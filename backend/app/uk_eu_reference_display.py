"""Read-only UK/EU estimates from current, exact reference evidence.

The model is a separate reference display. It never replaces physical-copy
values, financial totals, source observations or retail recommendations.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .reference_asking_display import (
    ASKING_DISPLAY_SQL, asking_estimate_view,
)
from .uk_eu_market_estimate import estimate_uk_eu_market

METHOD = "DROP_RATE_UK_EU_MARKET_V1"
LABEL = "Drop Rate UK/EU estimate"
REASON = ("Calculated from eBay UK asking prices and Cardmarket guides. "
          "Provisional; not a completed-sale value.")
IDENTITY_KEYS = ("name", "set_id", "card_number", "set_name", "finish", "rarity")
REFERENCE_KEYS = ("provider", "system_code", "language", "provider_id")
FINISHES = {"normal": "Normal", "holo": "Holo", "holofoil": "Holo",
            "reverse holo": "Reverse Holo", "reverse holofoil": "Reverse Holo",
            "foil": "Foil", "parallel": "Parallel", "alt art": "Alt Art", "manga": "Manga"}

# The shared query already validates current reference identity, exact matching
# evidence, seller counts, age, expiry and the three-day cache contract.
MODEL_DISPLAY_SQL = ASKING_DISPLAY_SQL.replace(
    "select w.key,a.*,", "select w.key,a.*,a.snapshot_id as source_snapshot_id,r.evidence as reference_evidence,"
    "coalesce(m.quotes,'[]'::jsonb) as market_quotes,"
    "coalesce(b.quotes,'[]'::jsonb) as catalogue_quotes,"
).replace(
    "where a.provider_id is not null",
    "left join tcg.reference_market_prices m on (m.provider,m.system_code,m.language,m.provider_id)="
    "(r.provider,r.system_code,r.language,r.provider_id)\n"
    "left join tcg.reference_catalogue_prices b on (b.provider,b.system_code,b.language,b.provider_id)="
    "(r.provider,r.system_code,r.language,r.provider_id)\n"
    "where a.provider_id is not null",
)


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    return result


def _object(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else None


def _quotes(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


def _finish(value):
    return FINISHES.get(str(value or "").strip().casefold())


def cardmarket_model_guide(reference, selected_finish, *, now):
    """Normalize one exact TCGdex Cardmarket finish with its original FX proof.

    Named treatments and broad catalogue guides need their own exact mapping;
    neither is silently interpreted as the ordinary printing here.
    """
    selected = _finish(selected_finish)
    if not selected or reference.get("provider") != "TCGdex":
        return None
    try:
        now = _time(now)
        quotes = _quotes(reference.get("quotes")) + _quotes(reference.get("catalogue_quotes"))
        eligible = []
        for quote in quotes:
            if not isinstance(quote, dict) or quote.get("source") != "TCGDEX_CARDMARKET":
                continue
            if ("reference_identity" in quote
                    and quote["reference_identity"] != {k: reference.get(k) for k in IDENTITY_KEYS[:4]}):
                continue
            if (quote.get("reference_language") != reference.get("language")
                    or _finish(quote.get("finish")) != selected
                    or quote.get("variant_label") != quote.get("finish")
                    or quote.get("source_field") not in {"trend", "trend-holo"}
                    or (selected == "Normal" and quote.get("source_field") != "trend")
                    or (selected == "Reverse Holo" and quote.get("source_field") != "trend-holo")
                    or quote.get("original_currency") != "EUR"
                    or quote.get("fx_source") != "ECB_EURO_REFERENCE_RATES"
                    or not isinstance(quote.get("product_id"), (str, int))
                    or isinstance(quote.get("product_id"), bool)
                    or not str(quote["product_id"]).isdigit() or int(quote["product_id"]) <= 0
                    or not isinstance(quote.get("variant_id"), str) or not quote["variant_id"].strip()):
                continue
            try:
                observed = _time(quote["observed_at"])
                effective, retrieved = _time(quote["fx_effective_at"]), _time(quote["fx_retrieved_at"])
                amount, original = quote["price_gbp_minor"], quote["original_minor"]
                rate = Decimal(str(quote["fx_rate_to_gbp"]))
                if (any(type(v) is not int or v <= 0 for v in (amount, original))
                        or not rate.is_finite() or rate <= 0
                        or not now - timedelta(days=7) <= observed <= now
                        or not now - timedelta(days=7) <= effective <= retrieved <= now
                        or int((Decimal(original) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) != amount):
                    continue
            except (KeyError, ValueError, TypeError, InvalidOperation):
                continue
            eligible.append((quote, observed))
        products = {(str(q["product_id"]), q["variant_id"], _finish(q["finish"])) for q, _ in eligible}
        if len(products) != 1:
            return None
        newest = max(t for _, t in eligible)
        eligible = [q for q, t in eligible if t == newest]
        if len({(q["source_field"], q["price_gbp_minor"], q["original_minor"], str(q["fx_rate_to_gbp"])) for q in eligible}) != 1:
            return None
        quote = eligible[0]
        return {
            "source": "CARDMARKET", "source_product_id": str(quote["product_id"]),
            "source_field": quote["source_field"], "currency": "GBP",
            "price_gbp_minor": quote["price_gbp_minor"], "shipping_basis": "ITEM_ONLY",
            "observed_at": newest, "finish": selected,
            "reference_key": {k: reference[k] for k in REFERENCE_KEYS},
            "reference_identity": {k: reference.get(k) for k in IDENTITY_KEYS},
            "condition_specific": False, "language_specific": False,
            "provenance": dict(quote),
        }
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None


def estimate_from_reference(reference, browse_report, *, now):
    """Pure integration seam shared by cached displays and transient probes."""
    guide = cardmarket_model_guide(reference, browse_report.get("selected_finish"), now=now)
    if guide is None:
        return None
    return estimate_uk_eu_market(reference, browse_report, guide, now=now)


def cached_browse_report(record, *, now):
    """Restore only the evidence already admitted by the validated cache."""
    if asking_estimate_view(record, now=now) is None:
        return None
    try:
        evidence = _object(record["evidence"])
        identity = _object(record["reference_identity"])
        observed, expires = _time(record["observed_at"]), _time(record["expires_at"])
        comparables = evidence.get("comparables")
        if not isinstance(comparables, list) or not 3 <= len(comparables) <= 100:
            return None
        restored = []
        for row in comparables:
            if not isinstance(row, dict):
                return None
            item, shipping = row.get("price_gbp_minor"), row.get("shipping_gbp_minor")
            if type(item) is not int or item <= 0 or type(shipping) is not int or shipping < 0:
                return None
            restored.append(dict(row, delivered_gbp_minor=item + shipping,
                observed_at=observed.isoformat(), condition=evidence["condition"],
                finish=evidence["finish"], match_proof=evidence.get("match_proof", {})))
        return {
            "status": "READY", "source": "EBAY_OFFICIAL_BROWSE", "method_version": record["method_version"],
            "basis": "ASKING_PRICE_ESTIMATE", "currency": "GBP", "condition_basis": "RAW_NEAR_MINT_OR_MINT",
            "identity": identity, "selected_finish": evidence["finish"],
            "observed_at": observed.isoformat(), "expires_at": expires.isoformat(),
            "comparables": restored, "sample_count": record["listing_count"], "seller_count": record["seller_count"],
            "physical_valuation_eligible": False, "includes_shipping": True,
        }
    except (KeyError, ValueError, TypeError):
        return None


def public_model_view(result):
    if not result or result.get("status") != "READY":
        return None
    return {"status": "UK_EU_MARKET_ESTIMATE", "method": METHOD, "label": LABEL,
        "currency": "GBP", "estimate_minor": result["estimate_minor"],
        "estimate_low_minor": result["estimate_low_minor"], "estimate_high_minor": result["estimate_high_minor"],
        "confidence": result["confidence"], "observed_at": result["observed_at"], "expires_at": result["expires_at"],
        "computed_at": result.get("computed_at"), "finish": result.get("evidence", {}).get("finish"),
        "shipping_basis": "ITEM_ONLY", "physical_valuation_eligible": False,
        "sold_observation_count": 0, "source_count": 2, "reason": REASON,
        "source_estimates": [{k: value for k, value in source.items()
                              if k in {"source", "estimate_minor", "price_gbp_minor", "weight", "observed_at", "observation_type"}}
                             for source in result.get("evidence", {}).get("sources", [])]}


async def add_uk_eu_estimates(connection, rows, *, now=None):
    """One page-bounded read, no provider calls, and no legacy value replacement."""
    now = now or datetime.now(timezone.utc)
    items = [dict(row) for row in rows]
    pending = []
    for row in items:
        row.pop("uk_eu_market_estimate", None)
        try:
            source_quotes = (_quotes(row.get("quotes")) + _quotes(row.get("market_quotes"))
                             + _quotes(row.get("catalogue_quotes")))
        except (ValueError, TypeError):
            source_quotes = []
        if (row.get("provider") == "TCGdex" and row.get("source_kind", "REFERENCE") == "REFERENCE"
                and row.get("product_type", "CARD") == "CARD"
                and not row.get("grading_company") and not row.get("grade") and not row.get("seal_status")
                and any(isinstance(q, dict) and q.get("source") == "TCGDEX_CARDMARKET" for q in source_quotes)
                and all(isinstance(row.get(k), str) and row[k] for k in REFERENCE_KEYS)):
            pending.append(row)
    if not pending:
        return items
    lookup = {}
    for row in pending:
        key = tuple(row[k] for k in REFERENCE_KEYS)
        lookup[key] = {"key": "r:" + hashlib.md5("\x1f".join(key).encode()).hexdigest(),
                       **dict(zip(REFERENCE_KEYS, key))}
    estimates = {}
    for start in range(0, len(lookup), 100):
        keys = list(lookup.values())[start:start + 100]
        for raw in await connection.fetch(MODEL_DISPLAY_SQL, json.dumps(keys), now):
            record = dict(raw)
            report = cached_browse_report(record, now=now)
            if report is None:
                continue
            reference = {**dict(zip(REFERENCE_KEYS, (record.get(k) for k in REFERENCE_KEYS))),
                **(_object(record.get("current_identity")) or {}),
                "evidence": _object(record.get("reference_evidence")) or {},
                "quotes": record.get("market_quotes"), "catalogue_quotes": record.get("catalogue_quotes")}
            value = public_model_view(estimate_from_reference(reference, report, now=now))
            if value:
                estimates[tuple(reference[k] for k in REFERENCE_KEYS)] = value
    for row in pending:
        value = estimates.get(tuple(row[k] for k in REFERENCE_KEYS))
        if value:
            row["uk_eu_market_estimate"] = value
    return items
