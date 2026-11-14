"""One-time, source-hash-locked, resumable Cardmarket Pokémon backfill.

This is an operator-controlled completion of the already verified exact-match
source material, NOT a new pricing engine or scheduled price import.
Existing RLS/ownership, per-reference validations and immutable quote history
are enforced by the original `persist_cardmarket_context` function.
"""
from __future__ import annotations

import hashlib
import json
import os

from .cardmarket_public_pilot import PilotError
from .cardmarket_bulk_persistence import persist_cardmarket_context

APPROVED_PRODUCT_SHA = "53fa34f03f2a1d9d73fcccbfcd826d71386b1336c70557fae64542aa8678b190"
APPROVED_GUIDE_SHA = "122d8fbb72cc37092e609fa8d51f4d21cfc93ae83fab90cb936d0e1138f388fd"
APPROVED_CROSSWALK_SHA = "41b23c98d7e2a60947650c4b1f2730d5ab23b7b68b10af29127c57dd92484da3"
APPROVED_REFERENCE_COUNT = 8907
APPROVED_VARIANT_QUOTE_COUNT = 13703
APPROVED_MATCH_COUNT = 14506
APPROVED_START = 600
APPROVED_END = 8907
APPROVED_CHUNK = 500
APPROVED_SCHEMA = "drop-rate-cardmarket-pokemon-20261114-reviewed-batch-v1"


def exact_source_digest(candidates: list[dict]) -> str:
    # Identical canonical receipt algorithm to the successful protected
    # GitHub read-only full-reference job #43607783746.
    records = [
        (c["language"], c["provider_id"], c["cardmarket_id"],
         c["variant_id"], c["source_field"])
        for c in candidates
    ]
    return hashlib.sha256(
        json.dumps(sorted(records), separators=(",", ":")).encode()
    ).hexdigest()


def check_approved_source(*, candidates: list[dict], prepared: dict,
                          product_sha256: str, guide_sha256: str,
                          start_index: int, end_index: int) -> None:
    if os.getenv("DROP_RATE_CARDMARKET_FULL_APPLY_CONFIRMED") != "YES":
        raise PilotError("Full batch operator gate not enabled")
    if os.getenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED") != "YES":
        raise PilotError("Bounded import operator gate not enabled")
    if (start_index != APPROVED_START or end_index != APPROVED_END
            or product_sha256 != APPROVED_PRODUCT_SHA
            or guide_sha256 != APPROVED_GUIDE_SHA
            or len(candidates) != APPROVED_MATCH_COUNT
            or exact_source_digest(candidates) != APPROVED_CROSSWALK_SHA
            or prepared.get("regional_reference_count") != APPROVED_REFERENCE_COUNT
            or prepared.get("regional_variant_quote_count") != APPROVED_VARIANT_QUOTE_COUNT
            or len(prepared.get("prepared", [])) != APPROVED_REFERENCE_COUNT):
        raise PilotError("Official source or exact crosswalk changed; require a new audit")
    if not all(p.get("reference_key") and p.get("quotes") for p in prepared["prepared"]):
        raise PilotError("Prepared source references are incomplete")


async def apply_approved_remainder(pool, actor, *, candidates: list[dict],
                                   prepared: dict, product_sha256: str,
                                   guide_sha256: str, start_index: int,
                                   end_index: int, progress=None) -> dict:
    """Only complete reviewed indexes 600..8906, in <=500-reference commits.

    A repeat is safe: each source record is compared and append-only history
    is keyed by immutable SHA. Any blocked record aborts further batches.
    """
    check_approved_source(
        candidates=candidates, prepared=prepared, product_sha256=product_sha256,
        guide_sha256=guide_sha256, start_index=start_index, end_index=end_index)
    applied = unchanged = 0
    chunks = 0
    for cursor in range(start_index, end_index, APPROVED_CHUNK):
        count = min(APPROVED_CHUNK, end_index - cursor)
        receipt = await persist_cardmarket_context(
            pool, actor, prepared["prepared"], request_id="cardmarket-approved-20261114-remainder",
            max_references=count, start_index=cursor)
        if (receipt["blocked"] != 0 or
                receipt["applied"] + receipt["unchanged"] != count):
            raise PilotError("Partial batch blocked; stop and inspect verified cache")
        applied += receipt["applied"]
        unchanged += receipt["unchanged"]
        chunks += 1
        if progress is not None:
            progress({
                "schema": APPROVED_SCHEMA, "chunk": chunks,
                "processed": applied + unchanged,
                "applied": applied, "unchanged": unchanged,
                "next_index": cursor + count,
                "source_locked": True,
                "blocked": 0, "shopify_writes": 0,
            })
    return {
        "schema": APPROVED_SCHEMA, "status": "APPROVED_REMAINDER_APPLIED",
        "chunks": chunks, "references_processed": applied + unchanged,
        "applied": applied, "unchanged": unchanged, "blocked": 0,
        "range_start": start_index, "range_end": end_index,
        "physical_market_value_writes": 0, "store_price_writes": 0,
        "shopify_writes": 0, "source_locked": True,
    }
