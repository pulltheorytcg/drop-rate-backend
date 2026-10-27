"""Daily free TCGplayer export ingestion, with exact Dragon Ball identities.

TCGCSV permits backend ingestion (https://tcgcsv.com/docs). Never poll product
files more than once per day. Prices are US marketplace guides converted to
GBP, not UK sold comparables or physical inventory valuations.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx

from .access_control import require_platform_admin
from .db import user_connection
from .dragon_ball_market import FUSION, MASTERS
from .fx import EcbHistoricalFxProvider
from .object_storage import configured_object_storage
from .one_piece_market import normalized
from .pokewallet_dragon_ball_market import READ_SQL, reference_release
from .pokewallet_one_piece_market import WRITE_SQL
from .reference_market import _minor

SOURCE = "TCGCSV_TCGPLAYER_CATALOGUE"
JOB = "tcgcsv_dragon_ball"
REVISION = 1
BASE = "https://tcgcsv.com"
CATEGORIES = {27: MASTERS, 80: FUSION}
MAX_GROUPS = 100
MAX_REQUESTS = 2 * MAX_GROUPS + 4
MAX_RESPONSE_BYTES = 8_000_000
MAX_RUN_BYTES = 64_000_000


class SourceError(ValueError):
    pass


def build_timestamp(value, now):
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise SourceError("INVALID_BUILD_TIMESTAMP") from None
    if stamp.tzinfo is None or not now-timedelta(days=3) <= stamp <= now+timedelta(minutes=5):
        raise SourceError("STALE_OR_FUTURE_BUILD")
    return stamp


def collection(body, *, prices=False):
    if (not isinstance(body, dict) or body.get("success") is not True
            or body.get("errors") != [] or not isinstance(body.get("results"), list)
            or any(not isinstance(row, dict) for row in body["results"])):
        raise SourceError("INVALID_COLLECTION")
    rows = body["results"]
    if (not prices and (type(body.get("totalItems")) is not int
                       or body["totalItems"] != len(rows))) or len(rows) > 20000:
        raise SourceError("INCOMPLETE_COLLECTION")
    return rows


def extended(product, field):
    fields = product.get("extendedData")
    if not isinstance(fields, list):
        return None
    values = [r.get("value") for r in fields if isinstance(r, dict) and r.get("name") == field]
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def release_targets(refs, groups, category):
    """A single exact source release title and abbreviation; no fuzzy names."""
    source = defaultdict(list)
    for group in groups:
        if (group.get("categoryId") != category or type(group.get("groupId")) is not int
                or not isinstance(group.get("name"), str)):
            raise SourceError("GROUP_IDENTITY_INVALID")
        source[normalized(group["name"])].append(group)
    by_set = defaultdict(list)
    for ref in refs:
        release = reference_release(ref)
        if ref.get("system_code") == CATEGORIES[category] and release:
            by_set[(ref["set_id"], release)].append(ref)
    targets = []
    for (_, release), references in by_set.items():
        candidates = source.get(release, [])
        if len(candidates) != 1:
            continue
        group = candidates[0]
        # Preserve printed number spelling, including BT1 versus BT01.
        prefixes = {r["card_number"].split("-", 1)[0] for r in references}
        if prefixes != {group.get("abbreviation")}:
            continue
        targets.append((group, references))
    # Two reference releases cannot both claim one marketplace release.
    counts = defaultdict(int)
    for group, _ in targets:
        counts[group["groupId"]] += 1
    return [(g, r) for g, r in targets if counts[g["groupId"]] == 1]


def matched_printings(refs, products, group, now):
    """All products, including unpriced variants, participate in collisions."""
    by_number, ref_numbers = defaultdict(list), defaultdict(list)
    ids = set()
    for product in products:
        pid = product.get("productId")
        if (type(pid) is not int or pid <= 0 or pid in ids
                or product.get("categoryId") != group["categoryId"]
                or product.get("groupId") != group["groupId"]):
            raise SourceError("PRODUCT_IDENTITY_INVALID")
        ids.add(pid)
        fields = product.get("extendedData")
        if not isinstance(fields, list) or any(not isinstance(f, dict) for f in fields):
            raise SourceError("PRODUCT_NUMBER_INVALID")
        number_fields = [f for f in fields if f.get("name") == "Number"]
        if len(number_fields) > 1 or (number_fields and not isinstance(number_fields[0].get("value"), str)):
            raise SourceError("PRODUCT_NUMBER_INVALID")
        number = extended(product, "Number")
        # A malformed/suffixed number or an unnumbered variant must not vanish
        # from collision checks just because the base product is well formed.
        numbers = set(re.findall(r"[A-Z]{1,3}\d{1,2}-\d{2,3}", number or str(product.get("name") or "")))
        for candidate_number in numbers:
            by_number[candidate_number].append(product)
    for ref in refs:
        ref_numbers[ref["card_number"]].append(ref)
    matches = []
    for number, references in ref_numbers.items():
        candidates = by_number.get(number, [])
        if len(references) != 1 or len(candidates) != 1:
            continue
        ref, product = references[0], candidates[0]
        if extended(product, "Number") != number:
            continue
        sale = product.get("presaleInfo")
        if not isinstance(sale, dict) or sale.get("isPresale") is not False:
            continue
        released = sale.get("releasedOn")
        if not isinstance(released, str) or released[:10] > now.date().isoformat():
            continue
        try:
            datetime.fromisoformat(released)
        except ValueError:
            continue
        name = str(product.get("name") or "")
        for suffix in (" - " + number, " (" + number + ")"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        if normalized(name) != normalized(ref["name"]):
            continue
        # The source URL must identify this product on the real marketplace.
        if not re.fullmatch(r"https://www[.]tcgplayer[.]com/product/" + str(product["productId"]) + r"(?:/[a-zA-Z0-9/-]+)?", str(product.get("url") or "")):
            continue
        matches.append((ref, product))
    return matches


def guide_quote(ref, product, prices, observed, conversion):
    rows = [p for p in prices if p.get("productId") == product["productId"]]
    finishes = [p.get("subTypeName") for p in rows]
    if (not rows or any(f not in {"Normal", "Holofoil", "Foil"} for f in finishes)
            or len(finishes) != len(set(finishes))):
        return None
    # Distinct foil spellings in one product are ambiguous, even if unpriced.
    if "Foil" in finishes and "Holofoil" in finishes:
        return None
    rows.sort(key=lambda p: p["subTypeName"] != "Normal")
    for row in rows:
        try:
            original = _minor(row.get("marketPrice"))
            converted = int((Decimal(original) * conversion.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (ValueError, TypeError, ArithmeticError):
            continue
        if original <= 0 or converted <= 0:
            continue
        return dict(source=SOURCE, aggregator="TCGCSV", market="TCGPLAYER",
            source_product_id=product["productId"], source_set_id=product["groupId"],
            source_product_url=product["url"], source_field="marketPrice",
            original_currency="USD", original_minor=original, price_gbp_minor=converted,
            observed_at=observed.isoformat(), finish=row["subTypeName"],
            valuation_role="MIXED_LANGUAGE_REFERENCE", physical_valuation_eligible=False,
            physical_language_confirmed=False, condition_specific=False, sold_comparable=False,
            guide_scope="TCGplayer US marketplace guide converted to GBP",
            match_basis="EXACT_RELEASE_CODE_NUMBER_NAME_UNIQUE_SOURCE_PRODUCT",
            reference_printing_id=ref["provider_id"], reference_rarity=ref.get("rarity"),
            reference_language=ref["language"],
            reference_identity={k: ref[k] for k in ("name", "set_id", "card_number", "set_name")},
            fx_rate_to_gbp=str(conversion.rate), fx_source=conversion.source,
            fx_effective_at=conversion.effective_at.isoformat(), fx_retrieved_at=conversion.retrieved_at.isoformat())
    return None


class FreeExportClient:
    def __init__(self, http):
        self.http, self.requests, self.bytes = http, 0, 0
        self.digests = {}

    async def get(self, path, *, timestamp=False):
        if (path != "last-updated.txt" and not re.fullmatch(r"tcgplayer/(?:27|80)/(?:groups|[1-9][0-9]*/(?:products|prices))", path)):
            raise SourceError("UNREVIEWED_ENDPOINT")
        if self.requests >= MAX_REQUESTS:
            raise SourceError("REQUEST_BUDGET_EXHAUSTED")
        await asyncio.sleep(.25)
        self.requests += 1
        async with self.http.stream("GET", BASE + "/" + path,
                headers={"User-Agent": "DropRate/1.0 (daily catalogue sync)", "Accept": "text/plain" if timestamp else "application/json"}) as response:
            if response.status_code != 200:
                raise SourceError("UPSTREAM_HTTP_" + str(response.status_code))
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                self.bytes += len(chunk)
                if len(data) > MAX_RESPONSE_BYTES or self.bytes > MAX_RUN_BYTES:
                    raise SourceError("RESPONSE_BYTE_LIMIT")
        self.digests[path] = hashlib.sha256(data).hexdigest()
        return data.decode() if timestamp else json.loads(data)


def needs_value(ref, now):
    return (not ref.get("has_detail_value") and
            (not ref.get("existing_catalogue_value") or
             (ref.get("existing_source") == SOURCE and
              isinstance(ref.get("existing_pricing_updated_at"), datetime) and
              ref["existing_pricing_updated_at"] < now-timedelta(days=1))))


async def refresh_exports(pool, actor, *, previous=None, http_client=None, storage=None, fx=None):
    """Caller holds catalogue maintenance lock. Persist receipt before requests."""
    now = datetime.now(timezone.utc)
    if previous and previous["started_at"] > now-timedelta(hours=24):
        return None
    report = dict(importer_revision=REVISION, requests=0, matched=0, eligible_quotes=0,
                  writes_attempted=0, groups_checked=0, source=SOURCE, provider_failures=0)
    async with user_connection(pool, actor, str(uuid4())) as connection:
        await require_platform_admin(connection)
        run = await connection.fetchval("insert into tcg.reference_sync_runs(source,status) values($1,'RUNNING') returning id", JOB)
    status, client = "INCOMPLETE", None
    owns_http = http_client is None
    try:
        storage = storage or configured_object_storage()
        if storage is None:
            raise SourceError("VERIFIED_R2_SNAPSHOT_REQUIRED")
        http_client = http_client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        client = FreeExportClient(http_client)
        observed = build_timestamp(await client.get("last-updated.txt", timestamp=True), now)
        report["source_build"] = observed.isoformat()
        old = (previous.get("report") or {}) if previous else {}
        if previous and previous["status"] == "COMPLETE" and old.get("source_build") == report["source_build"]:
            report.update(reason="SOURCE_UNCHANGED", source_snapshot=old.get("source_snapshot"))
            status = "COMPLETE"
            return report
        async with user_connection(pool, actor, str(uuid4())) as connection:
            refs = [dict(r) for r in await connection.fetch(READ_SQL)]
        targets = []
        for category in CATEGORIES:
            groups = collection(await client.get(f"tcgplayer/{category}/groups"))
            targets.extend((group, references) for group, references in release_targets(refs, groups, category)
                           if any(needs_value(ref, now) for ref in references))
        if len(targets) > MAX_GROUPS:
            raise SourceError("GROUP_BUDGET_EXCEEDED")
        targets.sort(key=lambda pair: (-sum(needs_value(r, now) for r in pair[1]), pair[0]["groupId"]))
        report["target_groups"] = len(targets)
        values, evidence = [], []
        conversion = None
        fx = fx or EcbHistoricalFxProvider(timeout_seconds=6)
        for group, references in targets:
            path = f"tcgplayer/{group['categoryId']}/{group['groupId']}"
            products = collection(await client.get(path + "/products"))
            prices = collection(await client.get(path + "/prices"), prices=True)
            matches = matched_printings(references, products, group, now)
            report["matched"] += len(matches)
            report["groups_checked"] += 1
            for ref, product in matches:
                if not needs_value(ref, now):
                    continue
                if conversion is None:
                    conversion = await fx.quote(base_currency="USD", quote_currency="GBP", at=observed)
                quote = guide_quote(ref, product, prices, observed, conversion)
                if quote is None:
                    continue
                evidence.append(dict(provider=ref["provider"], system_code=ref["system_code"],
                    language=ref["language"], provider_id=ref["provider_id"], quote=quote))
                values.append((ref["provider"], ref["system_code"], ref["language"], ref["provider_id"],
                    [quote], quote["price_gbp_minor"], quote["price_gbp_minor"], observed, now,
                    now+timedelta(days=1), ref["name"], ref["set_id"], ref["card_number"],
                    ref["set_name"], ref.get("rarity"), SOURCE))
        if build_timestamp(await client.get("last-updated.txt", timestamp=True), now) != observed:
            raise SourceError("SOURCE_BUILD_CHANGED")
        report["eligible_quotes"] = len(values)
        # Cache minimal factual price evidence, never card text or artwork.
        snapshot = dict(source_build=observed.isoformat(), request_sha256=client.digests, quotes=evidence)
        with TemporaryDirectory(prefix="drop-rate-tcgcsv-") as folder:
            path = Path(folder) / "tcgcsv.json.gz"
            path.write_bytes(gzip.compress(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
            report["source_snapshot"] = await asyncio.to_thread(storage.put_verified_file, path,
                category="exports", content_type="application/gzip")
        if report["source_snapshot"].get("verified") is not True:
            raise SourceError("SNAPSHOT_VERIFICATION_FAILED")
        for start in range(0, len(values), 100):
            async with user_connection(pool, actor, str(uuid4())) as connection:
                await require_platform_admin(connection)
                await connection.executemany(WRITE_SQL, values[start:start+100])
            report["writes_attempted"] += len(values[start:start+100])
        status = "COMPLETE"
    except asyncio.CancelledError:
        report.update(reason="INTERRUPTED", provider_failures=1)
        raise
    except Exception as exc:
        report.update(reason=str(exc) if isinstance(exc, SourceError) else type(exc).__name__, provider_failures=1)
    finally:
        if client:
            report.update(requests=client.requests, downloaded_bytes=client.bytes)
        if owns_http and http_client:
            await http_client.aclose()
        async with user_connection(pool, actor, str(uuid4())) as connection:
            await connection.execute("""update tcg.reference_sync_runs set status=$2,finished_at=now(),
                sets_loaded=$3,cards_loaded=$4,report=$5::jsonb where id=$1""",
                run, status, report["groups_checked"], report["writes_attempted"], json.dumps(report))
    return report
