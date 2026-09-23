from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .parse_client import ParseHttpClient


EBAY_UK_PARSE_SCRAPER_ID = "923c816c-9218-4c32-ae0c-2eac3d514be5"
EBAY_UK_PARSE_SNAPSHOT_VERSION = 10

_MONEY_RE = re.compile(r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
_SPACE_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _normalise_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(_SPACE_RE.sub(" ", value.casefold()).split())


def _parse_mapping_spec(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("eBay source_product_id must be a JSON mapping specification") from exc
    if not isinstance(payload, dict):
        raise ValueError("eBay mapping specification must be an object")

    query = payload.get("query")
    required_terms = payload.get("required_title_terms")
    forbidden_terms = payload.get("forbidden_title_terms", [])

    if not isinstance(query, str) or not query.strip():
        raise ValueError("eBay mapping query is required")
    if not isinstance(required_terms, list) or not required_terms:
        raise ValueError("eBay mapping requires required_title_terms")
    if not all(isinstance(term, str) and term.strip() for term in required_terms):
        raise ValueError("eBay required_title_terms must contain non-empty strings")
    if not isinstance(forbidden_terms, list) or not all(
        isinstance(term, str) and term.strip() for term in forbidden_terms
    ):
        raise ValueError("eBay forbidden_title_terms must contain strings")

    grading_company = payload.get("grading_company")
    grade = payload.get("grade")
    if (grading_company is None) != (grade is None):
        raise ValueError("eBay grading_company and grade must be supplied together")
    if grading_company is not None and (
        not isinstance(grading_company, str)
        or not grading_company.strip()
        or not isinstance(grade, str)
        or not grade.strip()
    ):
        raise ValueError("eBay grading_company and grade must be non-empty strings")

    language = payload.get("language")
    if language is not None and (not isinstance(language, str) or not language.strip()):
        raise ValueError("eBay language must be a non-empty string")

    category_id = payload.get("category_id")
    if category_id is not None and not isinstance(category_id, (str, int)):
        raise ValueError("eBay category_id must be a string or integer")

    include_sold = payload.get("include_sold", True)
    include_active = payload.get("include_active", True)
    if not isinstance(include_sold, bool) or not isinstance(include_active, bool):
        raise ValueError("eBay include_sold/include_active must be booleans")
    if not include_sold and not include_active:
        raise ValueError("eBay mapping must enable sold or active observations")

    return {
        "query": query.strip(),
        "required_title_terms": [term.strip() for term in required_terms],
        "forbidden_title_terms": [term.strip() for term in forbidden_terms],
        "grading_company": grading_company.strip().upper() if grading_company else None,
        "grade": grade.strip() if isinstance(grade, str) else None,
        "language": language.strip() if isinstance(language, str) else None,
        "category_id": str(category_id).strip() if category_id is not None else None,
        "include_sold": include_sold,
        "include_active": include_active,
    }


def _gbp_minor(value: object, *, allow_range: bool = False) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    matches = _MONEY_RE.findall(value)
    if not matches:
        return None
    if len(matches) > 1 and not allow_range:
        return None
    try:
        amount = Decimal(matches[0].replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("eBay returned an invalid GBP price") from exc
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _shipping_minor(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "free" in text.casefold():
        return 0
    return _gbp_minor(text)


def _matches_listing(
    title: object,
    *,
    spec: dict[str, Any],
    source_variant_id: str | None,
) -> bool:
    normalised_title = _normalise_text(title)
    if not normalised_title:
        return False

    required_terms = list(spec["required_title_terms"])
    if source_variant_id is not None and source_variant_id.strip():
        required_terms.append(source_variant_id.strip())
    if spec["grading_company"]:
        required_terms.append(spec["grading_company"])
        required_terms.append(spec["grade"])

    for term in required_terms:
        normalised_term = _normalise_text(term)
        if normalised_term and normalised_term not in normalised_title:
            return False

    for term in spec["forbidden_title_terms"]:
        normalised_term = _normalise_text(term)
        if normalised_term and normalised_term in normalised_title:
            return False

    return True


def _provider_item_id(row: dict[str, Any]) -> str | None:
    value = str(row.get("item_id") or "").strip()
    return value or None


def _metadata(
    *,
    endpoint: str,
    spec: dict[str, Any],
    row: dict[str, Any],
    source_variant_id: str | None,
    provider_timestamp_absent: bool,
) -> dict[str, Any]:
    return {
        "access_method": "PARSE_BOT",
        "provider": "EBAY",
        "marketplace": "EBAY_UK",
        "scraper_id": EBAY_UK_PARSE_SCRAPER_ID,
        "snapshot_version": EBAY_UK_PARSE_SNAPSHOT_VERSION,
        "endpoint": endpoint,
        "query": spec["query"],
        "required_title_terms": spec["required_title_terms"],
        "forbidden_title_terms": spec["forbidden_title_terms"],
        "source_variant_id": source_variant_id,
        "provider_item_id": _provider_item_id(row),
        "url": row.get("url"),
        "title": row.get("title"),
        "provider_timestamp_absent": provider_timestamp_absent,
        "provider_sold_badge": row.get("sold_date"),
    }


class EbayUkParseAdapter:
    """eBay UK adapter using the user-approved Parse API.

    VERIFIED mappings use a strict JSON search identity in source_product_id.
    Search results are accepted only when their titles satisfy every verified
    required term and none of the forbidden terms. This prevents eBay Best Match
    from silently substituting a different card, printing, grade or proxy.

    eBay UK sold/completed results are SOLD evidence. Active search results are
    ACTIVE evidence only; an active result's display badge such as "99+ sold" is
    retained as metadata and never converted into a sold observation.
    """

    source = "EBAY"

    def __init__(self, *, client: ParseHttpClient) -> None:
        self._client = client

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        spec = _parse_mapping_spec(source_product_id)
        retrieved_at = datetime.now(timezone.utc)
        observations: dict[str, NormalizedMarketObservation] = {}

        if spec["include_sold"]:
            if spec["grading_company"] == "PSA":
                sold_query = f"{spec['query']} PSA {spec['grade']}".strip()
                sold_payload = await self._client.get(
                    scraper_id=EBAY_UK_PARSE_SCRAPER_ID,
                    endpoint="search_sold_psa_cards",
                    snapshot_version=EBAY_UK_PARSE_SNAPSHOT_VERSION,
                    params={"card_name": sold_query},
                )
                sold_endpoint = "search_sold_psa_cards"
            else:
                sold_payload = await self._client.get(
                    scraper_id=EBAY_UK_PARSE_SCRAPER_ID,
                    endpoint="search_sold_listings",
                    snapshot_version=EBAY_UK_PARSE_SNAPSHOT_VERSION,
                    params={"query": spec["query"], "page": 1},
                )
                sold_endpoint = "search_sold_listings"

            sold_rows = sold_payload.get("items", [])
            if not isinstance(sold_rows, list):
                raise ValueError("eBay sold items must be an array")

            for row in sold_rows:
                if not isinstance(row, dict):
                    continue
                if not _matches_listing(row.get("title"), spec=spec, source_variant_id=source_variant_id):
                    continue
                price_minor = _gbp_minor(row.get("price"))
                if price_minor is None:
                    continue
                item_id = _provider_item_id(row)
                if item_id is None:
                    key = stable_source_record_key(
                        "EBAY",
                        "SOLD",
                        spec["query"],
                        row.get("title"),
                        price_minor,
                        row.get("url"),
                    )
                else:
                    key = stable_source_record_key("EBAY", "SOLD", item_id)
                shipping_minor = _shipping_minor(row.get("shipping"))
                observations.setdefault(
                    key,
                    NormalizedMarketObservation(
                        source="EBAY",
                        source_record_key=key,
                        observation_type="SOLD",
                        observed_at=retrieved_at,
                        price_minor=price_minor,
                        shipping_minor=shipping_minor,
                        currency="GBP",
                        price_gbp_minor=price_minor,
                        shipping_gbp_minor=shipping_minor,
                        fx_rate_to_gbp=1.0,
                        catalogue_id=catalogue_id,
                        condition=row.get("condition") if isinstance(row.get("condition"), str) else None,
                        grading_company=spec["grading_company"],
                        grade=spec["grade"],
                        language=spec["language"],
                        source_country="GB",
                        sample_size=1,
                        evidence_quality=1.0,
                        metadata=_metadata(
                            endpoint=sold_endpoint,
                            spec=spec,
                            row=row,
                            source_variant_id=source_variant_id,
                            provider_timestamp_absent=True,
                        ),
                    ).validate(),
                )

        if spec["include_active"]:
            params: dict[str, Any] = {"query": spec["query"], "page": 1}
            if spec["category_id"]:
                params["category_id"] = spec["category_id"]
            active_payload = await self._client.get(
                scraper_id=EBAY_UK_PARSE_SCRAPER_ID,
                endpoint="search_listings",
                snapshot_version=EBAY_UK_PARSE_SNAPSHOT_VERSION,
                params=params,
            )
            active_rows = active_payload.get("items", [])
            if not isinstance(active_rows, list):
                raise ValueError("eBay active items must be an array")

            for row in active_rows:
                if not isinstance(row, dict):
                    continue
                if not _matches_listing(row.get("title"), spec=spec, source_variant_id=source_variant_id):
                    continue
                # Range listings represent multiple variants and cannot be safely
                # mapped to one exact physical card, so they are rejected.
                price_minor = _gbp_minor(row.get("price"), allow_range=False)
                if price_minor is None:
                    continue
                item_id = _provider_item_id(row)
                if item_id is None:
                    key = stable_source_record_key(
                        "EBAY",
                        "ACTIVE",
                        spec["query"],
                        row.get("title"),
                        price_minor,
                        row.get("url"),
                    )
                else:
                    key = stable_source_record_key(
                        "EBAY",
                        "ACTIVE",
                        item_id,
                        price_minor,
                        row.get("condition"),
                    )
                shipping_minor = _shipping_minor(row.get("shipping"))
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
                    condition=row.get("condition") if isinstance(row.get("condition"), str) else None,
                    grading_company=spec["grading_company"],
                    grade=spec["grade"],
                    language=spec["language"],
                    source_country="GB",
                    sample_size=1,
                    evidence_quality=0.65,
                    metadata=_metadata(
                        endpoint="search_listings",
                        spec=spec,
                        row=row,
                        source_variant_id=source_variant_id,
                        provider_timestamp_absent=True,
                    ),
                ).validate()

        return list(observations.values())
