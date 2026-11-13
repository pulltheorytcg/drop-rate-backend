"""Exact current UK asking prices as founder-selected catalogue Market Value basis.

The user has chosen asking-price-derived Market Values instead of sold-only
values. Physical item prices and financials remain separate: no SQL write,
no Shopify updates, no sale claim and no grade/condition inference.
"""
import json
from datetime import datetime, timedelta, timezone

from .reference_applicability import DIGITAL_REFERENCE_SQL

ASKING_METHOD_VERSION = "EBAY_UK_RAW_ASK_V1"
ASKING_SOURCE = "EBAY_OFFICIAL_BROWSE"
ASKING_MARKET_VALUE_SOURCE = "DROP_RATE_UK_ASKING_MARKET_V1"
ASKING_MARKET_VALUE_BASIS = "CURRENT_UK_ACTIVE_ASKING_LISTINGS"
ASKING_MAX_AGE = timedelta(days=3)
ASKING_FINISHES = frozenset({"Normal", "Holo", "Reverse Holo", "Foil", "Parallel", "Alt Art", "Manga"})
MATCHING_EVIDENCE_KEYS = ("provider_variant", "variant_title_terms", "set_title_terms", "set_name")
MATCHING_EVIDENCE_SQL = "jsonb_build_object(" + ",".join(
    f"'{key}',r.evidence->'{key}'" for key in MATCHING_EVIDENCE_KEYS) + ")"


def reference_number_alias(alias):
    """Same printing-number grouping for acquisition and cache invalidation."""
    return f"regexp_replace(lower(regexp_replace(regexp_replace(split_part({alias}.card_number,'/',1),'_p[0-9]+$','','i'),'[^[:alnum:]]','','g')),'^0+([0-9])','\\1')"


def matching_reference_evidence(reference):
    evidence = reference.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    return {key: evidence.get(key) for key in MATCHING_EVIDENCE_KEYS}


def asking_cache_join(*, as_of_sql="now()"):
    """Shared eligibility for reference aliases r/s and asking-cache alias a.

    Only internal, fixed SQL expressions may be passed as the clock expression.
    Identity equality deliberately includes finish/rarity so a corrected printing
    cannot inherit an estimate calculated for an earlier reference identity.
    """
    return f"""left join (
 select other.provider,other.system_code,other.language,other.set_id,
   {reference_number_alias('other')} as number_alias,count(*)::integer as reference_group_count
 from tcg.reference_cards other join (
   select distinct cached_ref.provider,cached_ref.system_code,cached_ref.language,cached_ref.set_id
   from tcg.reference_cards cached_ref join tcg.reference_asking_prices cached
   using(provider,system_code,language,provider_id)
 ) asking_sets using(provider,system_code,language,set_id)
 group by other.provider,other.system_code,other.language,other.set_id,{reference_number_alias('other')}
) asking_groups on (asking_groups.provider,asking_groups.system_code,asking_groups.language,asking_groups.set_id)=
 (r.provider,r.system_code,r.language,r.set_id) and asking_groups.number_alias={reference_number_alias('r')}
left join tcg.reference_asking_prices a
 on (a.provider,a.system_code,a.language,a.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and a.reference_identity=jsonb_build_object('name',r.name,'set_id',r.set_id,
   'card_number',r.card_number,'set_name',s.name,'finish',r.finish,'rarity',r.rarity)
 and a.evidence->'matching_reference_evidence'={MATCHING_EVIDENCE_SQL}
 and a.evidence->'reference_group_count'=to_jsonb(asking_groups.reference_group_count)
 and a.method_version='{ASKING_METHOD_VERSION}' and a.currency='GBP'
 and a.evidence->>'source'='{ASKING_SOURCE}'
 and a.evidence->>'shipping_basis'='ITEM_PLUS_SHIPPING'
 and a.evidence->>'shipping_context'='CONFIGURED_SHOP_POSTCODE_BENCHMARK'
 and a.evidence->>'condition'='Near Mint'
 and a.evidence->>'finish' in ('Normal','Holo','Reverse Holo','Foil','Parallel','Alt Art','Manga')
 and a.estimate_minor>0 and a.estimate_high_minor>=a.estimate_minor
 and a.listing_count>=3 and a.seller_count>=3 and a.seller_count<=a.listing_count
 and a.observed_at<={as_of_sql} and a.observed_at>={as_of_sql}-interval '3 days'
 and a.expires_at>{as_of_sql} and a.expires_at<=a.observed_at+interval '3 days'
 and not ({DIGITAL_REFERENCE_SQL})"""


