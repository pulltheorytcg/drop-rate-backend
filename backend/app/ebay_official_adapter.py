from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .ebay_official_client import EbayOfficialClient
from .ebay_uk_parse_adapter import _contains_term, _normalise_text, _parse_mapping_spec
from .market_adapters import NormalizedMarketObservation, stable_source_record_key


_RAW_GRADED_TERMS = ("psa", "cgc", "bgs", "beckett", "graded", "slab")
_EXPLICIT_MULTI_ITEM_TERMS = ("bundle", "job lot", "playset", "lot of")
_CARD_NUMBER_RE = re.compile(r"\b\d{1,3}/\d{1,3}\b")
_QUANTITY_RE = re.compile(r"\b(?:x\s*([2-9]\d*)|([2-9]\d*)\s*x)\b", re.IGNORECASE)


def _money_minor(money: object, *, expected_currency: str = "GBP") -> int | None:
    if not isinstance(money, dict):
        return None
    currency = money.get("currency")
    value = money.get("value")
    if not isinstance(currency, str) or currency.strip().upper() != expected_currency:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _shipping_minor(row: dict[str, Any]) -> int | None:
    options = row.get("shippingOptions")
    if not isinstance(options, list):
        return None

    values: list[int] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        amount = _money_minor(option.get("shippingCost"))
        if amount is not None:
            values.append(amount)
    return min(values) if values else None


def _condition(row: dict[str, Any]) -> str | None:
    value = row.get("condition")
    if not isinstance(value, str):
        return None
    normalized = _normalise_text(value)
    if "near mint" in normalized:
        return "Near Mint"
    return None


def _variant_matches(
    title: object,
    source_variant_id: str | None,
    *,
    allow_implicit_finish: bool = False,
) -> bool:
    variant = _normalise_text(source_variant_id)
    if not variant:
        return True

    normalized_title = _normalise_text(title)
    if not normalized_title:
        return False

    if variant == "normal":
        return (
            "reverse" not in normalized_title.split()
            and "holo" not in normalized_title.split()
            and "holofoil" not in normalized_title.split()
            and "foil" not in normalized_title.split()
        )
    if variant in {"reverse holo", "reverse holofoil", "reverse"}:
        return _contains_term(normalized_title, "reverse") and (
            _contains_term(normalized_title, "holo")
            or _contains_term(normalized_title, "holofoil")
        )
    if variant in {"holo", "holofoil"}:
        if _contains_term(normalized_title, "reverse"):
            return False
        if _contains_term(normalized_title, "non holo") or _contains_term(normalized_title, "nonholo"):
            return False
        return (
            _contains_term(normalized_title, "holo")
            or _contains_term(normalized_title, "holofoil")
            or allow_implicit_finish
        )
    if variant == "foil":
        if _contains_term(normalized_title, "non foil") or _contains_term(normalized_title, "nonfoil"):
            return False
        return _contains_term(normalized_title, "foil") or allow_implicit_finish
    return _contains_term(normalized_title, source_variant_id)


def _looks_like_multi_item_listing(title: object) -> bool:
    normalized_title = _normalise_text(title)
    if not normalized_title:
        return True

    if any(_contains_term(normalized_title, term) for term in _EXPLICIT_MULTI_ITEM_TERMS):
        return True
    if _QUANTITY_RE.search(normalized_title):
        return True

    card_numbers = {match.group(0) for match in _CARD_NUMBER_RE.finditer(normalized_title)}
    return len(card_numbers) > 1


def _matches_listing(
    title: object,
    *,
    spec: dict[str, Any],
    source_variant_id: str | None,
) -> bool:
    normalized_title = _normalise_text(title)
    if not normalized_title:
        return False
    if _looks_like_multi_item_listing(title):
        return False

    for term in spec["required_title_terms"]:
        if not _contains_term(normalized_title, term):
            return False

    for term in spec["forbidden_title_terms"]:
        if _contains_term(normalized_title, term):
            return False

    if spec["grading_company"]:
        if not _contains_term(normalized_title, spec["grading_company"]):
            return False
        if not _contains_term(normalized_title, spec["grade"]):
            return False
    else:
        for term in _RAW_GRADED_TERMS:
            if _contains_term(normalized_title, term):
                return False

    return _variant_matches(
        title,
        source_variant_id,
        allow_implicit_finish=bool(spec["grading_company"]),
    )


class EbayOfficialBrowseAdapter:
    """Official eBay Browse adapter for active UK listings.

    This adapter intentionally emits ACTIVE evidence only. eBay SOLD history is
    a separate capability and must never be synthesized from Browse results.
    """

    source = "EBAY"

    def __init__(self, *, client: EbayOfficialClient) -> None:
        self._client = client

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        spec = _parse_mapping_spec(source_product_id)
        if not spec["include_active"]:
            return []

        payload = await self._client.search_items(
            query=spec["query"],
            limit=50,
            category_id=spec["category_id"],
            item_location_country="GB",
        )
        rows = payload.get("itemSummaries", [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError("eBay Browse itemSummaries must be an array")

        retrieved_at = datetime.now(timezone.utc)
        observations: dict[str, NormalizedMarketObservation] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _matches_listing(
                row.get("title"),
                spec=spec,
                source_variant_id=source_variant_id,
            ):
                continue

            price_minor = _money_minor(row.get("price"))
            if price_minor is None:
                continue

            item_id = str(row.get("itemId") or "").strip()
            if not item_id:
                continue

            item_location = row.get("itemLocation")
            source_country = None
            if isinstance(item_location, dict):
                country = item_location.get("country")
                if isinstance(country, str) and len(country.strip()) == 2:
                    source_country = country.strip().upper()
            if source_country != "GB":
                continue

            shipping_minor = _shipping_minor(row)
            key = stable_source_record_key(
                "EBAY",
                "ACTIVE",
                item_id,
                price_minor,
                shipping_minor,
            )
            observations[key] = NormalizedMarketObservation(
                source="EBAY",
                source_record_key=key,
                observation_type="ACTIVE",
                observed_at=retrieved_at,
                price_minor=price_minor,
                shipping_minor=shipping_minor,
                currency="GBP",
                price_gbp_minor=price_minor,
                shipping_gbp_minor=shipping_minor,
                fx_rate_to_gbp=1.0,
                catalogue_id=catalogue_id,
                condition=_condition(row),
                grading_company=spec["grading_company"],
                grade=spec["grade"],
                language=spec["language"],
                source_country="GB",
                sample_size=1,
                evidence_quality=0.75,
                metadata={
                    "access_method": "OFFICIAL_EBAY_BROWSE",
                    "provider": "EBAY",
                    "marketplace": self._client.marketplace_id,
                    "endpoint": "GET /buy/browse/v1/item_summary/search",
                    "query": spec["query"],
                    "required_title_terms": spec["required_title_terms"],
                    "forbidden_title_terms": spec["forbidden_title_terms"],
                    "source_variant_id": source_variant_id,
                    "provider_item_id": item_id,
                    "url": row.get("itemWebUrl"),
                    "title": row.get("title"),
                    "buying_options": row.get("buyingOptions"),
                    "sold_history_available": False,
                },
            ).validate()

        return list(observations.values())
