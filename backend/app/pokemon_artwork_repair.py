"""Probe documented TCGdex manifest omissions; repair only blank reference URLs.

No inventory/media approval, copied R2 objects, cross-language matching or guessed
set aliases. Every written URL has passed an actual same-origin image GET. The
individually reviewed M1S 001–056 exception additionally pins the exact image bytes.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from PIL import Image, UnidentifiedImageError

from .access_control import require_platform_admin
from .db import user_connection

VERSION = "TCGDEX_MANIFEST_ARTWORK_V1"
MAX_ROWS = 5000
MAX_IMAGE_BYTES = 2_000_000
MAX_PIXELS = 4_000_000
ISSUES = {
    "English": "https://github.com/tcgdex/cards-database/issues/2362",
    "Japanese": "https://github.com/tcgdex/cards-database/issues/2477",
}
# Fixed, reviewed provider reports. M1S is restricted below to the independently
# reviewed 001–056 images; its misnumbered remainder and digital Pocket stay out.
SETS = {
    "English": {"mep": "me", "svp": "sv"},
    "Japanese": {
        "M1S": "M", "M4": "M", "S5I": "S", "S6H": "S", "S6K": "S", "S7D": "S",
        "S8": "S", "S8b": "S", "S12a": "S",
        **{name: "SM" for name in (
            "SM10", "SM10b", "SM11", "SM11a", "SM11b", "SM12", "SM12a",
            "SM1M", "SM1S", "SM2L", "SM3H", "SM3N", "SM4A", "SM4S",
            "SM5M", "SM5S", "SM6", "SM6a", "SM6b", "SM7", "SM7a",
            "SM7b", "SM8", "SM8a", "SM8b", "SM9", "SM9a", "SM9b")},
        "SV11B": "SV", "SV5M": "SV", "SV10": "SV", "SV8": "SV",
    },
}
LOCALES = {"English": "en", "Japanese": "ja"}
M1S_REVIEW_PATH = Path(__file__).resolve().parents[1] / "data" / "pokemon_artwork_m1s_20261027.json"
_M1S_REVIEW_BYTES = M1S_REVIEW_PATH.read_bytes()
M1S_REVIEW = json.loads(_M1S_REVIEW_BYTES)
M1S_REVIEW_SHA256 = hashlib.sha256(_M1S_REVIEW_BYTES).hexdigest()
M1S_REVIEWED_CARDS = {card["local_id"]: card for card in M1S_REVIEW["cards"]}
READ_SQL = """
select r.*, count(*) over() as candidate_total
from tcg.reference_cards r
join tcg.reference_sets s using(provider,system_code,language,set_id)
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and nullif(btrim(r.image_url),'') is null
 and (s.release_date is null or s.release_date<=current_date)
 and ((r.language='English' and r.set_id=any($1::text[]))
   or (r.language='Japanese' and r.set_id=any($2::text[])))
 and ($4::text is null or (r.language,r.set_id,r.provider_id)>($4::text,$5::text,$6::text))
order by r.language,r.set_id,r.provider_id limit $3
"""
WRITE_SQL = """
with candidates as (
 select * from jsonb_to_recordset($1::jsonb) as c(
  language text,set_id text,provider_id text,name text,card_number text,
  source_url text,local_id text,image_url text,image_reference jsonb)
)
update tcg.reference_cards r set image_url=c.image_url,
 evidence=r.evidence || jsonb_build_object('image_reference',c.image_reference)
from candidates c,tcg.reference_sets s
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and r.language=c.language and r.set_id=c.set_id and r.provider_id=c.provider_id
 and r.name=c.name and r.card_number=c.card_number and r.source_url=c.source_url
 and r.evidence->>'provider_local_id'=c.local_id
 and nullif(btrim(r.image_url),'') is null
 and s.provider=r.provider and s.system_code=r.system_code
 and s.language=r.language and s.set_id=r.set_id
 and (s.release_date is null or s.release_date<=current_date)
