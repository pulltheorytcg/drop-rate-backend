"""Resumable, capped rollout of independently verified Cardmarket regional guides.

One provider snapshot, exact source IDs, batches of up to 500 canonical refs,
existing RLS context+append-only history only. Rollout starts after the verified
100-reference pilot and fails immediately on blocked/missing rows. No Shopify,
physical inventory, Store Price, settlement or UK sold-price changes.
"""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import json

from .cardmarket_bulk_persistence import persist_cardmarket_context
from .cardmarket_public_pilot import PilotError

MAX_FULL_REFERENCE_COUNT = 10_000
MIN_VERIFIED_PILOT = 100
MAX_BATCH_SIZE = 500

def approved_full_source_digest(candidates: list[dict]) -> str:
    """Match the protected full-source audit, including variant ID and repeats.

    A digest of a different tuple or a deduplicated set is not the approved
    source receipt and must never authorize mass reference writes.
    """
    records = [
        (c["language"], c["provider_id"], c["cardmarket_id"],
         c.get("variant_id"), c["source_field"])
        for c in candidates
    ]
    return hashlib.sha256(
        json.dumps(sorted(records), separators=(",", ":")).encode()
    ).hexdigest()



async def apply_verified_remaining(
    pool, actor, prepared: list[dict], *, start_index: int,
    batch_size: int, request_id: str,
    log_progress: Callable[[dict], None] | None = None,
) -> dict:
    if (not isinstance(prepared, list)
            or not MIN_VERIFIED_PILOT <= start_index < len(prepared) <= MAX_FULL_REFERENCE_COUNT
            or type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE):
        raise PilotError("Unsafe full-batch limits or missing completed pilot")
    if any(not isinstance(row, dict) or not row.get("reference_key") for row in prepared):
        raise PilotError("Malformed prepared canonical reference batch")
    if len({r["reference_key"] for r in prepared}) != len(prepared):
        raise PilotError("Duplicate canonical reference key in import plan")

    inserted = unchanged = 0
    batches = 0
    for index in range(start_index, len(prepared), batch_size):
        count = min(batch_size, len(prepared) - index)
        receipt = await persist_cardmarket_context(
            pool, actor, prepared,
            request_id=request_id,
            max_references=count, start_index=index,
        )
        if (receipt["blocked"] != 0 or
                receipt["applied"] + receipt["unchanged"] != count or
                receipt["physical_market_value_writes"] != 0 or
                receipt["store_price_writes"] != 0 or
                receipt["shopify_writes"] != 0):
            raise PilotError("Bounded Cardmarket import batch did not fully reconcile")
        inserted += receipt["applied"]
        unchanged += receipt["unchanged"]
        batches += 1
        if log_progress is not None:
            log_progress({
                "status": "VERIFIED_BATCH_COMMITTED",
                "start_index": index, "batch_count": count,
                "applied": receipt["applied"], "unchanged": receipt["unchanged"],
                "blocked": receipt["blocked"],
                "uk_physical_market_values": 0, "store_price_writes": 0,
                "shopify_writes": 0,
            })
    return {
        "status": "BOUNDED_CARDMARKET_REGIONAL_ROLLOUT_COMPLETE",
        "start_index": start_index,
        "total_reference_count": len(prepared),
        "planned": len(prepared) - start_index,
        "applied": inserted,
        "unchanged": unchanged,
        "blocked": 0, "batches": batches,
        "physical_market_value_writes": 0,
        "store_price_writes": 0,
        "shopify_writes": 0,
    }
