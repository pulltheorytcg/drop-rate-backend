"""R2-first delivery and transactional, on-demand canonical identities.

R2 I/O NEVER awaits inside a request's database transaction. Cold reads schedule
a bounded background load and return 503; startup prewarming loads outside SQL.
Only the small authenticated SQL pointer authorizes a cached generation.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import heapq
import json
import logging
import os
import re
import time

from fastapi import HTTPException

from . import r2_first_catalogue as codec
from .access_control import current_access_context, require_platform_admin
from .db import user_connection
from .object_storage import ObjectStorageConfig, S3ObjectStorage

log = logging.getLogger(__name__)
TCG_GAMES = {"YUGIOH": "Yu-Gi-Oh!", "DISNEY_LORCANA": "Disney Lorcana",
             "MAGIC_THE_GATHERING": "Magic: The Gathering", "RIFTBOUND": "Riftbound"}
GAMES = {**TCG_GAMES, "SPORTS_CARDS": "Sports Cards", "FIGURES": "Figures"}
CATEGORY_SYSTEMS = {"TCG": frozenset(TCG_GAMES), "SPORTS": frozenset({"SPORTS_CARDS"}),
                    "FIGURES": frozenset({"FIGURES"})}
SOURCE_ATTRIBUTION = {
    "ygoprodeck": {"label": "YGOPRODeck", "url": "https://ygoprodeck.com/api-guide/",
        "coverage": "English printing references; edition and finish need physical review."},
    "lorcast": {"label": "Lorcast", "url": "https://lorcast.com/docs/api",
        "coverage": "English printing metadata; physical foil finish is not established."},
    "mtgjson": {"label": "MTGJSON · MIT", "url": "https://mtgjson.com/license/",
        "coverage": "English paper printing and finish references; no artwork or price feed."},
    "cardcollectorcapital": {"label": "Card Collector Capital · CC BY 4.0",
        "url": "https://cardcollectorcapital.com/data",
        "coverage": "Selected Bowman checklists only, reviewed 27 October 2026. Not all sports cards; physical parallel and language need confirmation."},
    "reviewed_figures": {"label": "Drop Rate · reviewed official product facts",
        "url": "https://github.com/pulltheorytcg/drop-rate-backend/blob/main/docs/R2_CATALOGUE_EXPANSION_20261104.md",
        "coverage": "Four individually reviewed Funko product references only. Not a complete Funko catalogue or an automated Funko feed. Confirm the exact edition on your item."},
}
MAX_PARTITIONS = 12
MAX_ACTIVE_RAW_BYTES = 256_000_000  # SQLite/FTS needs additional rebuildable disk.
_cache: OrderedDict[str, codec.Snapshot] = OrderedDict()
_loading: dict[str, asyncio.Task] = {}
_failures: dict[str, float] = {}
_leases: dict[int, int] = {}
_retired: dict[int, codec.Snapshot] = {}
_load_semaphore = asyncio.Semaphore(1)


@contextmanager
def _borrow(snapshots):
    for snapshot in snapshots:
        _leases[id(snapshot)] = _leases.get(id(snapshot), 0) + 1
    try:
        yield
    finally:
        for snapshot in snapshots:
            identity = id(snapshot)
            remaining = _leases[identity] - 1
            if remaining:
                _leases[identity] = remaining
            else:
                _leases.pop(identity)
                retired = _retired.pop(identity, None)
                if retired is not None:
                    retired.close()


def _retire(snapshot):
    if _leases.get(id(snapshot), 0):
        _retired[id(snapshot)] = snapshot
    else:
        snapshot.close()


def enabled() -> bool:
    return os.getenv("TCG_R2_FIRST_CATALOGUE_ENABLED", "false").lower() in {"true", "1"}


def storage():
    config = ObjectStorageConfig.from_env()
    if config is None:
        raise RuntimeError("Private R2 storage is not configured")
    return S3ObjectStorage(config)


async def sources(connection) -> list[dict]:
    if not enabled():
        return []
    if not await connection.fetchval(
            "select to_regclass('tcg_private.r2_first_catalogue_publications') is not null"):
        raise HTTPException(503, "R2 catalogue registry is not ready")
    rows = await connection.fetch("""
        select * from tcg_private.r2_first_catalogue_publications
        where active order by provider,system_code,language limit 13
        """)
    if len(rows) > MAX_PARTITIONS:
        raise HTTPException(503, "R2 catalogue partition capacity needs review")
    return [{**dict(row), "game": GAMES.get(row["system_code"], row["system_code"])} for row in rows]


def _manifest_binding(manifest, publication):
    if codec.manifest_digest(manifest) != publication["manifest_sha256"] or any(
        manifest[field] != publication[field] for field in (
            "provider", "system_code", "language", "source_revision", "source_url",
            "permission_ref", "record_count")):
        raise codec.R2FirstCatalogueError("Publication binding mismatch")
    if publication.get("raw_bytes", manifest["raw_bytes"]) != manifest["raw_bytes"]:
        raise codec.R2FirstCatalogueError("Publication byte bound mismatch")


def _binding(snapshot, publication):
    _manifest_binding(snapshot.manifest, publication)


async def _load(publication, object_store=None):
    digest = publication["manifest_sha256"]
    snapshot = None
    acquired = False
    try:
        await _load_semaphore.acquire()
        acquired = True
        cached = _cache.get(digest)
        if cached is not None:
            _binding(cached, publication)
            return
        object_store = object_store or storage()
        manifest = await codec.load_manifest(digest, object_store)
        _manifest_binding(manifest, publication)
        retained_bytes = sum(row.manifest["raw_bytes"] for key, row in _cache.items() if key != digest)
        # Retire superseded generations of this exact partition first. Active
        # request leases finish safely; no source data is deleted from R2.
        for old_digest, old_snapshot in list(_cache.items()):
            if old_digest != digest and tuple(old_snapshot.manifest[name] for name in (
                    "provider", "system_code", "language")) == tuple(manifest[name] for name in (
                    "provider", "system_code", "language")):
                retained_bytes -= old_snapshot.manifest["raw_bytes"]
                _cache.pop(old_digest)
                _retire(old_snapshot)
        retired_bytes = sum(row.manifest["raw_bytes"] for row in _retired.values())
        if retained_bytes+retired_bytes+manifest["raw_bytes"] > MAX_ACTIVE_RAW_BYTES:
            raise codec.R2FirstCatalogueError("Aggregate catalogue index budget exceeded")
        snapshot = await codec.load_catalogue(manifest, object_store)
        _binding(snapshot, publication)
        previous = _cache.pop(digest, None)
        if previous is not None:
            _retire(previous)
        _cache[digest] = snapshot
        snapshot = None
        while len(_cache) > MAX_PARTITIONS:
            _, old = _cache.popitem(last=False)
            _retire(old)
        _failures.pop(digest, None)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _failures[digest] = time.monotonic() + 60
        log.error("R2_FIRST_LOAD_FAILED type=%s digest=%s", type(exc).__name__, digest)
    finally:
        if snapshot is not None:
            snapshot.close()
        if acquired:
            _load_semaphore.release()
        _loading.pop(digest, None)


def _cached(publication):
    digest = publication["manifest_sha256"]
    snapshot = _cache.get(digest)
    if snapshot is not None:
        try:
            _binding(snapshot, publication)
        except codec.R2FirstCatalogueError as exc:
            raise HTTPException(503, "Catalogue approval does not match the cached generation") from exc
        _cache.move_to_end(digest)
        return snapshot
    if (digest not in _loading and len(_loading) < MAX_PARTITIONS
            and _failures.get(digest, 0) <= time.monotonic()):
        _loading[digest] = asyncio.create_task(_load(dict(publication)))
    raise HTTPException(503, "This catalogue is warming or temporarily unavailable. Please retry shortly.",
                        headers={"Retry-After": "10"})


async def read(connection, *, system_code="", language="", provider=None, systems=None):
    publications = [row for row in await sources(connection)
                    if (not system_code or row["system_code"] == system_code)
                    and (systems is None or row["system_code"] in systems)
                    and (not language or row["language"] == language)
                    and (not provider or row["provider"] == provider)]
    return [_cached(row) for row in publications]


async def prewarm(pool, actor):
    async with user_connection(pool, actor, "r2-first-prewarm", readonly_snapshot=True) as connection:
        await require_platform_admin(connection)
        publications = await sources(connection)
    # Network calls begin after the SQL transaction has closed.
    active_digests = {row['manifest_sha256'] for row in publications}
    for digest, snapshot in list(_cache.items()):
        if digest not in active_digests:
            _cache.pop(digest)
            _retire(snapshot)
    for row in publications:
        if row["manifest_sha256"] not in _cache:
            await _load(row)


async def close():
    tasks = list(_loading.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _loading.clear()
    for snapshot in _cache.values():
        _retire(snapshot)
    _cache.clear()
    _failures.clear()


def _view(record, digest):
    details = record.get("details", {})
    result = {**record, "source_kind": "REFERENCE", "game": GAMES.get(record["system_code"]),
            "variant": record.get("finish") or details.get("variant") or details.get("edition") or "",
            "catalogue_id": None, "image_url": None, "market_value_minor": None,
            "market_value_high_minor": None, "market_refresh_needed": False,
            "market_value_source": None, "owned_count": 0, "owned_quantity": 0, "metadata_only": True,
            "reference_verified": False, "identity_review_required": True,
            "source_manifest_sha256": digest}
    attribution = SOURCE_ATTRIBUTION.get(record["provider"])
    if attribution:
        result["source_attribution"] = {**attribution, "notice_url": "/assets/catalogue-source-notices.txt"}
    year = details.get("source_year", "")
    year = int(year) if re.fullmatch(r"(?:18|19|20|21)[0-9]{2}|2200", year) else None
    if record["system_code"] == "SPORTS_CARDS":
        # Checklist sections are not proof of a specific parallel, nor of the
        # language on the seller's copy. Those required fields stay editable.
        set_name = record["set_name"]
        if year is not None and set_name.startswith(str(year) + " "):
            set_name = set_name[len(str(year))+1:]
        result["sports_card"] = {"system_code": "SPORTS_CARDS",
            "sport": details.get("sport"), "release_year": year,
            "manufacturer": details.get("manufacturer"), "set_name": set_name,
            "subject_name": details.get("player") or record["name"],
            "team": details.get("team"), "card_number": record["card_number"], "parallel": None}
        result["reference_scope"] = "PARTIAL_CHECKLIST_REFERENCE"
    if record["system_code"] == "FIGURES":
        result["language"] = None
        result["figure_details"] = {"system_code": "FIGURES", "release_year": year,
            **{key: details.get(key) for key in ("manufacturer", "franchise", "character",
                "product_line", "edition", "scale", "manufacturer_sku", "barcode_gtin")}}
        result["reference_scope"] = "PARTIAL_PRODUCT_REFERENCE"
    return result


async def resolve(connection, key):
    if not enabled() or not re.fullmatch(r"x:[a-f0-9]{64}", key):
        return None
    publications = await sources(connection)
    cold = False
    for publication in sorted(publications, key=lambda p: p["manifest_sha256"] not in _cache):
        try:
            snapshot = _cached(publication)
        except HTTPException:
            cold = True
            continue
        with _borrow([snapshot]):
            row = await asyncio.to_thread(snapshot.get, key)
            if row is not None:
                if row["release_date"] and row["release_date"] > datetime.now(timezone.utc).date().isoformat():
                    return None
                return _view(row, snapshot.manifest_digest)
    if cold:
        raise HTTPException(503, "Catalogue lookup is temporarily unavailable", headers={"Retry-After": "10"})
    return None


async def sets(connection, *, owner_id, system_code, language="", q="", limit=80, offset=0):
    snapshots = await read(connection, system_code=system_code, language=language)
    def summarize(owned_links):
        items = []
        for snapshot in snapshots:
            owner_sets = {}
            for key, link in owned_links.items():
                row = snapshot.get(key)
                if row is not None:
                    aggregate = owner_sets.setdefault(row["set_id"], [0, None, 0])
                    aggregate[0] += 1
                    if link["owned_value_minor"] is not None:
                        aggregate[1] = (aggregate[1] or 0) + link["owned_value_minor"]
                    aggregate[2] += link["unknown_values"]
            for row in snapshot.sets():
                if q and q.casefold() not in (row["set_id"] + " " + row["set_name"]).casefold():
                    continue
                owned = owner_sets.get(row["set_id"], [0, None, 0])
                items.append({**row, "provider": snapshot.provider, "system_code": snapshot.system_code,
                    "language": snapshot.language, "name": row["set_name"], "release_date": None,
                    "game": GAMES.get(snapshot.system_code), "indexed_count": row["count"],
                    "card_count": row["count"], "owned_count": owned[0],
                    "owned_value_minor": owned[1] if owned[0] else None, "unknown_values": owned[2],
                    "checklist_status": "PARTIAL", "image_url": None, "metadata_only": True})
        items.sort(key=lambda row: (row["name"].casefold(), row["provider"], row["language"], row["set_id"]))
        return {"items": items[offset:offset+limit], "total_count": len(items), "offset": offset,
                "has_more": offset+limit < len(items), "coverage": "METADATA_ONLY"}
    with _borrow(snapshots):
        links = await _owned_links(connection, owner_id, system_code)
        return await asyncio.to_thread(summarize, links)


async def _owned_links(connection, owner_id, system_code=""):
    rows = await connection.fetch("""
        select l.reference_key,l.catalogue_id,count(i.id)::integer owned_quantity,
            sum(i.market_value_minor) owned_value_minor,
            count(*) filter(where i.market_value_minor is null)::integer unknown_values
        from tcg.inventory_items i
        join tcg_private.r2_first_catalogue_links l on l.catalogue_id=i.catalogue_id
        where i.owner_id=$1 and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
            and ($2='' or l.system_code=$2)
        group by l.reference_key,l.catalogue_id order by l.reference_key limit 10001
        """, owner_id, system_code)
    if len(rows) > 10000:
        raise HTTPException(422, "This ownership filter needs a narrower catalogue scope")
    return {row["reference_key"]: dict(row) for row in rows}


async def _page_links(connection, owner_id, keys):
    if not keys:
        return {}
    return {row["reference_key"]: dict(row) for row in await connection.fetch("""
        select l.reference_key,l.catalogue_id,count(i.id)::integer owned_quantity
        from tcg_private.r2_first_catalogue_links l
        left join tcg.inventory_items i on i.catalogue_id=l.catalogue_id and i.owner_id=$1
            and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
        where l.reference_key=any($2::text[])
        group by l.reference_key,l.catalogue_id
        """, owner_id, keys)}


class _HeapRow:
    def __init__(self, row, partition, sort):
        self.row, self.partition, self.sort = row, partition, sort

    def __lt__(self, other):
        a, b, sort = self.row, other.row, self.sort
        if sort in {"oldest", "newest"}:
            if bool(a["release_date"]) != bool(b["release_date"]):
                return bool(a["release_date"])
            if a["release_date"] != b["release_date"]:
                return a["release_date"] > b["release_date"] if sort == "newest" else a["release_date"] < b["release_date"]
        if sort == "number" and a["card_number"].casefold() != b["card_number"].casefold():
            return a["card_number"].casefold() < b["card_number"].casefold()
        if a["name"].casefold() != b["name"].casefold():
            return a["name"].casefold() > b["name"].casefold() if sort == "name_desc" else a["name"].casefold() < b["name"].casefold()
        return a["key"] < b["key"]


def _merge_page(snapshots, *, q, set_id, product_type, keys, exclude_keys, sort, limit, offset):
    # At most one 100-record page per source, not every matching record in RAM.
    pages, cursors, totals, heap = [], [], [], []
    options = dict(q=q.strip(), set_id=set_id, product_type=product_type, keys=keys,
                   exclude_keys=exclude_keys, sort=sort, limit=100)
    for index, snapshot in enumerate(snapshots):
        page = snapshot.search(**options, offset=0)
        pages.append(page["items"])
        cursors.append(0)
        totals.append(page["total"])
        if page["items"]:
            heapq.heappush(heap, _HeapRow(page["items"][0], index, sort))
    output, visited = [], 0
    while heap and visited < offset+limit:
        entry = heapq.heappop(heap)
        if visited >= offset:
            output.append(_view(entry.row, snapshots[entry.partition].manifest_digest))
        visited += 1
        index = entry.partition
        cursors[index] += 1
        cursor = cursors[index]
        if cursor >= totals[index]:
            continue
        if cursor % 100 == 0:
            pages[index] = snapshots[index].search(**options, offset=cursor)["items"]
        heapq.heappush(heap, _HeapRow(pages[index][cursor % 100], index, sort))
    return {"items": output, "total_count": sum(totals), "offset": offset,
            "has_more": offset+limit < sum(totals), "metadata_only": True,
            "price_sort_available": False}


async def browse(connection, *, owner_id, q="", system_code="", language="", category="",
                 set_id="", provider=None, product_type="", owned="all", sort="name", keys=None,
                 limit=40, offset=0):
    systems = CATEGORY_SYSTEMS.get(category, frozenset(GAMES))
    if ((system_code and system_code not in systems)
            or category not in ("", "TCG", "SPORTS", "FIGURES", None)
            or product_type not in ("", "CARD", "FIGURE") or keys == []):
        return {"items": [], "has_more": False, "offset": offset, "total_count": 0}
    if offset > 10000:
        raise HTTPException(422, "Choose a set or narrow the search before browsing further")
    snapshots = await read(connection, system_code=system_code, language=language, provider=provider,
                           systems=systems)
    with _borrow(snapshots):
        selected_keys = None if keys is None else [key for key in keys if re.fullmatch(r"x:[a-f0-9]{64}", key)]
        excluded = None
        if owned != "all":
            owner_keys = set(await _owned_links(connection, owner_id, system_code))
            if owned == "owned":
                selected_keys = sorted(owner_keys if selected_keys is None else owner_keys.intersection(selected_keys))
            else:
                excluded = sorted(owner_keys)
        try:
            page = await asyncio.to_thread(_merge_page, snapshots, q=q, set_id=set_id,
                product_type=product_type, keys=selected_keys, exclude_keys=excluded,
                sort="name" if sort.startswith("value_") else sort, limit=limit, offset=offset)
        except codec.R2FirstCatalogueError as exc:
            raise HTTPException(503, "Catalogue index is temporarily unavailable") from exc
        links = await _page_links(connection, owner_id, [row["key"] for row in page["items"]])
        for row in page["items"]:
            link = links.get(row["key"], {})
            row.update({key: value for key, value in link.items() if key in {"catalogue_id", "owned_quantity"}})
            row["owned_count"] = row["owned_quantity"]
        return page


async def materialize(connection, item):
    access = await current_access_context(connection)
    # Never trust a caller's displayed fields or a previously approved digest.
    current = await resolve(connection, item["key"])
    if current is None:
        raise HTTPException(404, "Reference is no longer available")
    if current["source_manifest_sha256"] != item.get("source_manifest_sha256"):
        raise HTTPException(409, "Reference generation changed. Search again.")
    if current["product_type"] != "CARD" or current["system_code"] not in TCG_GAMES:
        raise HTTPException(422, "This category requires structured identity review")
    # A concurrent disable/version switch must not race a new canonical link.
    scope = tuple(current[name] for name in ("provider", "system_code", "language"))
    # Shared advisory lock matches the publisher's exclusive lock, without
    # granting sellers UPDATE/row-lock privileges on the publication registry.
    await connection.execute("select pg_advisory_xact_lock_shared(hashtextextended($1,0))",
                             "r2-first-publication:" + json.dumps(scope))
    approved = await connection.fetchval("""
        select manifest_sha256 from tcg_private.r2_first_catalogue_publications
        where provider=$1 and system_code=$2 and language=$3 and active
        """, *scope)
    if approved != current["source_manifest_sha256"]:
        raise HTTPException(409, "Reference approval changed. Search again.")
    from .catalogue_browser import reference_product
    product = reference_product(current)
    key = current["key"]
    await connection.execute("select pg_advisory_xact_lock(hashtextextended($1,0))", "r2-first:" + key)
    existing = await connection.fetchrow("""
        select c.* from tcg_private.r2_first_catalogue_links l
        join tcg.catalogue_products c on c.id=l.catalogue_id where l.reference_key=$1
        """, key)
    if existing is not None:
        return existing
    identity = "r2:v1:" + key[2:]
    row = await connection.fetchrow("""
        insert into tcg.catalogue_products(identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
        values($1,$2,$3,$4,$5,$6,$7,$8,$9) on conflict(identity_key) do nothing returning *
        """, identity, product.product_type, product.game, product.name, product.set_name,
        product.card_number, product.variant, product.rarity, product.language)
    if row is None:
        row = await connection.fetchrow("select * from tcg.catalogue_products where identity_key=$1", identity)
    if row is None:
        raise HTTPException(409, "Reference changed concurrently. Search again.")
    await connection.execute("""
        insert into tcg_private.r2_first_catalogue_links
        (reference_key,catalogue_id,provider,system_code,language,provider_id,source_manifest_sha256,created_by)
        values($1,$2,$3,$4,$5,$6,$7,$8)
        """, key, row["id"], current["provider"], current["system_code"], current["language"],
        current["provider_id"], current["source_manifest_sha256"], access["user_id"])
    return row