returning r.language,r.set_id,r.provider_id
"""


def _reviewed_m1s(item):
    """Exact reviewed identity only; never extend the safe range by an offset."""
    local = item.get("local_id")
    if (item.get("language") != "Japanese" or item.get("set_id") != "M1S"
            or not isinstance(local, str) or not re.fullmatch(r"0[0-9]{2}", local)
            or not 1 <= int(local) <= 56):
        return None
    reviewed = M1S_REVIEWED_CARDS.get(local)
    if not reviewed or any(item.get(key) != reviewed[key] for key in
                           ("provider_id", "name", "card_number", "image_url")):
        return None
    if item.get("source_url") != f"https://api.tcgdex.net/v2/ja/cards/M1S-{local}":
        return None
    return reviewed


def candidate(row):
    """Bind a documented CDN path to the exact existing provider identity."""
    if row.get("provider") != "TCGdex" or row.get("system_code") != "POKEMON_TCG":
        return None
    language, set_id = row.get("language"), row.get("set_id")
    series = SETS.get(language, {}).get(set_id)
    if not series or row.get("image_url") and str(row["image_url"]).strip():
        return None
    evidence = row.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except (ValueError, TypeError):
            return None
    local = evidence.get("provider_local_id") if isinstance(evidence, dict) else None
    if not isinstance(local, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,24}", local):
        return None
    ident = f"{set_id}-{local}"
    name, number = row.get("name"), row.get("card_number")
    source = f"https://api.tcgdex.net/v2/{LOCALES[language]}/cards/{ident}"
    if (row.get("provider_id") != ident or row.get("source_url") != source
            or not isinstance(name, str) or not name.strip()
            or not isinstance(number, str) or number.split("/", 1)[0] != local):
        return None
    item = {"language": language, "set_id": set_id, "provider_id": ident,
            "name": name, "card_number": number, "source_url": source, "local_id": local,
            "image_url": f"https://assets.tcgdex.net/{LOCALES[language]}/{series}/{set_id}/{local}/high.webp"}
    if set_id == "M1S" and _reviewed_m1s(item) is None:
        return None
    return item


def decoded_image(data, *, expected_format="WEBP"):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("INVALID_IMAGE_SIZE")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if (image.format != expected_format or expected_format not in {"WEBP", "PNG"}
                    or getattr(image, "is_animated", False)
                    or width < 200 or height < 200 or width * height > MAX_PIXELS
                    or not 0.60 <= width / height <= 0.85):
                raise ValueError("INVALID_IMAGE")
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("INVALID_IMAGE") from exc
    return {"content_sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "width": width, "height": height}


async def _probe_url(client, url, mime_type, image_format):
    try:
        async with client.stream("GET", url, follow_redirects=False,
                                 timeout=httpx.Timeout(10),
                                 headers={"Accept": mime_type}) as response:
            if response.status_code != 200:
                return None, f"HTTP_{response.status_code}"
            if response.headers.get("content-type", "").split(";", 1)[0].lower() != mime_type:
                return None, "INVALID_CONTENT_TYPE"
            size = response.headers.get("content-length")
            if size is not None:
                try:
                    if not 1 <= int(size) <= MAX_IMAGE_BYTES:
                        return None, "INVALID_IMAGE_SIZE"
                except ValueError:
                    return None, "INVALID_IMAGE_SIZE"
            raw = bytearray()
            async for part in response.aiter_bytes():
                raw.extend(part)
                if len(raw) > MAX_IMAGE_BYTES:
                    return None, "INVALID_IMAGE_SIZE"
        metadata = await asyncio.to_thread(decoded_image, bytes(raw), expected_format=image_format)
    except httpx.HTTPError:
        return None, "REQUEST_FAILED"
    except ValueError:
        return None, "INVALID_IMAGE"
    return {**metadata, "image_url": url}, None


async def probe(client, item):
    """Same card/locale/path only; no redirects or alternative printing guesses."""
    language, set_id, local = item.get("language"), item.get("set_id"), item.get("local_id")
    series = SETS.get(language, {}).get(set_id)
    if (not series or not isinstance(local, str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,24}", local)
            or item.get("provider_id") != f"{set_id}-{local}"):
        return None, "UNSAFE_IDENTITY"
    base = f"https://assets.tcgdex.net/{LOCALES[language]}/{series}/{set_id}/{local}"
    if item.get("image_url") != base + "/high.webp":
        return None, "UNSAFE_URL"
    reviewed = _reviewed_m1s(item) if set_id == "M1S" else None
    if set_id == "M1S" and reviewed is None:
        return None, "UNSAFE_IDENTITY"
    if reviewed:
        # The set contains known misnumbered files. Accept only the exact full
        # raster whose Japanese title, set mark and printed number were reviewed.
        # A different encoding or thumbnail requires its own review; no fallback.
        metadata, error = await _probe_url(client, base + "/high.webp", "image/webp", "WEBP")
        if metadata and metadata["content_sha256"] != reviewed["content_sha256"]:
            return None, "REVIEWED_IMAGE_BYTES_CHANGED"
        return metadata, error
    # These formats/qualities are documented by TCGdex. Some high assets are
    # absent while their exact low or PNG sibling exists; retry only a 404.
    for suffix, mime_type, image_format in (
            ("high.webp", "image/webp", "WEBP"),
            ("low.webp", "image/webp", "WEBP"),
            ("high.png", "image/png", "PNG")):
        metadata, error = await _probe_url(client, base + "/" + suffix, mime_type, image_format)
        if error != "HTTP_404":
            return metadata, error
    return None, "HTTP_404"


async def probe_rows(rows, *, client=None, progress=None, max_seconds=120):
    """Read-only image verification, also usable without database credentials."""
    if len(rows) > MAX_ROWS:
        raise ValueError("Artwork probe exceeds bounded rows")
    if type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 240:
        raise ValueError("Artwork time budget must be between 1 and 240 seconds")
    seen = set()
    items, skipped = [], 0
    for row in rows:
        item = candidate(dict(row))
        if item is None:
            skipped += 1
            continue
        key = (item["language"], item["provider_id"])
        if key in seen:
            raise ValueError("Duplicate artwork reference identity")
        seen.add(key)
        items.append(item)
    own_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
    failures = Counter()
    verified = []
    deadline = time.monotonic() + max_seconds
    timed_out = False
    last_examined = None
    by_set = defaultdict(lambda: {"requested": 0, "verified": 0, "failed": 0})
    try:
        # Bounded batches + spacing: at most four requests in flight.
        for start in range(0, len(items), 4):
            batch = items[start:start + 4]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                async with asyncio.timeout(remaining):
                    outcomes = await asyncio.gather(*(probe(client, item) for item in batch))
            except TimeoutError:
                timed_out = True
                break
            for item, (metadata, error) in zip(batch, outcomes):
                key = (item["language"], item["set_id"])
                by_set[key]["requested"] += 1
                if error:
                    failures[error] += 1
                    by_set[key]["failed"] += 1
                    continue
                evidence = {"verification": VERSION, "source_url": item["source_url"],
                    "image_url": item["image_url"], "provider_issue_url": ISSUES[item["language"]],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "scope": "REFERENCE_ONLY_NOT_APPROVED_MEDIA", **metadata}
                if reviewed := _reviewed_m1s(item):
                    evidence.update(
                        verification="TCGDEX_REVIEWED_IMAGE_BYTES_V1",
                        provider_issue_url=M1S_REVIEW["provider_issue_url"],
                        review_manifest=M1S_REVIEW_PATH.name,
                        review_manifest_sha256=M1S_REVIEW_SHA256,
                        visual_reviewed_at=M1S_REVIEW["reviewed_at"],
                        visual_review_method=M1S_REVIEW["review_method"],
                        printed_card_number=reviewed["printed_card_number"],
                        visual_review_page=reviewed["visual_review_page"],
                        visual_review_page_sha256=reviewed["visual_review_page_sha256"])
                verified.append({**item, "image_url": metadata["image_url"], "image_reference": evidence})
                by_set[key]["verified"] += 1
            if batch:
                last_examined = [batch[-1]["language"], batch[-1]["set_id"], batch[-1]["provider_id"]]
            if progress and (start + len(batch)) % 100 == 0:
                progress({"examined": start + len(batch), "verified": len(verified),
                          "failed": sum(failures.values()), "total": len(items)})
            if start + len(batch) < len(items):
                await asyncio.sleep(0.15)
    finally:
        if own_client:
            await client.aclose()
    # A generic successful placeholder must not become thousands of card images.
    digests = Counter(x["image_reference"]["content_sha256"] for x in verified)
    unique = []
    for item in verified:
        if digests[item["image_reference"]["content_sha256"]] > 1:
            failures["DUPLICATE_IMAGE_BYTES"] += 1
            key = (item["language"], item["set_id"])
            by_set[key]["verified"] -= 1
            by_set[key]["failed"] += 1
        else:
            unique.append(item)
    examined = sum(value["requested"] for value in by_set.values())
    report = {"version": VERSION, "requested": len(rows), "candidates": len(items),
              "examined": examined, "unexamined": len(items) - examined,
              "timed_out": timed_out, "max_seconds": max_seconds, "last_examined": last_examined,
              "verified": len(unique), "failed": sum(failures.values()), "skipped": skipped,
              "failure_counts": dict(sorted(failures.items())),
              "sets": [{"language": key[0], "set_id": key[1], **value}
                       for key, value in sorted(by_set.items())]}
    return unique, report


async def repair(pool, actor: UUID, *, apply=False, limit=MAX_ROWS, client=None, progress=None, max_seconds=120, after=None):
    if not isinstance(actor, UUID) or type(apply) is not bool:
        raise ValueError("Artwork repair requires a UUID administrator and boolean apply")
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError("Artwork repair limit must be between 1 and 5000")
    if type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 240:
        raise ValueError("Artwork time budget must be between 1 and 240 seconds")
    if after is not None and (not isinstance(after, (list, tuple)) or len(after) != 3
            or any(not isinstance(value, str) or not 1 <= len(value) <= 200 or chr(0) in value for value in after)
            or after[0] not in SETS or after[1] not in SETS[after[0]]):
        raise ValueError("Artwork cursor must contain an allowed language, set and provider ID")
    cursor = list(after) if after is not None else [None, None, None]
    request_id = str(uuid4())
    async with user_connection(pool, actor, request_id) as conn:
        await require_platform_admin(conn)
        rows = await conn.fetch(READ_SQL, list(SETS["English"]), list(SETS["Japanese"]), limit, *cursor)
    run_id = None
    if apply:
        async with user_connection(pool, actor, request_id) as conn:
            await require_platform_admin(conn)
            run_id = await conn.fetchval(
                "insert into tcg.reference_sync_runs(source,status) values('tcgdex_artwork_repair','RUNNING') returning id")
    report = {"version": VERSION, "apply": apply, "requested": len(rows), "updated": 0,
              "candidate_total": int(rows[0]["candidate_total"]) if rows else 0, "input_cursor": after}
    try:
        verified, probe_report = await probe_rows(rows, client=client, progress=progress, max_seconds=max_seconds)
        report.update(probe_report)
        report["more_available"] = report["candidate_total"] > len(rows) or report["unexamined"] > 0
        end_cursor = (report.get("last_examined") if report["timed_out"] else
                      [rows[-1]["language"], rows[-1]["set_id"], rows[-1]["provider_id"]] if rows else None)
        report["next_cursor"] = end_cursor if report["more_available"] else None
        if apply:
            for start in range(0, len(verified), 100):
                batch = verified[start:start + 100]
                for item in batch:
                    item["image_reference"].update(actor_user_id=str(actor), run_id=str(run_id))
                async with user_connection(pool, actor, request_id) as conn:
                    await require_platform_admin(conn)
                    changed = await conn.fetch(WRITE_SQL, json.dumps(batch, ensure_ascii=False))
                report["updated"] += len(changed)
        report["changed_before_write"] = len(verified) - report["updated"] if apply else 0
        report["status"] = ("PARTIAL_TIME_BUDGET" if report["timed_out"] else
                            "VERIFIED_WITH_GAPS" if report["failed"] or report["skipped"] else "VERIFIED")
        return report
    except BaseException as exc:
        report.update(status="INTERRUPTED" if isinstance(exc, asyncio.CancelledError) else "FAILED",
                      error_type=type(exc).__name__)
        raise
    finally:
        if run_id:
            async with user_connection(pool, actor, request_id) as conn:
                await require_platform_admin(conn)
                await conn.execute("""update tcg.reference_sync_runs set status=$2,
                    finished_at=now(),sets_loaded=$3,cards_loaded=$4,report=$5::jsonb where id=$1""",
                    run_id, "COMPLETE" if report.get("status") in {"VERIFIED", "VERIFIED_WITH_GAPS"} else "INCOMPLETE",
                    len(report.get("sets", [])), report["updated"], json.dumps(report))
