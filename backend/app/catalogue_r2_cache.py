"""Verified exact-set reference inputs, with live SQL eligibility and ownership.

The cache contains only explicit shared reference columns. Every read compares
the object's raw SHA-256 with a fresh, bounded PostgreSQL source fingerprint.
It never caches an account response or a derived current-price decision.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import threading
import time
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .object_storage import ObjectStorageError, configured_object_storage
from .recognition_games import SYSTEM_BY_GAME


logger = logging.getLogger(__name__)
SCHEMA = "drop-rate-reference-inputs-v1"
MAX_CARDS = 1000
MAX_RAW_BYTES = 4_000_000
MAX_CACHE_BYTES = 16_000_000
MAX_CACHE_KEYS = 64
READ_TIMEOUT_SECONDS = 3.0
MAX_INFLIGHT_READS = 4
NON_VALUE_SORTS = {"name", "name_desc", "newest", "oldest", "number"}
CACHE_SYSTEMS = tuple(sorted(set(SYSTEM_BY_GAME.values())))
SCOPE_FIELDS = ("provider", "system_code", "language", "set_id")
SCOPE_LIMITS = (80, 80, 80, 200)

# Explicit projections also define the typed relations used by the unchanged
# catalogue SQL. No inventory, mappings, media approvals or derived values enter.
COLUMNS = {
    "r": (("provider", "text"), ("system_code", "text"), ("language", "text"),
          ("provider_id", "text"), ("set_id", "text"), ("name", "text"),
          ("card_number", "text"), ("rarity", "text"), ("image_url", "text"), ("source_url", "text")),
    "s": (("provider", "text"), ("system_code", "text"), ("language", "text"),
          ("set_id", "text"), ("name", "text"), ("release_date", "date")),
    "m": (("provider", "text"), ("system_code", "text"), ("language", "text"),
          ("provider_id", "text"), ("market_value_minor", "bigint"), ("market_value_high_minor", "bigint"),
          ("pricing_updated_at", "timestamptz"), ("quotes", "jsonb"),
          ("expires_at", "timestamptz"), ("refresh_revision", "integer")),
    "b": (("provider", "text"), ("system_code", "text"), ("language", "text"),
          ("provider_id", "text"), ("market_value_minor", "bigint"), ("market_value_high_minor", "bigint"),
          ("pricing_updated_at", "timestamptz"), ("quotes", "jsonb")),
}


def _projection(alias):
    return ",".join(alias + "." + name for name, _ in COLUMNS[alias])


# This exact projection feeds both warming and request fingerprints. jsonb::text
# stays PostgreSQL-produced; Python never reserializes quote numbers or dates.
SNAPSHOT_SQL = f"""
with picked_cards as materialized (
 select {_projection('r')} from tcg.reference_cards r
 where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.set_id=$4
 order by r.provider_id limit $5
), card_count as (
 select count(*)::int as value from picked_cards
), r as (
 select * from picked_cards where (select value from card_count)<$5
), s as (
 select {_projection('s')} from tcg.reference_sets s
 where s.provider=$1 and s.system_code=$2 and s.language=$3 and s.set_id=$4
), m as (
 select {_projection('m')} from tcg.reference_market_prices m
 join r using(provider,system_code,language,provider_id)
), b as (
 select {_projection('b')} from tcg.reference_catalogue_prices b
 join r using(provider,system_code,language,provider_id)
), source_payload as (
 select jsonb_build_object(
   'schema','{SCHEMA}',
   'scope',jsonb_build_object('provider',$1::text,'system_code',$2::text,'language',$3::text,'set_id',$4::text),
   'r',coalesce((select jsonb_agg(to_jsonb(r) order by provider_id) from r),'[]'::jsonb),
   's',coalesce((select jsonb_agg(to_jsonb(s) order by set_id) from s),'[]'::jsonb),
   'm',coalesce((select jsonb_agg(to_jsonb(m) order by provider_id) from m),'[]'::jsonb),
   'b',coalesce((select jsonb_agg(to_jsonb(b) order by provider_id) from b),'[]'::jsonb)
 )::text as payload
)
select encode(sha256(convert_to(payload,'UTF8')),'hex') as source_sha256,
       octet_length(payload)::int as raw_size_bytes,
       (select value from card_count) as card_count,
       (select count(*)::int from s) as set_count,
       case when $6::boolean then payload end as payload
from source_payload
"""

WARM_SCOPES_SQL = """
select s.provider,s.system_code,s.language,s.set_id
from tcg.reference_sets s
where (s.release_date is null or s.release_date<=current_date)
  and s.system_code=any($3::text[])
  and length(s.provider) between 1 and 80 and s.provider ~ '[^[:space:]]'
  and length(s.system_code) between 1 and 80
  and length(s.language) between 1 and 80 and s.language ~ '[^[:space:]]'
  and length(s.set_id) between 1 and 200 and s.set_id ~ '[^[:space:]]'
  and exists(select 1 from tcg.reference_cards r
    where (r.provider,r.system_code,r.language,r.set_id)=(s.provider,s.system_code,s.language,s.set_id))
  and ($1::text[] is null or (s.provider,s.system_code,s.language,s.set_id)>
       (($1::text[])[1],($1::text[])[2],($1::text[])[3],($1::text[])[4]))
