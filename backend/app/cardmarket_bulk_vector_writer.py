"""Transactional vector writer for *the same* verified Cardmarket regional cache.

Performance-only transport for existing deterministic, source-qualified
Cardmarket pricing. Locks 25 existing reference rows at a time and pipelines
two bounded inserts through asyncpg executemany, instead of three roundtrips
per reference. Exact final readback is REQUIRED inside the same RLS transaction.
A mismatch aborts the transaction; history remains INSERT-only and auditable.

No physical inventory, market_observations, shared Market Value, Shopify,
Store Price, owners, settlements or catalogue source cache writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from .access_control import require_platform_admin
from .cardmarket_bulk_context import SOURCE
from .cardmarket_bulk_persistence import merge_source_quotes
from .cardmarket_public_pilot import PilotError
from .db import user_connection

_CHUNK = 25
_MAX_APPLY = 500

_LOCK = """
select reference_key,identity_sha256,quotes,lease_token
from tcg.reference_regional_price_context
where reference_key=any($1::text[]) for update
"""
_HISTORY_SQL = """
insert into tcg.reference_regional_price_history
(reference_key,identity_sha256,quotes_sha256,quotes)
values($1,$2,$3,$4::jsonb) on conflict do nothing
"""
_CONTEXT_SQL = """
insert into tcg.reference_regional_price_context
(reference_key,identity_sha256,quotes,checked_at,expires_at)
values($1,$2,$3::jsonb,$4,$5)
on conflict(reference_key) do update set
quotes=excluded.quotes,checked_at=excluded.checked_at,
expires_at=excluded.expires_at
where tcg.reference_regional_price_context.identity_sha256=excluded.identity_sha256
and tcg.reference_regional_price_context.lease_token is null
"""
_CHECK_SQL = """
select reference_key,identity_sha256,quotes,expires_at
from tcg.reference_regional_price_context
where reference_key=any($1::text[])
"""


def _decode(value: object) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise PilotError("Malformed source context JSON") from exc
    if not isinstance(value, list) or any(not isinstance(q, dict) for q in value):
        raise PilotError("Malformed source context quotes")
    return value


def _prepare(current, candidate: dict, now: datetime) -> tuple[str, tuple | None]:
    key, identity = candidate["reference_key"], candidate["identity_sha256"]
    if candidate["expires_at"] <= now:
        raise PilotError("Expired source candidate")
    if current and (current["identity_sha256"] != identity
                    or current["lease_token"] is not None):
        raise PilotError("Source identity or active lease conflict")
    prior_quotes = _decode(current["quotes"]) if current else []
    prior_bulk = [q for q in prior_quotes if q.get("source") == SOURCE]
    if prior_bulk and max(q.get("observed_at", "") for q in prior_bulk) > candidate["guide_at"].isoformat():
        raise PilotError("Refusing older Cardmarket source snapshot")
    if prior_bulk and sorted(
        prior_bulk, key=lambda q: (q.get("product_id", ""), q.get("variant_id", ""))
    ) == sorted(
        candidate["quotes"], key=lambda q: (q.get("product_id", ""), q.get("variant_id", ""))
    ):
        return key, None
    merged = merge_source_quotes(prior_quotes, candidate["quotes"])
    digest = hashlib.sha256(merged.encode("utf-8")).hexdigest()
    return key, (key, identity, digest, merged, now, candidate["expires_at"])


async def persist_cardmarket_context_vector(
    pool, actor, prepared: list[dict], *, request_id: str,
    max_references: int, start_index: int
) -> dict:
    if (type(max_references) is not int or not 1 <= max_references <= _MAX_APPLY
            or type(start_index) is not int or start_index < 100
            or not isinstance(prepared, list)
            or start_index >= len(prepared)):
        raise PilotError("Invalid source-qualified vector import bounds")
    selected = prepared[start_index:start_index + max_references]
    keys = [r.get("reference_key") for r in selected if isinstance(r, dict)]
    if len(keys) != len(selected) or any(not isinstance(k, str) or not k.startswith("r:") for k in keys):
        raise PilotError("Invalid canonical reference keys")
    if len(keys) != len(set(keys)):
        raise PilotError("Duplicate exact reference key in import batch")

    applied = unchanged = 0
    for start in range(0, len(selected), _CHUNK):
        chunk = selected[start:start + _CHUNK]
        chunk_keys = [r["reference_key"] for r in chunk]
        async with user_connection(pool, actor, request_id) as conn:
            await require_platform_admin(conn)
            if await conn.fetchval("show transaction_read_only") != "off":
                raise PilotError("Regional write transaction unexpectedly read only")
            existing = await conn.fetch(_LOCK, chunk_keys)
            if len(existing) != len({r["reference_key"] for r in existing}):
                raise PilotError("Duplicate existing reference cache keys")
            by_key = {r["reference_key"]:r for r in existing}
            now = datetime.now(timezone.utc)
            planned = []
            pending = []
            for row in chunk:
                key, write = _prepare(by_key.get(row["reference_key"]), row, now)
                planned.append((key, row["identity_sha256"]))
                if write is None:
                    unchanged += 1
                else:
                    pending.append(write)
            if pending:
                await conn.executemany(
                    _HISTORY_SQL,
                    [(r[0],r[1],r[2],r[3]) for r in pending],
                )
                await conn.executemany(
                    _CONTEXT_SQL,
                    [(r[0],r[1],r[3],r[4],r[5]) for r in pending],
                )
                # A missing or changed UPDATE under RLS must not be counted as
                # success. Fail the *whole transaction* including new history.
                check = await conn.fetch(_CHECK_SQL, [r[0] for r in pending])
                if len(check) != len(pending):
                    raise PilotError("Incomplete committed-source readback")
                by_result = {r["reference_key"]:r for r in check}
                for key, identity, digest, merged, checked, expiry in pending:
                    got = by_result.get(key)
                    if (got is None or got["identity_sha256"] != identity
                            or _decode(got["quotes"]) != json.loads(merged)
                            or got["expires_at"] != expiry):
                        raise PilotError("Cardmarket source readback mismatch")
                applied += len(pending)
    return {
        "status": "BOUNDED_CARDMARKET_REGIONAL_CONTEXT_APPLIED",
        "start_index": start_index,
        "requested_max_references": max_references,
        "applied": applied, "unchanged": unchanged, "blocked": 0,
        "physical_market_value_writes": 0,
        "store_price_writes": 0, "shopify_writes": 0,
    }
