"""Provisional item-only UK/EU reference estimates from two explicit sources.

The caller must select and validate the exact Cardmarket printing/finish and FX
quote before building ``cardmarket_guide``. This module rechecks its reference
binding, money basis and dates; it does not discover or guess product mappings.
The Browse input is the full report from reference_asking_estimator, including
its matched comparables. Stored delivered-price summaries alone are inadequate.

The blend is a documented initial policy, not a calibrated accuracy claim.
It never changes physical stock, owner prices, sold observations or history.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import exp, log
import re
from statistics import median


METHOD = "DROP_RATE_UK_EU_MARKET_V1"
RULESET = "2026-11-04-browse-cardmarket-1"
REFERENCE_KEYS = ("provider", "system_code", "language", "provider_id")
IDENTITY_FIELDS = ("name", "set_id", "card_number", "set_name", "finish", "rarity")
MAX_PRICE_MINOR = 1_000_000_000_000
BROWSE_TTL = timedelta(days=3)
GUIDE_TTL = timedelta(days=7)
FINISHES = {
    "normal": "Normal", "holo": "Holo", "holofoil": "Holo",
    "reverse holo": "Reverse Holo", "reverse holofoil": "Reverse Holo",
    "foil": "Foil", "parallel": "Parallel", "alt art": "Alt Art", "manga": "Manga",
}


def _at(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _amount(value, *, zero=False):
    return type(value) is int and (0 if zero else 1) <= value <= MAX_PRICE_MINOR


def _finish(value):
    return FINISHES.get(value.strip().casefold()) if isinstance(value, str) else None


def _round(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _quantile(values, fraction):
    position = Decimal(len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return _round(Decimal(values[lower]) + (values[upper] - values[lower]) * (position - lower))


def _browse_comparables(report, reference, observed_at, selected_finish, current):
    """Recheck stored facts; one seller and one provider item contribute once."""
    rows = report.get("comparables")
    if not isinstance(rows, list) or len(rows) > 1000:
        return [], 0
    by_id = {}
    conflicts = set()
    rejected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        item_id = row.get("item_id")
        # The source estimator emits legacy item IDs. Normalize a retained
        # Browse REST ID too, so variants cannot inflate independent evidence.
        rest_id = re.fullmatch(r"v1\|([1-9][0-9]{0,19})\|[0-9]+", item_id) if isinstance(item_id, str) else None
        if rest_id:
            item_id = rest_id[1]
        seller = row.get("seller_hash")
        price, shipping = row.get("price_gbp_minor"), row.get("shipping_gbp_minor")
        proof = row.get("match_proof")
        listing_evidence = row.get("listing_evidence")
        listing_evidence = listing_evidence if isinstance(listing_evidence, Mapping) else {}
        raw_end = listing_evidence.get("item_end_date")
        end_at = _at(raw_end)
        if (not isinstance(item_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", item_id)
                or not isinstance(seller, str) or not re.fullmatch(r"[0-9a-f]{64}", seller)
                or not _amount(price) or not _amount(shipping, zero=True)
                or not _amount(row.get("delivered_gbp_minor"))
                or row.get("delivered_gbp_minor") != price + shipping
                or (row.get("listing_evidence") is not None and not isinstance(row["listing_evidence"], Mapping))
                or (raw_end is not None and (end_at is None or end_at <= current))
                or _at(row.get("observed_at")) != observed_at
                or row.get("condition") != "Near Mint"
                or _finish(row.get("finish")) != selected_finish
                or not isinstance(proof, Mapping)
                or proof.get("game") != reference["system_code"]
                or proof.get("language") != reference["language"].strip().casefold()
                or proof.get("card_number") != reference["card_number"]):
            rejected += 1
            continue
        signature = (seller, price, shipping, selected_finish)
        if item_id in conflicts:
            rejected += 1
        elif item_id in by_id:
            if by_id[item_id][0] != signature:
                conflicts.add(item_id)
                by_id.pop(item_id)
                rejected += 2
            else:
                rejected += 1
        else:
            by_id[item_id] = (signature, dict(row, item_id=item_id))
    by_seller = {}
    for item_id, (signature, row) in by_id.items():
        seller = signature[0]
        if seller not in by_seller or (row["price_gbp_minor"], item_id) < (
                by_seller[seller]["price_gbp_minor"], by_seller[seller]["item_id"]):
            if seller in by_seller:
                rejected += 1
            by_seller[seller] = row
        else:
            rejected += 1
    selected = sorted(by_seller.values(), key=lambda row: (row["price_gbp_minor"], row["item_id"]))
    if len(selected) >= 3:
        centre = Decimal(str(median(row["price_gbp_minor"] for row in selected)))
        mad = Decimal(str(median(abs(Decimal(row["price_gbp_minor"]) - centre) for row in selected)))
        threshold = max(centre * Decimal("0.20"), mad * 3)
        retained = [row for row in selected if abs(Decimal(row["price_gbp_minor"]) - centre) <= threshold]
        rejected += len(selected) - len(retained)
        selected = retained
    return selected, rejected


def estimate_uk_eu_market(reference, browse_report, cardmarket_guide, *, now):
    """Combine exact UK asking evidence and a matched EU guide in GBP pennies.

    ``cardmarket_guide`` contract (constructed after source/FX validation):
      source=CARDMARKET, currency=GBP, shipping_basis=ITEM_ONLY,
      source_product_id, source_field, price_gbp_minor, observed_at,
      reference_key={provider,system_code,language,provider_id},
      reference_identity={name,set_id,card_number,set_name,finish,rarity},
      finish, condition_specific=False, language_specific=False, provenance={}.

    Unknown condition/language in the EU guide remain explicit. Agreement with
    exact UK listings does not turn that guide into a condition-specific sale.
    Each source starts with equal influence; freshness decays by the existing
    three-day ACTIVE and seven-day PRICE_GUIDE half-lives. Source disagreement
    exceeding 50% is rejected rather than hidden by a midpoint.
    """
    result = {
        "status": "INVALID_INPUT", "source": METHOD, "method_version": METHOD,
        "ruleset_revision": RULESET, "currency": "GBP", "shipping_basis": "ITEM_ONLY",
        "observation_type": "DERIVED_NOT_SOLD", "valuation_kind": "REFERENCE_ESTIMATE",
        "estimate_minor": None, "estimate_low_minor": None, "estimate_high_minor": None,
        "market_value_minor": None, "confidence": 0.0,
        "source_count": 0, "observation_count": 0, "sold_observation_count": 0,
        "physical_valuation_eligible": False, "auto_publish_eligible": False,
        "recommended_retail_minor": None, "observed_at": None, "expires_at": None,
        "computed_at": None,
        "condition_specific": False, "language_specific": False,
        "limitation": "Provisional blend of UK asking prices and a Cardmarket guide across conditions and languages; not a completed-sale or exact-copy valuation.",
        "evidence": {},
    }
    current = _at(now)
    if current is not None:
        result["computed_at"] = current.isoformat()
    if (current is None or not all(isinstance(value, Mapping) for value in (reference, browse_report, cardmarket_guide))
            or any(not isinstance(reference.get(key), str) or not reference[key].strip()
                   for key in (*REFERENCE_KEYS, "name", "set_id", "card_number", "set_name"))):
        return result
    identity = {key: reference.get(key) for key in IDENTITY_FIELDS}
    reference_key = {key: reference[key] for key in REFERENCE_KEYS}
    if browse_report.get("identity") != identity or cardmarket_guide.get("reference_identity") != identity or cardmarket_guide.get("reference_key") != reference_key:
        result["status"] = "REFERENCE_IDENTITY_MISMATCH"
        return result
    selected_finish = _finish(browse_report.get("selected_finish"))
    if (selected_finish is None or selected_finish != _finish(cardmarket_guide.get("finish"))
            or (reference.get("finish") and _finish(reference["finish"]) != selected_finish)):
        result["status"] = "FINISH_MISMATCH"
        return result
    if (browse_report.get("status") != "READY" or browse_report.get("source") != "EBAY_OFFICIAL_BROWSE"
            or browse_report.get("method_version") != "EBAY_UK_RAW_ASK_V1"
            or browse_report.get("basis") != "ASKING_PRICE_ESTIMATE"
            or browse_report.get("currency") != "GBP"
            or browse_report.get("condition_basis") != "RAW_NEAR_MINT_OR_MINT"):
        result["status"] = "INVALID_BROWSE_REPORT"
        return result
    browse_at, browse_expiry = _at(browse_report.get("observed_at")), _at(browse_report.get("expires_at"))
    guide_at = _at(cardmarket_guide.get("observed_at"))
    if (browse_at is None or browse_expiry is None or guide_at is None
            or not browse_at <= current < browse_expiry <= browse_at + BROWSE_TTL
            or not current - GUIDE_TTL < guide_at <= current):
        result["status"] = "STALE_OR_INVALID_EVIDENCE_TIME"
        return result
    if (cardmarket_guide.get("source") != "CARDMARKET" or cardmarket_guide.get("currency") != "GBP"
            or cardmarket_guide.get("shipping_basis") != "ITEM_ONLY"
            or not _amount(cardmarket_guide.get("price_gbp_minor"))
            or cardmarket_guide.get("condition_specific") is not False
            or cardmarket_guide.get("language_specific") is not False
            or not isinstance(cardmarket_guide.get("provenance"), Mapping)
            or any(not isinstance(cardmarket_guide.get(key), str) or not cardmarket_guide[key].strip()
                   for key in ("source_product_id", "source_field"))):
        result["status"] = "INVALID_CARDMARKET_GUIDE"
        return result
    comparables, rejected = _browse_comparables(browse_report, reference, browse_at, selected_finish, current)
    if len(comparables) < 3:
        result.update(status="INSUFFICIENT_INDEPENDENT_LISTINGS", evidence={"excluded_browse_count": rejected})
        return result
    prices = [row["price_gbp_minor"] for row in comparables]
    ebay_value = _round(median(prices))
    if Decimal(max(prices) - min(prices)) > Decimal(ebay_value) * Decimal("0.50"):
        result["status"] = "EXCESSIVE_ITEM_PRICE_DISPERSION"
        return result
    guide_value = cardmarket_guide["price_gbp_minor"]
    if Decimal(max(ebay_value, guide_value)) > Decimal(min(ebay_value, guide_value)) * Decimal("1.50"):
        result.update(status="SOURCE_DISAGREEMENT", evidence={"ebay_item_median_minor": ebay_value, "cardmarket_guide_minor": guide_value})
        return result
    ebay_freshness = exp(-log(2.0) * (current - browse_at).total_seconds() / BROWSE_TTL.total_seconds())
    guide_freshness = exp(-log(2.0) * (current - guide_at).total_seconds() / GUIDE_TTL.total_seconds())
    ebay_weight = Decimal(str(ebay_freshness))
    guide_weight = Decimal(str(guide_freshness))
    value = _round((ebay_value * ebay_weight + guide_value * guide_weight) / (ebay_weight + guide_weight))
    low = min(guide_value, _quantile(prices, Decimal("0.25")), value)
    high = max(guide_value, _quantile(prices, Decimal("0.75")), value)
    confidence = round(min(.60, (.60 if len(prices) >= 5 else .50) * min(ebay_freshness, guide_freshness)), 4)
    sources = [
        {"source": "EBAY_OFFICIAL_BROWSE", "observation_type": "ACTIVE", "estimate_minor": ebay_value,
         "observed_at": browse_at.isoformat(), "listing_count": len(prices), "seller_count": len(prices),
         "weight": float(ebay_weight / (ebay_weight + guide_weight)), "shipping_basis": "ITEM_ONLY"},
        {"source": "CARDMARKET", "observation_type": "PRICE_GUIDE", "estimate_minor": guide_value,
         "observed_at": guide_at.isoformat(), "source_product_id": cardmarket_guide["source_product_id"],
         "source_field": cardmarket_guide["source_field"], "condition_specific": False, "language_specific": False,
         "weight": float(guide_weight / (ebay_weight + guide_weight)), "shipping_basis": "ITEM_ONLY"},
    ]
    expiry = min(browse_expiry, guide_at + GUIDE_TTL)
    for row in comparables:
        end_at = _at((row.get("listing_evidence") or {}).get("item_end_date"))
        if end_at is not None:
            expiry = min(expiry, end_at)
    result.update(status="READY", estimate_minor=value, market_value_minor=value,
                  estimate_low_minor=low, estimate_high_minor=high, confidence=confidence,
                  source_count=2, observation_count=len(prices) + 1,
                  observed_at=min(browse_at, guide_at).isoformat(),
                  expires_at=expiry.isoformat(),
                  evidence={"reference_key": reference_key, "reference_identity": identity, "finish": selected_finish,
                            "computed_at": current.isoformat(),
                            "sources": sources, "excluded_browse_count": rejected,
                            "ebay_comparables": deepcopy(comparables),
                            "cardmarket_provenance": deepcopy(dict(cardmarket_guide["provenance"])),
                            "source_disagreement_ratio": float(Decimal(max(ebay_value, guide_value)) / min(ebay_value, guide_value)),
                            "policy": "EQUAL_INITIAL_SOURCE_INFLUENCE_WITH_3D_7D_FRESHNESS_DECAY",
                            "calibration_status": "PROVISIONAL_NOT_YET_BACKTESTED"})
    return result