ASKING_DISPLAY_SQL = f"""with wanted as (
 select * from jsonb_to_recordset($1::jsonb) as x(
   key text,provider text,system_code text,language text,provider_id text)
)
select w.key,a.*,{MATCHING_EVIDENCE_SQL} as current_matching_reference_evidence,
 asking_groups.reference_group_count as current_reference_group_count,
 jsonb_build_object('name',r.name,'set_id',r.set_id,
 'card_number',r.card_number,'set_name',s.name,'finish',r.finish,'rarity',r.rarity) as current_identity
from wanted w join tcg.reference_cards r using(provider,system_code,language,provider_id)
join tcg.reference_sets s using(provider,system_code,language,set_id)
{asking_cache_join(as_of_sql='$2::timestamptz')}
where a.provider_id is not null"""


def _object(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else None


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError("An aware evidence timestamp is required")
    return result


def asking_estimate_view(record, *, now):
    """Validate the cache contract again before exposing a bounded public view."""
    try:
        evidence = _object(record.get("evidence"))
        identity = _object(record.get("reference_identity"))
        current_identity = _object(record.get("current_identity"))
        low, high = record.get("estimate_minor"), record.get("estimate_high_minor")
        listings, sellers = record.get("listing_count"), record.get("seller_count")
        observed, expires = _time(record.get("observed_at")), _time(record.get("expires_at"))
        if (record.get("method_version") != ASKING_METHOD_VERSION or record.get("currency") != "GBP"
                or not evidence or evidence.get("source") != ASKING_SOURCE
                or evidence.get("shipping_basis") != "ITEM_PLUS_SHIPPING"
                or evidence.get("shipping_context") != "CONFIGURED_SHOP_POSTCODE_BENCHMARK"
                or evidence.get("condition") != "Near Mint" or evidence.get("finish") not in ASKING_FINISHES
                or evidence.get("matching_reference_evidence") != _object(record.get("current_matching_reference_evidence"))
                or not isinstance(evidence.get("matching_reference_evidence"), dict)
                or set(evidence["matching_reference_evidence"]) != set(MATCHING_EVIDENCE_KEYS)
                or type(evidence.get("reference_group_count")) is not int
                or evidence["reference_group_count"] < 1
                or evidence["reference_group_count"] != record.get("current_reference_group_count")
                or not identity or identity != current_identity
                or set(identity) != {"name", "set_id", "card_number", "set_name", "finish", "rarity"}
                or any(type(amount) is not int for amount in (low, high, listings, sellers))
                or low <= 0 or high < low or listings < 3 or sellers < 3 or sellers > listings
                or not now - ASKING_MAX_AGE <= observed <= now < expires <= observed + ASKING_MAX_AGE):
            return None
    except (TypeError, ValueError):
        return None
    return {
        "status": "ASKING_PRICE_ESTIMATE", "source": ASKING_SOURCE,
        "method_version": ASKING_METHOD_VERSION, "currency": "GBP",
        "estimate_minor": low, "estimate_high_minor": high,
        "listing_count": listings, "seller_count": sellers,
        "observed_at": observed, "expires_at": expires,
        "shipping_basis": "ITEM_PLUS_SHIPPING",
        "shipping_context": "CONFIGURED_SHOP_POSTCODE_BENCHMARK",
        "condition": evidence["condition"], "finish": evidence["finish"],
        "physical_valuation_eligible": False, "recommended_retail_minor": None,
    }


def asking_market_value_fields(view):
    """Project the already-validated robust three-seller median into catalogue MV.

    This does not reprice from one seller or create any new statistics: the
    existing independent seller, exact printing, GBP, NM condition, shipped
    price and expiry checks remain mandatory. Retail/store prices are not
    calculated or changed here. If the cache is expired no value is emitted.
    """
    if not isinstance(view, dict) or view.get("status") != "ASKING_PRICE_ESTIMATE":
        return None
    price, high, sellers = view.get("estimate_minor"), view.get("estimate_high_minor"), view.get("seller_count")
    if (type(price) is not int or price <= 0 or type(high) is not int or high < price
            or type(sellers) is not int or sellers < 3):
        return None
    return {
        "market_value_minor": price,
        "market_value_high_minor": high,
        "market_value_source": ASKING_MARKET_VALUE_SOURCE,
        "market_value_basis": ASKING_MARKET_VALUE_BASIS,
        "market_value_confidence": "MEDIUM" if sellers >= 5 else "LOW",
        "market_value_observed_at": view["observed_at"],
        "market_value_expires_at": view["expires_at"],
        "pricing_updated_at": view["observed_at"],
        "basis_condition": view["condition"],
        "market_value_evidence": {
            "provider": view["source"],
            "method_version": view["method_version"],
            "currency": "GBP",
            "listing_count": view["listing_count"],
            "independent_seller_count": sellers,
            "shipping_basis": view["shipping_basis"],
            "basis_type": ASKING_MARKET_VALUE_BASIS,
            "completed_sales_used": 0,
        },
    }


_EXPIRED_GUIDE_SOURCES = frozenset({
    "TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT", "TCGDEX_TCGPLAYER",
    "CARDMARKET_BULK", "CARDMARKET_BULK_SINGLES", "CARDMARKET_CATALOGUE",
    "POKEWALLET_POKEMON_CARDMARKET_CATALOGUE",
    "TCGCSV_TCGPLAYER_CATALOGUE", "DROP_RATE_COMPUTED_MARKET_V1",
})


def expired_reference_guide(row, now):
    """Expired legacy *catalogue* guides may not block current asking evidence.

    A null/non-expiring or unknown source is deliberately not treated as an
    expired guide. Current stored-sale/shared prices and physical inventory
    cannot be replaced by this reference-only display projection.
    """
    if row.get("market_value_source") not in _EXPIRED_GUIDE_SOURCES:
        return False
    timestamp = row.get("pricing_updated_at")
    try:
        checked = _time(timestamp)
        if checked.utcoffset() is None:
            return False
        return checked < now - timedelta(days=7)
    except (TypeError, ValueError, OverflowError):
        return False


async def add_asking_estimates(connection, rows, *, now=None):
    """Bounded verified-cache read with an asking-derived Market Value fallback.

    Never updates inventory, product/store retail prices or other persisted
    values. A canonical reference row is the only eligible fallback; owned
    physical items, grade-specific slabs and missing proof remain unchanged.
    """
    now = now or datetime.now(timezone.utc)
    items = [dict(row) for row in rows]
    pending = []
    for row in items:
        row.pop("asking_price_estimate", None)
        # Never inherit a previously calculated asking basis from an outdated
        # response if this function is invoked twice on the same in-memory row.
        if row.get("market_value_source") == ASKING_MARKET_VALUE_SOURCE:
            for key in ("market_value_minor","market_value_high_minor","market_value_source",
                        "market_value_basis","market_value_confidence","market_value_observed_at",
                        "market_value_expires_at","market_value_evidence",
                        "pricing_updated_at","basis_condition"):
                row.pop(key,None)
        shared = row.get("shared_price") or {}
        if (row.get("source_kind") == "REFERENCE" and row.get("product_type") == "CARD"
                and not row.get("grading_company") and not row.get("grade") and not row.get("seal_status")
                and (row.get("market_value_minor") is None or expired_reference_guide(row, now))
                and not (shared.get("market_value_minor") is not None and shared.get("status") != "STALE")):
            pending.append(row)
    if not pending:
        return items
    keys = [{key: row[key] for key in ("key", "provider", "system_code", "language", "provider_id")}
            for row in pending]
    estimates = {}
    for record in await connection.fetch(ASKING_DISPLAY_SQL, json.dumps(keys), now):
        value = asking_estimate_view(dict(record), now=now)
        if value:
            estimates[record["key"]] = value
    for row in pending:
        if row["key"] in estimates:
            derived = asking_market_value_fields(estimates[row["key"]])
            if derived:
                row.update(derived)
            else:
                # Keep explanatory context if the cache is valid but cannot
                # satisfy the chosen model's reliability gates.
                row["asking_price_estimate"] = estimates[row["key"]]
    return items
