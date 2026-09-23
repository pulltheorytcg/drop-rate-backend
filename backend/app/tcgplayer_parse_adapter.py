from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .parse_client import ParseHttpClient


TCGPLAYER_PARSE_SCRAPER_ID = "5d1e8a71-43a6-400a-9f41-6f2a4ad5cbe7"
TCGPLAYER_PARSE_SNAPSHOT_VERSION = 14


@dataclass(frozen=True, slots=True)
class FxQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_at: datetime
    retrieved_at: datetime
    source: str

    def validate(self) -> "FxQuote":
        if self.base_currency.upper() != "USD" or self.quote_currency.upper() != "GBP":
            raise ValueError("TCGPlayer adapter requires a USD to GBP FX quote")
        if self.rate <= 0:
            raise ValueError("FX rate must be positive")
        if self.effective_at.tzinfo is None or self.retrieved_at.tzinfo is None:
            raise ValueError("FX timestamps must be timezone-aware")
        if not self.source.strip():
            raise ValueError("FX source is required")
        return self


class FxRateProvider(Protocol):
    async def quote(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> FxQuote:
        """Return an auditable FX quote for the requested observation time."""
        ...


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provider timestamp is required")
    clean = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(clean)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _money_minor(value: object) -> int | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Provider returned an invalid money value") from exc
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_gbp_minor(usd_minor: int, quote: FxQuote) -> int:
    return int((Decimal(usd_minor) * quote.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _variant_matches(observed: object, expected: str | None) -> bool:
    if expected is None or not expected.strip():
        return True
    if not isinstance(observed, str):
        return False
    return observed.strip().casefold() == expected.strip().casefold()


class TcgplayerParseAdapter:
    """TCGPlayer market adapter using the user-approved Parse API.

    TCGPlayer is US-market supporting evidence only. Every observation is tagged
    source_country='US'. The UK pricing engine excludes it from the displayed
    Market Value and uses it only for confidence/trend/discrepancy analysis.

    No USD value is normalized without a real auditable FX quote.
    """

    source = "TCGPLAYER"

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
            raise ValueError("TCGPlayer source_product_id must be numeric")

        sales = await self._client.get(
            scraper_id=TCGPLAYER_PARSE_SCRAPER_ID,
            endpoint="get_latest_sales",
            snapshot_version=TCGPLAYER_PARSE_SNAPSHOT_VERSION,
            params={"product_id": product_id, "limit": 10},
        )
        details = await self._client.get(
            scraper_id=TCGPLAYER_PARSE_SCRAPER_ID,
            endpoint="get_card_details",
            snapshot_version=TCGPLAYER_PARSE_SNAPSHOT_VERSION,
            params={"product_id": product_id},
        )

        observations: list[NormalizedMarketObservation] = []
        fx_cache: dict[str, FxQuote] = {}

        async def fx_for(observed_at: datetime) -> FxQuote:
            key = observed_at.date().isoformat()
            if key not in fx_cache:
                quote = await self._fx_provider.quote(
                    base_currency="USD",
                    quote_currency="GBP",
                    at=observed_at,
                )
                fx_cache[key] = quote.validate()
            return fx_cache[key]

        for sale in sales.get("sales", []):
            if not isinstance(sale, dict):
                continue
            if not _variant_matches(sale.get("variant"), source_variant_id):
                continue
            price_minor = _money_minor(sale.get("price"))
            if price_minor is None:
                continue
            observed_at = _parse_datetime(sale.get("date"))
            fx = await fx_for(observed_at)
            shipping_minor = _money_minor(sale.get("shipping_price"))
            quantity = max(1, int(sale.get("quantity") or 1))
            condition = sale.get("condition") if isinstance(sale.get("condition"), str) else None
            variant = sale.get("variant") if isinstance(sale.get("variant"), str) else None
            language = sale.get("language") if isinstance(sale.get("language"), str) else "English"
            title = sale.get("listing_title") if isinstance(sale.get("listing_title"), str) else None
            listing_type = sale.get("listing_type") if isinstance(sale.get("listing_type"), str) else None

            key = stable_source_record_key(
                "TCGPLAYER",
                product_id,
                "SOLD",
                observed_at.isoformat(),
                price_minor,
                shipping_minor,
                condition,
                variant,
                language,
                quantity,
                title,
                listing_type,
            )
            observations.append(
                NormalizedMarketObservation(
                    source="TCGPLAYER",
                    source_record_key=key,
                    observation_type="SOLD",
                    observed_at=observed_at,
                    price_minor=price_minor,
                    currency="USD",
                    price_gbp_minor=_to_gbp_minor(price_minor, fx),
                    fx_rate_to_gbp=float(fx.rate),
                    catalogue_id=catalogue_id,
                    shipping_minor=shipping_minor,
                    shipping_gbp_minor=_to_gbp_minor(shipping_minor, fx) if shipping_minor else None,
                    condition=condition,
                    language=language,
                    source_country="US",
                    sample_size=quantity,
                    evidence_quality=1.0,
                    metadata={
                        "access_method": "PARSE_BOT",
                        "provider": "TCGPLAYER",
                        "scraper_id": TCGPLAYER_PARSE_SCRAPER_ID,
                        "snapshot_version": TCGPLAYER_PARSE_SNAPSHOT_VERSION,
                        "endpoint": "get_latest_sales",
                        "source_product_id": product_id,
                        "source_variant_id": source_variant_id,
                        "observed_variant": variant,
                        "listing_title": title,
                        "listing_type": listing_type,
                        "fx_source": fx.source,
                        "fx_effective_at": fx.effective_at.isoformat(),
                        "fx_retrieved_at": fx.retrieved_at.isoformat(),
                    },
                ).validate()
            )

        pricing_rows = details.get("pricing_by_condition", [])
        if not isinstance(pricing_rows, list):
            pricing_rows = []
        for row in pricing_rows:
            if not isinstance(row, dict):
                continue
            if not _variant_matches(row.get("variant"), source_variant_id):
                continue
            price_minor = _money_minor(row.get("market_price"))
            if price_minor is None:
                continue
            observed_at = _parse_datetime(row.get("calculated_at"))
            fx = await fx_for(observed_at)
            condition = row.get("condition") if isinstance(row.get("condition"), str) else None
            variant = row.get("variant") if isinstance(row.get("variant"), str) else None
            language = row.get("language") if isinstance(row.get("language"), str) else "English"
            sample_size = max(1, int(row.get("price_count") or 1))
            sku_id = row.get("sku_id")

            key = stable_source_record_key(
                "TCGPLAYER",
                product_id,
                "MARKET_AGGREGATE",
                sku_id,
                observed_at.isoformat(),
                price_minor,
                condition,
                variant,
                language,
            )
            observations.append(
                NormalizedMarketObservation(
                    source="TCGPLAYER",
                    source_record_key=key,
                    observation_type="MARKET_AGGREGATE",
                    observed_at=observed_at,
                    price_minor=price_minor,
                    currency="USD",
                    price_gbp_minor=_to_gbp_minor(price_minor, fx),
                    fx_rate_to_gbp=float(fx.rate),
                    catalogue_id=catalogue_id,
                    condition=condition,
                    language=language,
                    source_country="US",
                    sample_size=sample_size,
                    evidence_quality=0.85,
                    metadata={
                        "access_method": "PARSE_BOT",
                        "provider": "TCGPLAYER",
                        "scraper_id": TCGPLAYER_PARSE_SCRAPER_ID,
                        "snapshot_version": TCGPLAYER_PARSE_SNAPSHOT_VERSION,
                        "endpoint": "get_card_details",
                        "source_product_id": product_id,
                        "source_variant_id": source_variant_id,
                        "sku_id": sku_id,
                        "observed_variant": variant,
                        "fx_source": fx.source,
                        "fx_effective_at": fx.effective_at.isoformat(),
                        "fx_retrieved_at": fx.retrieved_at.isoformat(),
                    },
                ).validate()
            )

        return observations
