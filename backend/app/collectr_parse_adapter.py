from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP

from .fx import FxQuote, FxRateProvider
from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .parse_client import ParseHttpClient


COLLECTR_PARSE_SCRAPER_ID = "deec24d2-ffc5-41bd-b3fd-99cd817443e2"
COLLECTR_PARSE_SNAPSHOT_VERSION = 1


def _money_minor(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Provider returned an invalid money value") from exc
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _price_date(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Collectr price date is required")
    try:
        day = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Collectr price date is invalid") from exc
    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)


def _to_gbp_minor(usd_minor: int, quote: FxQuote) -> int:
    return int((Decimal(usd_minor) * quote.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _clean_sub_types(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _resolve_sub_type(sub_types: list[str], expected: str | None) -> str | None:
    clean_expected = expected.strip() if isinstance(expected, str) and expected.strip() else None
    if len(sub_types) > 1 and clean_expected is None:
        raise ValueError("Collectr mapping requires source_variant_id for multi-sub-type products")
    if clean_expected is None:
        return sub_types[0] if len(sub_types) == 1 else None

    for sub_type in sub_types:
        if sub_type.casefold() == clean_expected.casefold():
            return sub_type
    if sub_types:
        raise ValueError("Collectr source_variant_id does not match a provider sub-type")
    return clean_expected


def _row_matches_sub_type(row: dict, expected: str | None) -> bool:
    if expected is None:
        return True
    observed = row.get("sub_type")
    return isinstance(observed, str) and observed.strip().casefold() == expected.casefold()


class CollectrParseAdapter:
    """Collectr adapter using the user-approved Parse API.

    Collectr is global/supporting evidence. It never provides an individual sale
    record through this API, so every accepted price is normalised as
    MARKET_AGGREGATE. The UK pricing engine does not use Collectr to set the
    displayed UK Market Value.

    source_product_id is the numeric Collectr product_id. source_variant_id is
    the exact Collectr print sub-type when a product exposes more than one.
    """

    source = "COLLECTR"

    def __init__(self, *, client: ParseHttpClient, fx_provider: FxRateProvider) -> None:
        self._client = client
        self._fx_provider = fx_provider

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        product_id = source_product_id.strip()
        if not product_id.isdigit():
            raise ValueError("Collectr source_product_id must be numeric")

        params: dict[str, object] = {"product_id": product_id}
        if source_variant_id is not None and source_variant_id.strip():
            params["sub_type"] = source_variant_id.strip()

        payload = await self._client.get(
            scraper_id=COLLECTR_PARSE_SCRAPER_ID,
            endpoint="get_graded_prices",
            snapshot_version=COLLECTR_PARSE_SNAPSHOT_VERSION,
            params=params,
        )

        returned_product_id = str(payload.get("product_id") or "").strip()
        if returned_product_id and returned_product_id != product_id:
            raise ValueError("Collectr returned the wrong product")

        sub_types = _clean_sub_types(payload.get("sub_types"))
        resolved_sub_type = _resolve_sub_type(sub_types, source_variant_id)
        is_card = bool(payload.get("is_card", True))
        retrieved_at = datetime.now(timezone.utc)

        fx_cache: dict[str, FxQuote] = {}

        async def fx_for(observed_at: datetime) -> FxQuote:
            key = observed_at.date().isoformat()
            if key not in fx_cache:
                quote = await self._fx_provider.quote(
                    base_currency="USD",
                    quote_currency="GBP",
                    at=observed_at,
                )
                quote.validate()
                if quote.base_currency.upper() != "USD" or quote.quote_currency.upper() != "GBP":
                    raise ValueError("Collectr adapter requires a USD to GBP FX quote")
                fx_cache[key] = quote
            return fx_cache[key]

        observations: dict[str, NormalizedMarketObservation] = {}

        def base_metadata(*, endpoint: str, fx: FxQuote) -> dict[str, object]:
            return {
                "access_method": "PARSE_BOT",
                "provider": "COLLECTR",
                "market_scope": "GLOBAL",
                "scraper_id": COLLECTR_PARSE_SCRAPER_ID,
                "snapshot_version": COLLECTR_PARSE_SNAPSHOT_VERSION,
                "endpoint": endpoint,
                "source_product_id": product_id,
                "source_variant_id": source_variant_id,
                "resolved_sub_type": resolved_sub_type,
                "product_name": payload.get("name"),
                "category": payload.get("category"),
                "set_id": payload.get("set_id"),
                "set_name": payload.get("set_name"),
                "card_number": payload.get("card_number"),
                "rarity": payload.get("rarity"),
                "fx_source": fx.source,
                "fx_effective_at": fx.effective_at.isoformat(),
                "fx_retrieved_at": fx.retrieved_at.isoformat(),
            }

        # Collectr's top-level market_price has no provider timestamp and is not
        # broken down by sub-type. It is safe only when the product is not
        # ambiguous across multiple print sub-types.
        market_price_minor = _money_minor(payload.get("market_price"))
        if market_price_minor is not None and len(sub_types) <= 1:
            fx = await fx_for(retrieved_at)
            key = stable_source_record_key(
                "COLLECTR",
                product_id,
                "MARKET_AGGREGATE",
                "UNGRADED_CURRENT",
                retrieved_at.date().isoformat(),
                market_price_minor,
                resolved_sub_type,
            )
            metadata = base_metadata(endpoint="get_graded_prices", fx=fx)
            metadata.update(
                {
                    "price_kind": "UNGRADED_CURRENT",
                    "provider_timestamp_absent": True,
                    "market_price_change": payload.get("market_price_change"),
                    "market_price_change_pct": payload.get("market_price_change_pct"),
                }
            )
            observations[key] = NormalizedMarketObservation(
                source="COLLECTR",
                source_record_key=key,
                observation_type="MARKET_AGGREGATE",
                observed_at=retrieved_at,
                price_minor=market_price_minor,
                currency="USD",
                price_gbp_minor=_to_gbp_minor(market_price_minor, fx),
                fx_rate_to_gbp=float(fx.rate),
                catalogue_id=catalogue_id,
                source_country=None,
                sample_size=1,
                evidence_quality=0.75,
                metadata=metadata,
            ).validate()

        if not is_card:
            return list(observations.values())

        psa10_rows = payload.get("psa10", [])
        if not isinstance(psa10_rows, list):
            raise ValueError("Collectr psa10 must be an array")

        for row in psa10_rows:
            if not isinstance(row, dict) or not _row_matches_sub_type(row, resolved_sub_type):
                continue
            observed_sub_type = row.get("sub_type") if isinstance(row.get("sub_type"), str) else None

            history = row.get("history", [])
            if not isinstance(history, list):
                raise ValueError("Collectr PSA 10 history must be an array")
            for point in history:
                if not isinstance(point, dict):
                    continue
                price_minor = _money_minor(point.get("price"))
                if price_minor is None:
                    continue
                observed_at = _price_date(point.get("date"))
                fx = await fx_for(observed_at)
                key = stable_source_record_key(
                    "COLLECTR",
                    product_id,
                    "MARKET_AGGREGATE",
                    observed_sub_type,
                    "PSA",
                    "10",
                    observed_at.date().isoformat(),
                    price_minor,
                )
                metadata = base_metadata(endpoint="get_graded_prices", fx=fx)
                metadata.update(
                    {
                        "price_kind": "PSA10_HISTORY",
                        "observed_sub_type": observed_sub_type,
                    }
                )
                observations.setdefault(
                    key,
                    NormalizedMarketObservation(
                        source="COLLECTR",
                        source_record_key=key,
                        observation_type="MARKET_AGGREGATE",
                        observed_at=observed_at,
                        price_minor=price_minor,
                        currency="USD",
                        price_gbp_minor=_to_gbp_minor(price_minor, fx),
                        fx_rate_to_gbp=float(fx.rate),
                        catalogue_id=catalogue_id,
                        grading_company="PSA",
                        grade="10",
                        source_country=None,
                        sample_size=1,
                        evidence_quality=0.80,
                        metadata=metadata,
                    ).validate(),
                )

            current_price_minor = _money_minor(row.get("price"))
            if current_price_minor is not None:
                observed_at = _price_date(row.get("price_date"))
                fx = await fx_for(observed_at)
                key = stable_source_record_key(
                    "COLLECTR",
                    product_id,
                    "MARKET_AGGREGATE",
                    observed_sub_type,
                    "PSA",
                    "10",
                    observed_at.date().isoformat(),
                    current_price_minor,
                )
                metadata = base_metadata(endpoint="get_graded_prices", fx=fx)
                metadata.update(
                    {
                        "price_kind": "PSA10_CURRENT",
                        "observed_sub_type": observed_sub_type,
                    }
                )
                observations.setdefault(
                    key,
                    NormalizedMarketObservation(
                        source="COLLECTR",
                        source_record_key=key,
                        observation_type="MARKET_AGGREGATE",
                        observed_at=observed_at,
                        price_minor=current_price_minor,
                        currency="USD",
                        price_gbp_minor=_to_gbp_minor(current_price_minor, fx),
                        fx_rate_to_gbp=float(fx.rate),
                        catalogue_id=catalogue_id,
                        grading_company="PSA",
                        grade="10",
                        source_country=None,
                        sample_size=1,
                        evidence_quality=0.85,
                        metadata=metadata,
                    ).validate(),
                )

        graded_rows = payload.get("graded", [])
        if not isinstance(graded_rows, list):
            raise ValueError("Collectr graded must be an array")

        for row in graded_rows:
            if not isinstance(row, dict) or not _row_matches_sub_type(row, resolved_sub_type):
                continue
            company = row.get("company") if isinstance(row.get("company"), str) else None
            grade = row.get("grade") if isinstance(row.get("grade"), str) else None
            if not company or not grade:
                continue
            price_minor = _money_minor(row.get("price"))
            if price_minor is None:
                continue
            observed_at = _price_date(row.get("price_date"))
            fx = await fx_for(observed_at)
            observed_sub_type = row.get("sub_type") if isinstance(row.get("sub_type"), str) else None
            key = stable_source_record_key(
                "COLLECTR",
                product_id,
                "MARKET_AGGREGATE",
                observed_sub_type,
                company.upper(),
                grade,
                observed_at.date().isoformat(),
                price_minor,
            )
            metadata = base_metadata(endpoint="get_graded_prices", fx=fx)
            metadata.update(
                {
                    "price_kind": "GRADED_CURRENT",
                    "observed_sub_type": observed_sub_type,
                    "grade_label": row.get("grade_label"),
                    "grade_name": row.get("grade_name"),
                }
            )
            observations.setdefault(
                key,
                NormalizedMarketObservation(
                    source="COLLECTR",
                    source_record_key=key,
                    observation_type="MARKET_AGGREGATE",
                    observed_at=observed_at,
                    price_minor=price_minor,
                    currency="USD",
                    price_gbp_minor=_to_gbp_minor(price_minor, fx),
                    fx_rate_to_gbp=float(fx.rate),
                    catalogue_id=catalogue_id,
                    grading_company=company.upper(),
                    grade=grade,
                    source_country=None,
                    sample_size=1,
                    evidence_quality=0.82,
                    metadata=metadata,
                ).validate(),
            )

        return list(observations.values())
