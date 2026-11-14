"""Bounded, idempotent Cardmarket regional-context persistence.

Keeps existing source observations append-only and never touches actual UK
SOLD prices, physical inventory, Store Prices, ownership or Shopify.

Requires RLS-authorized platform maintenance account. Caller explicitly opts in.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from .access_control import require_platform_admin
from .cardmarket_bulk_context import MAX_BYTES_PER_REFERENCE, SOURCE
from .cardmarket_public_pilot import PilotError
from .db import user_connection

_BATCH = 25


def merge_source_quotes(existing: object, fresh: list[dict]) -> str:
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except (TypeError, ValueError) as exc:
            raise PilotError("Existing regional cache JSON corrupt") from exc
    if not isinstance(existing, list) or not isinstance(fresh, list) or not fresh:
        raise PilotError("Invalid regional quote merge")
    if any(not isinstance(q, dict) for q in existing + fresh):
        raise PilotError("Invalid regional quote type")
    # Preserve independent price sources; replace this exact source only.
    old = [q for q in existing if q.get("source") != SOURCE]
    combined = old + fresh
    text = json.dumps(combined, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_BYTES_PER_REFERENCE:
        raise PilotError("Combined regional quote payload too large")
    return text


async def persist_cardmarket_context(pool, actor, prepared: list[dict], *,
                                     request_id: str, max_references: int = 100,
                                     start_index: int = 0) -> dict:
    if not 1 <= max_references <= 500 or start_index < 0:
        raise PilotError("Apply batch boundaries invalid")
    selected = prepared[start_index:start_index + max_references]
    inserted = unchanged = blocked = 0
    for first in range(0, len(selected), _BATCH):
        async with user_connection(pool, actor, request_id) as conn:
            await require_platform_admin(conn)
            if await conn.fetchval("show transaction_read_only") != "off":
                raise PilotError("Maintenance transaction cannot persist verified evidence")
            for candidate in selected[first:first + _BATCH]:
                now = datetime.now(timezone.utc)
                key, identity = candidate["reference_key"], candidate["identity_sha256"]
                if candidate["expires_at"] <= now:
                    blocked += 1
                    continue
                current = await conn.fetchrow(
                    'select identity_sha256,quotes,lease_token from '
                    'tcg.reference_regional_price_context where reference_key=$1 for update',
                    key)
                if current and (current["identity_sha256"] != identity or
                                current["lease_token"] is not None):
                    blocked += 1
                    continue
                old_quotes = current["quotes"] if current else []
                try:
                    merged = merge_source_quotes(old_quotes, candidate["quotes"])
                except PilotError:
                    blocked += 1
                    continue
                old = json.loads(old_quotes) if isinstance(old_quotes, str) else old_quotes
                # A previously ingested newer public snapshot cannot be demoted.
                prior = [q for q in old if isinstance(q, dict) and q.get("source") == SOURCE]
                if prior and max(q.get("observed_at", "") for q in prior) > candidate["guide_at"].isoformat():
                    blocked += 1
                    continue
                if prior and sorted(prior, key=lambda q: (q.get("product_id",""),q.get("variant_id",""))) == sorted(
                        candidate["quotes"], key=lambda q: (q.get("product_id",""),q.get("variant_id",""))):
                    unchanged += 1
                    continue
                digest = hashlib.sha256(merged.encode("utf-8")).hexdigest()
                # Insert history and current context in the same transaction.
                # History has INSERT/SELECT RLS only and no UPDATE or DELETE route.
                await conn.execute(
                    'insert into tcg.reference_regional_price_history '
                    '(reference_key,identity_sha256,quotes_sha256,quotes) '
                    'values($1,$2,$3,$4::jsonb) on conflict do nothing',
                    key, identity, digest, merged)
                await conn.execute(
                    'insert into tcg.reference_regional_price_context '
                    '(reference_key,identity_sha256,quotes,checked_at,expires_at) '
                    'values($1,$2,$3::jsonb,$4,$5) on conflict(reference_key) do update set '
                    'quotes=excluded.quotes, checked_at=excluded.checked_at,'
                    'expires_at=excluded.expires_at '
                    'where tcg.reference_regional_price_context.identity_sha256=excluded.identity_sha256 '
                    'and tcg.reference_regional_price_context.lease_token is null',
                    key, identity, merged, now, candidate["expires_at"])
                inserted += 1
    return {
        "status": "BOUNDED_CARDMARKET_REGIONAL_CONTEXT_APPLIED",
        "start_index": start_index, "requested_max_references": max_references,
        "applied": inserted, "unchanged": unchanged, "blocked": blocked,
        "physical_market_value_writes": 0,
        "store_price_writes": 0, "shopify_writes": 0
    }