order by s.provider,s.system_code,s.language,s.set_id limit $2
"""


@dataclass(frozen=True, slots=True)
class ReferenceScope:
    provider: str
    system_code: str
    language: str
    set_id: str

    def __post_init__(self):
        for value, maximum in zip(self.values(), SCOPE_LIMITS):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError("An exact bounded reference scope is required")
        if self.system_code not in CACHE_SYSTEMS:
            raise ValueError("The reference cache supports exact configured card systems only")

    def values(self):
        return self.provider, self.system_code, self.language, self.set_id

    def as_dict(self):
        return dict(zip(SCOPE_FIELDS, self.values()))


@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    scope: ReferenceScope
    payload: str
    sha256: str
    card_count: int
    origin: str = "VERIFIED"


def delivery_enabled():
    return os.getenv("TCG_R2_CATALOGUE_CACHE_DELIVERY_ENABLED", "false").strip().lower() in {"true", "1"}


def reference_scope(*, provider, system_code, language, set_id, product_type="", owned="all",
                    sort="newest", q="", keys=None, slab_number="", slab_name="", slab_set=""):
    """Only exact-set ordinary pages; sealed rows keep their separate live SQL."""
    if (product_type not in {"", "CARD"} or owned != "all" or sort not in NON_VALUE_SORTS
            or q or keys is not None or slab_number or slab_name or slab_set):
        return None
    try:
        return ReferenceScope(provider, system_code, language, set_id)
    except (ValueError, TypeError):
        return None


async def fetch_snapshot_source(connection, scope, *, include_payload=False):
    """Read current shared inputs through the caller's normal authorized snapshot."""
    result = await connection.fetchrow(SNAPSHOT_SQL, *scope.values(), MAX_CARDS + 1, include_payload)
    if result is None:
        return None
    result = dict(result)
    if (type(result.get("card_count")) is not int or not 0 < result["card_count"] <= MAX_CARDS
            or result.get("set_count") != 1 or type(result.get("raw_size_bytes")) is not int
            or not 0 < result["raw_size_bytes"] <= MAX_RAW_BYTES
            or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("source_sha256", "")))):
        return None
    return result


