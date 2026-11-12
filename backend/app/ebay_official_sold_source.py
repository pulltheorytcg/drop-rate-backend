"""Official UK completed-sales acquisition adapter — strictly permission gated.

Preparation for an autonomous *sold-only* evidence channel. eBay Marketplace
Insights is a restricted partner API: no HTTP request is permitted unless
explicit business approval and exact UK category grants have been recorded.
No Browse listing can be substituted. No AI pricing or DB/Shopify writes.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

import httpx

from .ebay_official_adapter import _grade_matches, _looks_like_multi_item_listing
from .ebay_official_client import EBAY_PRODUCTION_BASE_URL, EbayApiError, EbayOfficialClient, _retry_after
from .ebay_sold_pricing import _matches_comp, _normalise_text, _contains_term
from .market_adapters import NormalizedMarketObservation, stable_source_record_key

INSIGHTS_PATH = "/buy/marketplace_insights/v1_beta/item_sales/search"
NORMALIZATION_REVISION = "drop-rate-ebay-official-insights-uk-sold-v1"
SOURCE_ACCESS = "EBAY_MARKETPLACE_INSIGHTS_RESTRICTED"
MAX_PAGE_ROWS = 25
MAX_PRICE_MINOR = 1_000_000_000
ID_RE = re.compile(r"(?:v1\|)?[1-9][0-9]{5,19}(?:\|(?:0|[1-9][0-9]{0,19}))?")
CATEGORY_RE = re.compile(r"[1-9][0-9]{0,7}")


@dataclass(frozen=True)
class MarketplaceInsightsApproval:
    """A signed-in seller or Browse API OAuth token is NOT an approval."""
    enabled: bool
    approval_reference: str | None
    permitted_uk_categories: frozenset[str]
    provider_terms_reviewed: bool = False

    def authorize(self, category_id: str) -> None:
        if (not self.enabled or not self.provider_terms_reviewed
                or not isinstance(self.approval_reference, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,79}", self.approval_reference)
                or not CATEGORY_RE.fullmatch(category_id)
                or category_id not in self.permitted_uk_categories):
            raise PermissionError("Official eBay sold-history partner access is not approved for this UK category")


class OfficialMarketplaceInsightsClient:
    """Read-only official provider request, using the existing eBay OAuth client."""

    def __init__(self, *, oauth_client: EbayOfficialClient,
                 approval: MarketplaceInsightsApproval, timeout_seconds: float = 15.0):
        self.oauth_client = oauth_client
        self.approval = approval
        self.timeout = timeout_seconds

    async def sold(self, *, query: str, category_id: str, limit: int = MAX_PAGE_ROWS) -> dict:
        # Check access BEFORE requesting any application token or making HTTP calls.
        self.approval.authorize(category_id)
        if self.oauth_client.marketplace_id != "EBAY_GB":
            raise PermissionError("Only explicitly approved eBay UK sold history is supported")
        if (not isinstance(query, str) or not 4 <= len(query.strip()) <= 190
                or "*" in query):
            raise ValueError("Exact printing name/number query required")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_ROWS:
            raise ValueError("Bounded sold-history page required")
        token = await self.oauth_client.application_token()
        params = {"q": query.strip(), "category_ids": category_id, "limit": limit,
                  "filter": "itemLocationCountry:GB,priceCurrency:GBP"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(
                    EBAY_PRODUCTION_BASE_URL + INSIGHTS_PATH,
                    params=params,
                    headers={"Authorization": f"Bearer {token}",
                             "X-EBAY-C-MARKETPLACE-ID": "EBAY_GB",
                             "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise EbayApiError("Official eBay sold-history request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbayApiError("Official eBay sold-history request failed", retryable=True) from exc
        if response.status_code != 200:
            # Restricted access rejection is a blocker, not a hint to scrape.
            raise EbayApiError("Official eBay sold-history access unavailable",
                               status_code=response.status_code,
                               retryable=response.status_code in {429, 500, 502, 503, 504},
                               retry_after_seconds=_retry_after(response))
        try:
            value = response.json()
        except ValueError as exc:
            raise EbayApiError("Official eBay sold-history returned invalid JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("itemSales"), list):
            raise EbayApiError("Official eBay sold-history returned an invalid itemSales response")
        if len(value["itemSales"]) > limit:
            raise EbayApiError("Official eBay sold-history response exceeds bounded page size")
        return value


def _minor(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount > Decimal(MAX_PRICE_MINOR) / 100:
        return None
    if amount.as_tuple().exponent < -2:
        return None
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _instant(raw: Any, now: datetime) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None or at.utcoffset() is None:
        return None
    at = at.astimezone(timezone.utc)
    if at > now + timedelta(minutes=5) or at < now - timedelta(days=90):
        return None
    return at


def _strict_title(row: dict, target: dict) -> bool:
    title = row.get("title")
    if not isinstance(title, str) or not title.strip() or _looks_like_multi_item_listing(title):
        return False
    if not _matches_comp({"title": title, "condition_raw": row.get("condition")}, target):
        return False
    grader = target.get("grading_company")
    if grader and not _grade_matches(title, grader, target.get("grade")):
        return False
    if (str(target.get("game") or "").casefold() == "one piece"
            and _normalise_text(target.get("variant", "")) == "foil"
            and not any(_contains_term(_normalise_text(target.get("name", "")), term)
                        for term in ("parallel", "manga", "alternate art", "alt art", "sp"))
            and any(_contains_term(_normalise_text(title), term)
                    for term in ("parallel", "manga", "alternate art", "alt art", "sp"))):
        return False
    return True


def normalize_marketplace_insights(
    payload: dict,
    *, target: dict[str, Any],
    approval: MarketplaceInsightsApproval,
    category_id: str,
    now: datetime,
) -> dict:
    """Return *candidate source observations*, one at most per distinct sold item.

    This never assumes 'totalSoldQuantity' separate paid transactions have
    distinct known prices. Accepted Best Offer rows are quarantined because
    the API does not independently prove that amount to our verifier.
    """
    approval.authorize(category_id)
    if now.tzinfo is None:
        raise ValueError("Aware validation timestamp required")
    if not isinstance(payload, dict) or not isinstance(payload.get("itemSales"), list):
        raise ValueError("Official itemSales data required")
    if len(payload["itemSales"]) > MAX_PAGE_ROWS:
        raise ValueError("Official sold history page exceeds bounded limit")
    if not all(target.get(key) for key in ("game", "name", "set_name", "card_number", "variant", "language")):
        raise ValueError("Complete canonical printing identity required")
    if bool(target.get("grading_company")) != bool(target.get("grade")):
        raise ValueError("Grade and grading company must be paired")
    reasons = Counter()
    accepted: dict[str, NormalizedMarketObservation] = {}
    collisions: set[str] = set()
    for row in payload["itemSales"]:
        if not isinstance(row, dict):
            reasons["INVALID_ROW"] += 1
            continue
        key = str(row.get("itemId") or "").strip()
        if not ID_RE.fullmatch(key):
            reasons["INVALID_ITEM_ID"] += 1
            continue
        if key in collisions:
            reasons["CONFLICTING_ITEM_ID"] += 1
            continue
        if (not isinstance(row.get("itemLocation"), dict)
                or row["itemLocation"].get("country") != "GB"):
            reasons["NON_UK_ITEM_LOCATION"] += 1
            continue
        price_field = row.get("lastSoldPrice")
        if not isinstance(price_field, dict) or price_field.get("currency") != "GBP":
            reasons["NO_GBP_ACTUAL_SOLD_PRICE"] += 1
            continue
        price_minor = _minor(price_field.get("value"))
        at = _instant(row.get("lastSoldDate"), now)
        if price_minor is None or at is None:
            reasons["INVALID_OR_STALE_SOLD_AMOUNT_DATE"] += 1
            continue
        options = row.get("buyingOptions")
        if (not isinstance(options, list) or not options
                or any(not isinstance(o, str) for o in options)
                or "BEST_OFFER" in options
                or not any(o in {"AUCTION", "FIXED_PRICE"} for o in options)):
            reasons["AMBIGUOUS_BEST_OFFER_OR_FORMAT"] += 1
            continue
        if "AUCTION" in options and (type(row.get("bidCount")) is not int or row["bidCount"] < 1):
            reasons["AUCTION_WITHOUT_CONFIRMED_BID"] += 1
            continue
        if type(row.get("totalSoldQuantity")) is not int or row["totalSoldQuantity"] < 1:
            reasons["NOT_CONFIRMED_SOLD"] += 1
            continue
        if not _strict_title(row, target):
            reasons["WRONG_EXACT_PRINTING_OR_PHYSICAL_STATE"] += 1
            continue

        normalized_id = stable_source_record_key(
            "EBAY", "OFFICIAL_INSIGHTS", key, at.isoformat(), NORMALIZATION_REVISION
        )
        # Every field must derive from the independently approved provider
        # response, not a user's manually asserted source boolean.
        record = NormalizedMarketObservation(
            source="EBAY",
            source_record_key=normalized_id,
            observation_type="SOLD",
            observed_at=at,
            price_minor=price_minor,
            currency="GBP",
            price_gbp_minor=price_minor,
            shipping_minor=None,
            shipping_gbp_minor=None,
            fx_rate_to_gbp=Decimal(1),
            catalogue_id=str(target["catalogue_id"]),
            condition=None if target.get("grading_company") else target.get("condition"),
            grading_company=target.get("grading_company"),
            grade=target.get("grade"),
            language=target["language"],
            seal_status=target.get("seal_status"),
            source_country="GB",
            sample_size=1,
            evidence_quality=1.0,
            metadata={
                "access_method": SOURCE_ACCESS,
                "marketplace": "EBAY_GB",
                "provider_item_id": key,
                "title": row["title"],
                "provider_evidence": {
                    "normalization_revision": NORMALIZATION_REVISION,
                    "item_location_country": "GB",
                    "sale_price_basis": ("OFFICIAL_LAST_SOLD_AUCTION_PRICE"
                                         if "AUCTION" in options
                                         else "OFFICIAL_LAST_SOLD_FIXED_PRICE"),
                    "last_sold_at": at.isoformat(),
                    "partner_approval_reference": approval.approval_reference,
                    "approved_category_id": category_id,
                    "total_sold_quantity": row["totalSoldQuantity"],
                    "source_has_no_per_transaction_history": True,
                    "accepted_best_offer_uncertain_rows_excluded": True,
                },
            },
        ).validate()
        if key in accepted:
            if accepted[key] != record:
                accepted.pop(key)
                collisions.add(key)
                reasons["CONFLICTING_ITEM_ID"] += 2
            else:
                reasons["DUPLICATE_ITEM_ID"] += 1
        else:
            accepted[key] = record
    return {"observations": list(accepted.values()),
            "count": len(accepted), "rejected": dict(sorted(reasons.items())),
            "status": "CANDIDATES_REQUIRE_INDEPENDENT_REVIEW",
            "partner_access_asserted_in_configuration": True,
            "can_publish_market_value": False}



def preview_verified_sold_market_value(
    normalized: dict, *, target: dict[str, Any], as_of: datetime,
) -> dict[str, Any]:
    """Run existing v4 deterministic engine for five distinct sale candidates.

    Never writes any price, and a provider candidate alone can *never*
    authorise a public Market Value: external permission, actual amounts,
    exact printing and business review are independent release gates.
    """
    from .pricing_engine import ComparableTarget, MarketObservation, PricingPolicy, calculate_price

    rows = normalized.get("observations") if isinstance(normalized, dict) else None
    if not isinstance(rows, list) or len(rows) < 5:
        return {"status": "INSUFFICIENT_VERIFIED_SALES", "candidate_market_value_minor": None,
                "verified_sale_count": len(rows) if isinstance(rows, list) else 0,
                "persisted": False, "publishable": False}
    if any(not isinstance(row, NormalizedMarketObservation)
           or row.source != "EBAY"
           or row.observation_type != "SOLD"
           or row.source_country != "GB"
           or row.currency != "GBP"
           or row.metadata.get("access_method") != SOURCE_ACCESS
           or row.metadata.get("provider_evidence", {}).get("normalization_revision") != NORMALIZATION_REVISION
           or row.metadata.get("provider_evidence", {}).get("partner_approval_reference") is None
           or row.catalogue_id != str(target.get("catalogue_id"))
           for row in rows):
        raise ValueError("Untrusted or mixed-source evidence cannot enter sold-price preview")
    if len({row.source_record_key for row in rows}) != len(rows):
        return {"status": "DUPLICATE_SALE_EVIDENCE", "candidate_market_value_minor": None,
                "verified_sale_count": len({row.source_record_key for row in rows}),
                "persisted": False, "publishable": False}
    if (not isinstance(as_of, datetime) or as_of.utcoffset() is None
            or max(row.observed_at for row in rows) < as_of - timedelta(days=7)):
        return {"status": "STALE_SOLD_EVIDENCE", "candidate_market_value_minor": None,
                "verified_sale_count": len(rows),
                "persisted": False, "publishable": False}
    physical = ComparableTarget(
        condition=target.get("condition"),
        grading_company=target.get("grading_company"),
        grade=target.get("grade"),
        language=target.get("language"),
        seal_status=target.get("seal_status"),
    )
    observations = [
        MarketObservation(
            source=o.source, observation_type=o.observation_type,
            observed_at=o.observed_at, price_gbp_minor=o.price_gbp_minor,
            condition=o.condition, grading_company=o.grading_company,
            grade=o.grade, language=o.language, seal_status=o.seal_status,
            source_country=o.source_country, source_record_key=o.source_record_key,
            sample_size=1, evidence_quality=o.evidence_quality,
        ) for o in rows
    ]
    try:
        result = calculate_price(
            observations, target=physical, policy=PricingPolicy(),
            current_store_price_minor=None, as_of=as_of)
    except ValueError:
        return {"status": "COMPARABILITY_BLOCKED", "candidate_market_value_minor": None,
                "verified_sale_count": 0, "persisted": False, "publishable": False}
    if result.sold_observation_count < 5:
        return {"status": "INSUFFICIENT_POST_FILTER_SALES", "candidate_market_value_minor": None,
                "verified_sale_count": result.sold_observation_count,
                "persisted": False, "publishable": False}
    return {
        "status": "REVIEW_REQUIRED",
        "candidate_market_value_minor": result.market_value_minor,
        "verified_sale_count": result.sold_observation_count,
        "algorithm_version": result.algorithm_version,
        "confidence": result.confidence,
        "volatility_pct": result.volatility_pct,
        "block_reasons": list(result.block_reasons),
        "persisted": False,
        "publishable": False,
        "store_price_changed": False,
        "shopify_changed": False,
    }
