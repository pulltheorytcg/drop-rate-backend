"""Prepare source-labelled Cardmarket EU seven-day aggregates for the existing
regional catalogue context/history. Never produce physical UK Market Values.

This is a deterministic conversion boundary, not a second pricing engine.
Data is admitted only after the existing exact source-ID crosswalk has passed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from .cardmarket_public_pilot import PilotError
from .fx import FxQuote, ECB_SOURCE
from .regional_catalogue_prices import _identity_hash

SOURCE = "CARDMARKET_PUBLIC_BULK"
SCHEMA = "drop-rate-cardmarket-context-prepared-v1"
MAX_CANDIDATES = 120_000
MAX_BYTES_PER_REFERENCE = 65_536


def _key(row: dict) -> str:
    fields = (row["provider"], row["system_code"], row["language"], row["provider_id"])
    return "r:" + hashlib.md5(chr(31).join(fields).encode("utf-8")).hexdigest()


def prepare_cardmarket_context(*, candidates: list[dict], fx: FxQuote,
                               guide_at: datetime, now: datetime,
                               product_sha256: str, guide_sha256: str) -> dict[str, Any]:
    if (not isinstance(now, datetime) or now.utcoffset() is None
            or not isinstance(guide_at, datetime) or guide_at.utcoffset() is None):
        raise PilotError("Timezone-aware UTC snapshots are required")
    now, guide_at = now.astimezone(timezone.utc), guide_at.astimezone(timezone.utc)
    if not now - timedelta(days=3) <= guide_at <= now:
        raise PilotError("Cardmarket guide snapshot is stale or future")
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise PilotError("Too many source candidates")
    for digest in (product_sha256, guide_sha256):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise PilotError("Verified original file SHA256 receipts required")
    if (fx.base_currency != "EUR" or fx.quote_currency != "GBP"
            or fx.source != ECB_SOURCE or not fx.rate.is_finite()
            or fx.rate <= 0 or fx.rate >= 10
            or fx.effective_at.utcoffset() is None or fx.retrieved_at.utcoffset() is None
            or fx.effective_at > guide_at or fx.retrieved_at > now
            or guide_at - fx.effective_at > timedelta(days=7)):
        raise PilotError("Valid earlier ECB EUR/GBP rate required")

    per_ref: dict[str, list[dict]] = defaultdict(list)
    identities: dict[str, str] = {}
    rejected = defaultdict(int)
    seen = set()
    for row in candidates:
        if not isinstance(row, dict):
            rejected["INVALID_SOURCE_CANDIDATE"] += 1
            continue
        if (row.get("provider") != "TCGdex" or row.get("system_code") != "POKEMON_TCG"
                or row.get("language") not in ("English", "Japanese")
                or not all(isinstance(row.get(k), str) and row[k].strip()
                           for k in ("set_id", "name", "set_name", "card_number",
                                     "provider_id", "variant_id", "finish"))
                or row.get("source_link") not in ("TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT")
                or row.get("is_exact_variant") is not True
                or row.get("publishable") is not False
                or row.get("physical_valuation_eligible") is not False
                or row.get("source_field") not in ("avg7", "avg7-holo")
                or type(row.get("cardmarket_id")) is not int
                or row["cardmarket_id"] <= 0
                or type(row.get("daily_guide_eur_minor")) is not int
                or row["daily_guide_eur_minor"] <= 0
                or row.get("guide_observed_at") != guide_at.isoformat()):
            rejected["SOURCE_IDENTITY_OR_VARIANT_NOT_VERIFIED"] += 1
            continue
        try:
            gbp = int((Decimal(row["daily_guide_eur_minor"]) * fx.rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            ))
        except ArithmeticError as exc:
            raise PilotError("Failed to normalise EUR with ECB") from exc
        if gbp <= 0:
            rejected["SUB_PENNY_GBP"] += 1
            continue
        reference_key = _key(row)
        identity = _identity_hash({
            "key": reference_key, "set_id": row["set_id"],
            "set_name": row["set_name"], "name": row["name"],
            "card_number": row["card_number"], "language": row["language"]
        })
        if reference_key in identities and identities[reference_key] != identity:
            raise PilotError("Canonical key reused for different printing")
        identities[reference_key] = identity
        slot = (reference_key, row["variant_id"], row["source_field"])
        if slot in seen:
            rejected["DUPLICATE_FINISH_SLOT"] += 1
            continue
        seen.add(slot)
        quote = {
            "source": SOURCE, "source_record_id": str(row["cardmarket_id"]),
            "product_id": str(row["cardmarket_id"]),
            "variant_id": row["variant_id"],
            "finish": row["finish"], "variant_label": row["finish"],
            "source_field": row["source_field"],
            "original_currency": "EUR",
            "original_minor": row["daily_guide_eur_minor"],
            "observed_at": guide_at.isoformat(),
            "reference_language": row["language"],
            "match_basis": row["match_basis"],
            "market_scope": "EU_AGGREGATED_7_DAY_SALES",
            "condition_basis": "MIXED",
            "language_basis": "UNSPECIFIED",
            "grade_basis": "NOT_GRADE_SPECIFIC",
            "valuation_role": "REGIONAL_CATALOGUE_CONTEXT_ONLY",
            "physical_valuation_eligible": False,
            "source_product_sha256": product_sha256,
            "source_guide_sha256": guide_sha256,
            "regional_sale": {
                "region": "EU", "source_field": row["source_field"],
                "original_minor": row["daily_guide_eur_minor"],
                "price_gbp_minor": gbp,
                "fx_rate_to_gbp": str(fx.rate), "fx_source": fx.source,
                "fx_effective_at": fx.effective_at.isoformat(),
                "physical_valuation_eligible": False
            }
        }
        per_ref[reference_key].append(quote)

    prepared = []
    expiry = guide_at + timedelta(days=3)
    for key, quotes in sorted(per_ref.items()):
        quotes.sort(key=lambda x: (x["source_record_id"], x["variant_id"], x["source_field"]))
        raw = json.dumps(quotes, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_BYTES_PER_REFERENCE:
            rejected["QUOTE_PAYLOAD_TOO_LARGE"] += 1
            continue
        prepared.append({
            "reference_key": key, "identity_sha256": identities[key],
            "quotes": quotes, "quotes_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "guide_at": guide_at, "expires_at": expiry
        })
    return {
        "schema": SCHEMA, "status": "PREPARED_NOT_PUBLISHED",
        "source": SOURCE, "candidate_count": len(candidates),
        "regional_reference_count": len(prepared),
        "regional_variant_quote_count": sum(len(p["quotes"]) for p in prepared),
        "rejections": dict(sorted(rejected.items())),
        "guide_observed_at": guide_at.isoformat(),
        "expires_at": expiry.isoformat(),
        "physical_market_values": 0, "shopify_store_prices": 0,
        "prepared": prepared
    }