def parse_reference_snapshot(payload, scope, expected_sha256, expected_size, *, origin="VERIFIED"):
    if (not isinstance(payload, bytes) or type(expected_size) is not int
            or not 0 < len(payload) == expected_size <= MAX_RAW_BYTES
            or hashlib.sha256(payload).hexdigest() != expected_sha256):
        raise ObjectStorageError("Reference input cache differs from current source fingerprint")
    try:
        text = payload.decode("utf-8")
        value = json.loads(text)
        if (set(value) != {"schema", "scope", "r", "s", "m", "b"}
                or value["schema"] != SCHEMA or value["scope"] != scope.as_dict()
                or not 0 < len(value["r"]) <= MAX_CARDS or len(value["s"]) != 1):
            raise ValueError("Unexpected reference snapshot scope")
        identities = set()
        for alias, columns in COLUMNS.items():
            rows = value[alias]
            if not isinstance(rows, list) or len(rows) > MAX_CARDS:
                raise ValueError("Invalid reference relation")
            seen = set()
            for row in rows:
                if (not isinstance(row, dict) or set(row) != {name for name, _ in columns}
                        or any(row[key] != scope.as_dict()[key] for key in ("provider", "system_code", "language"))):
                    raise ValueError("Unexpected reference columns or identity")
                key = row["set_id"] if alias == "s" else row["provider_id"]
                if not isinstance(key, str) or not key or key in seen:
                    raise ValueError("Duplicate reference identity")
                seen.add(key)
                if alias in {"r", "s"} and row["set_id"] != scope.set_id:
                    raise ValueError("Conflicting reference set")
                if alias in {"m", "b"} and key not in identities:
                    raise ValueError("Price does not belong to exact reference set")
            if alias == "r":
                identities = seen
    except (UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
        raise ObjectStorageError("Invalid reference input cache schema") from exc
    return ReferenceSnapshot(scope, text, expected_sha256, len(value["r"]), origin)


def source_cte_with_snapshot(source_cte, parameter):
    """Replace only raw card inputs; every eligibility predicate stays unchanged."""
    if not re.fullmatch(r"\$[1-9][0-9]*", parameter):
        raise ValueError("A bound snapshot parameter is required")
    replacements = (
        ("from tcg.reference_cards r join tcg.reference_sets s", "from r2_cache_r r join r2_cache_s s"),
        ("left join tcg.reference_market_prices m\n", "left join r2_cache_m m\n"),
        ("left join tcg.reference_catalogue_prices b\n", "left join r2_cache_b b\n"),
    )
    updated = source_cte
    for before, after in replacements:
        if updated.count(before) != 1:
            raise ValueError("Reference query shape changed; cache substitution refused")
        updated = updated.replace(before, after, 1)
    relations = []
    for alias, columns in COLUMNS.items():
        typed = ",".join(name + " " + kind for name, kind in columns)
        relations.append(f"r2_cache_{alias} as (select * from jsonb_to_recordset({parameter}::jsonb->'{alias}') as x({typed}))")
    prefix = "\nwith reference_base as not materialized ("
    if not updated.startswith(prefix):
        raise ValueError("Reference query prefix changed; cache substitution refused")
    return updated.replace(prefix, "\nwith " + ",\n".join(relations) + ",\nreference_base as not materialized (", 1)


_verified_inputs = OrderedDict()
_verified_input_bytes = 0
_read_slots = threading.BoundedSemaphore(MAX_INFLIGHT_READS)


def clear_reference_snapshot_cache():
    global _verified_input_bytes
    _verified_inputs.clear()
    _verified_input_bytes = 0


def _remember(digest, payload):
    global _verified_input_bytes
    previous = _verified_inputs.pop(digest, None)
    if previous is not None:
        _verified_input_bytes -= len(previous)
    while _verified_inputs and (len(_verified_inputs) >= MAX_CACHE_KEYS
                               or _verified_input_bytes + len(payload) > MAX_CACHE_BYTES):
        _, removed = _verified_inputs.popitem(last=False)
        _verified_input_bytes -= len(removed)
    if len(payload) <= min(MAX_RAW_BYTES, MAX_CACHE_BYTES):
        _verified_inputs[digest] = payload
        _verified_input_bytes += len(payload)


async def _read_with_budget(storage, digest):
    """A timed-out request cannot free a slot while its read thread still runs."""
    slots = _read_slots
    if not slots.acquire(blocking=False):
        raise ObjectStorageError("Reference cache read capacity reached")

    def read_and_release():
        try:
            return storage.read_verified_reference_snapshot(digest)
        finally:
            slots.release()

    try:
        future = asyncio.get_running_loop().run_in_executor(None, read_and_release)
    except BaseException:
        slots.release()
        raise
    # Shield keeps a queued executor job alive so it eventually releases its
    # slot even after caller cancellation. Consume any late exception as well.
    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return await asyncio.wait_for(asyncio.shield(future), timeout=READ_TIMEOUT_SECONDS)


async def read_reference_snapshot(connection, scope, *, storage=None):
    """Return a verified input object or fall back; this path never uploads."""
    try:
        storage = storage if storage is not None else configured_object_storage()
        if storage is None:
            return None
        # A fingerprint timeout or SQL error must not abort the caller's live
        # fallback query. Nested transaction creates a normal read-only savepoint.
        async with connection.transaction():
            source = await fetch_snapshot_source(connection, scope)
        if source is None:
            return None
        digest = source["source_sha256"]
        payload = _verified_inputs.get(digest)
        origin = "PROCESS" if payload is not None else "R2"
        if payload is None:
            payload = await _read_with_budget(storage, digest)
        snapshot = parse_reference_snapshot(payload, scope, digest, source["raw_size_bytes"], origin=origin)
        _remember(digest, payload)
        logger.info("CATALOGUE_R2_REFERENCE_CACHE_HIT origin=%s cards=%s", origin, snapshot.card_count)
        return snapshot
    except Exception as exc:
        logger.warning("CATALOGUE_R2_REFERENCE_CACHE_FALLBACK type=%s", type(exc).__name__)
        return None


async def verify_warmed_reference_snapshot(pool, actor, snapshot, *, storage=None):
    """Compare a bounded live/cached page after an actual R2 read, without private reporting."""
    if not isinstance(actor, UUID) or not isinstance(snapshot, ReferenceSnapshot):
        raise ValueError("Parity verification requires an existing admin UUID and verified snapshot")
    # Import only after the catalogue module has initialized its existing query builder.
    from .catalogue_browser import product_query

    result = {"status": "FAILED", "compared_rows": 0, "equal": False,
              "database_elapsed_ms": None, "cache_elapsed_ms": None, "source_changed": False}
    try:
        storage = storage if storage is not None else configured_object_storage()
        if storage is None:
            raise ObjectStorageError("Private reference storage is not configured")
        async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as connection:
            access = await require_platform_admin(connection)
            source = await fetch_snapshot_source(connection, snapshot.scope)
            if source is None or source["source_sha256"] != snapshot.sha256:
                result.update(status="SOURCE_CHANGED", equal=None, source_changed=True)
                return result
            # Deliberately bypass the process cache: release proof must read R2.
            raw = await _read_with_budget(storage, snapshot.sha256)
            verified = parse_reference_snapshot(raw, snapshot.scope, source["source_sha256"],
                                                source["raw_size_bytes"], origin="R2")
            # The existing builder fetches limit+1 for has_more; limit=19 keeps
            # this comparison at a strict maximum of twenty full result rows.
            options = dict(owner_id=access["owner_id"], **snapshot.scope.as_dict(),
                           product_type="", owned="all", sort="newest", limit=19, offset=0)
            original_query, original_params = product_query(**options)
            cached_query, cached_params = product_query(**options, reference_snapshot=verified)
            started = time.perf_counter()
            original = [dict(row) for row in await connection.fetch(original_query, *original_params)]
            result["database_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            started = time.perf_counter()
            cached = [dict(row) for row in await connection.fetch(cached_query, *cached_params)]
            result["cache_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            result.update(compared_rows=len(original), equal=original == cached,
                          status="MATCH" if original == cached else "MISMATCH")
            # Both rowsets, including owned quantities, leave scope here. They
            # are never serialized into a report, log, receipt or cache object.
        return result
    except Exception as exc:
        logger.warning("CATALOGUE_R2_PARITY_FAILED type=%s", type(exc).__name__)
        return result


def _directory_cursor(value):
    """A paging boundary may name an excluded row; it is never cache approval."""
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(not isinstance(part, str) or len(part) > maximum
                   for part, maximum in zip(value, SCOPE_LIMITS))):
        raise ValueError("Reference warming cursor must contain four bounded directory values")
    return list(value)


async def warm_reference_snapshots(pool, actor, *, cursor=None, limit=4, storage=None,
                                   verify_query_parity=False):
    """Bounded authorized snapshot reads, then private verified writes without DB leases."""
    if (not isinstance(actor, UUID) or type(limit) is not int or not 1 <= limit <= 5
            or type(verify_query_parity) is not bool):
        raise ValueError("Reference warming requires an existing admin UUID and limit 1–5")
    if cursor is not None:
        cursor = _directory_cursor(cursor)
    storage = storage if storage is not None else configured_object_storage()
    if storage is None:
        raise ObjectStorageError("Private reference storage is not configured")
    selected, snapshots = [], []
    async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as connection:
        await require_platform_admin(connection)
        scopes = [dict(row) for row in await connection.fetch(WARM_SCOPES_SQL, cursor, limit + 1, list(CACHE_SYSTEMS))]
        selected = scopes[:limit]
        for row in selected:
            try:
                scope = ReferenceScope(**row)
            except (TypeError, ValueError):
                # SQL filters normal invalid scopes before pagination. Keep a
                # bounded raw cursor if text/locale drift leaves a rejected row.
                continue
            source = await fetch_snapshot_source(connection, scope, include_payload=True)
            if source is not None:
                payload = source["payload"].encode("utf-8")
                snapshot = parse_reference_snapshot(payload, scope, source["source_sha256"], source["raw_size_bytes"])
                snapshots.append((snapshot, payload))
    report = {"examined": len(selected), "verified": 0, "skipped": len(selected) - len(snapshots),
              "failed": 0, "database_writes": 0, "has_more": len(scopes) > limit,
              "next_cursor": _directory_cursor([selected[-1][field] for field in SCOPE_FIELDS])
                  if len(scopes) > limit else None, "receipts": []}
    for snapshot, payload in snapshots:
        try:
            receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, payload)
            if (not isinstance(receipt, dict) or receipt.get("verified") is not True
                    or receipt.get("sha256") != snapshot.sha256
                    or receipt.get("key") != f"{storage.config.prefix}/catalogue-reference-inputs/{snapshot.sha256}.json.gz"
                    or type(receipt.get("size_bytes")) is not int or not 0 < receipt["size_bytes"] <= 2_000_000
                    or not re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("compressed_sha256", "")))):
                raise ObjectStorageError("Reference snapshot receipt differs from source")
            entry = {"scope": snapshot.scope.as_dict(), "cards": snapshot.card_count,
                     "object": {key: receipt[key] for key in
                                ("key", "sha256", "size_bytes", "compressed_sha256", "verified")}}
            _remember(snapshot.sha256, payload)
            report["verified"] += 1
            report["receipts"].append(entry)
            if verify_query_parity and "query_parity" not in report:
                report["query_parity"] = await verify_warmed_reference_snapshot(
                    pool, actor, snapshot, storage=storage)
        except Exception as exc:
            report["failed"] += 1
            logger.warning("CATALOGUE_R2_REFERENCE_CACHE_BUILD_FAILED type=%s", type(exc).__name__)
    return report
