"""Display-only current asking estimates; never physical market-value authority."""
import json
from datetime import datetime, timedelta, timezone

from .reference_applicability import DIGITAL_REFERENCE_SQL

ASKING_METHOD_VERSION = "EBAY_UK_RAW_ASK_V1"
ASKING_SOURCE = "EBAY_OFFICIAL_BROWSE"
ASKING_MAX_AGE = timedelta(days=3)
ASKING_FINISHES = frozenset({"Normal", "Holo", "Reverse Holo", "Foil", "Parallel", "Alt Art", "Manga"})


def asking_cache_join(*, as_of_sql="now()"):
    """Shared eligibility for reference aliases r/s and asking-cache alias a.

    Only internal, fixed SQL expressions may be passed as the clock expression.
    Identity equality deliberately includes finish/rarity so a corrected printing
    cannot inherit an estimate calculated for an earlier reference identity.
    """
    return f"""left join tcg.reference_asking_prices a
 on (a.provider,a.system_code,a.language,a.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and a.reference_identity=jsonb_build_object('name',r.name,'set_id',r.set_id,
   'card_number',r.card_number,'set_name',s.name,'finish',r.finish,'rarity',r.rarity)
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
select w.key,a.*,jsonb_build_object('name',r.name,'set_id',r.set_id,
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


async def add_asking_estimates(connection, rows, *, now=None):
    """One page-bounded fallback query, leaving all market-value fields unchanged."""
    now = now or datetime.now(timezone.utc)
    items = [dict(row) for row in rows]
    pending = []
    for row in items:
        row.pop("asking_price_estimate", None)
        shared = row.get("shared_price") or {}
        if (row.get("source_kind") == "REFERENCE" and row.get("product_type") == "CARD"
                and row.get("market_value_minor") is None
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
            row["asking_price_estimate"] = estimates[row["key"]]
    return items
