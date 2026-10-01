from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .cardtrader_client import CardTraderClient
from .fx import FxQuote, FxRateProvider
from .market_adapters import NormalizedMarketObservation, stable_source_record_key


_VARIANT_LANGUAGE = {
    "EN": "English",
    "JP": "Japanese",
    "ZH-CN": "Chinese",
    "ZH-TW": "Chinese",
    "KR": "Korean",
    "FR": "French",
    "DE": "German",
    "IT": "Italian",
    "ES": "Spanish",
    "PT": "Portuguese",
}
_SUPPORTED_SEALED_TYPES = {
    "BOOSTER_PACK",
    "BOOSTER_BOX",
    "STARTER_DECK",
    "COLLECTION",
    "TIN",
    "CASE",
}


def _parse_blueprint_id(value: str) -> int:
    clean = value.strip()
    if not clean.isdigit() or int(clean) <= 0:
        raise ValueError("CardTrader source_product_id must be a positive blueprint id")
    return int(clean)


def _parse_variant(value: str | None) -> tuple[str, str]:
    clean = str(value or "").strip().upper()
    parts = [part.strip() for part in clean.split(":") if part.strip()]
    if len(parts) != 3 or parts[2] != "SINGLE_UNIT":
        raise ValueError(
            "CardTrader sealed mapping source_variant_id must be TYPE:LANGUAGE:SINGLE_UNIT"
        )
    sealed_type, language_code, _unit = parts
    if sealed_type not in _SUPPORTED_SEALED_TYPES:
        raise ValueError("CardTrader sealed mapping has an unsupported sealed product type")
    if language_code not in _VARIANT_LANGUAGE:
        raise ValueError("CardTrader sealed mapping has an unsupported language")
    return sealed_type, language_code


def _price(row: dict[str, Any]) -> tuple[int, str] | None:
    price = row.get("price")
    if not isinstance(price, dict):
        return None
    cents = price.get("cents")
    currency = str(price.get("currency") or "").strip().upper()
    if isinstance(cents, bool):
        return None
    try:
        minor = int(cents)
    except (TypeError, ValueError):
        return None
    if minor <= 0 or len(currency) != 3:
        return None
    return minor, currency


def _bundle_size(row: dict[str, Any]) -> int | None:
    raw = row.get("bundle_size")
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _quantity(row: dict[str, Any]) -> int:
    raw = row.get("quantity")
    if isinstance(raw, bool):
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _seller(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("user", "seller"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _on_vacation(row: dict[str, Any]) -> bool:
    value = row.get("on_vacation")
    if value is None:
        value = _seller(row).get("on_vacation")
    return value is True


def _seller_country(row: dict[str, Any]) -> str | None:
    seller = _seller(row)
    for value in (
        seller.get("country_code"),
        seller.get("country"),
        row.get("seller_country"),
    ):
        clean = str(value or "").strip().upper()
        if len(clean) == 2:
            return clean
    return None


def _listing_id(row: dict[str, Any]) -> str | None:
    clean = str(row.get("id") or "").strip()
    return clean or None


def _to_gbp_minor(price_minor: int, quote: FxQuote) -> int:
    return int(
        (Decimal(price_minor) * quote.rate).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


class CardTraderMarketAdapter:
    """Official CardTrader active-listing adapter for exact mapped sealed products.

    A verified mapping pins one CardTrader blueprint id plus an explicit physical
    product type/language/unit contract, e.g. BOOSTER_PACK:JP:SINGLE_UNIT.
    Only bundle_size=1 listings are accepted for a single-unit mapping, so booster
    boxes and multi-pack bundles cannot leak into a single-pack valuation.
    """

    source = "CARDTRADER"

    def __init__(
        self,
        *,
        client: CardTraderClient,
        fx_provider: FxRateProvider,
    ) -> None:
        self._client = client
        self._fx_provider = fx_provider

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        blueprint_id = _parse_blueprint_id(source_product_id)
        sealed_type, language_code = _parse_variant(source_variant_id)
        language = _VARIANT_LANGUAGE[language_code]

        rows = await self._client.list_marketplace_products(
            blueprint_id=blueprint_id,
            language=language_code.lower(),
        )
        observed_at = datetime.now(timezone.utc)
        fx_cache: dict[str, FxQuote] = {}

        async def quote_for(currency: str) -> FxQuote:
            if currency not in fx_cache:
                quote = await self._fx_provider.quote(
                    base_currency=currency,
                    quote_currency="GBP",
                    at=observed_at,
                )
                quote.validate()
                if quote.base_currency.upper() != currency or quote.quote_currency.upper() != "GBP":
                    raise ValueError("CardTrader adapter received the wrong FX quote")
                fx_cache[currency] = quote
            return fx_cache[currency]

        output: dict[str, NormalizedMarketObservation] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _on_vacation(row) or _quantity(row) < 1:
                continue
            # Fail closed for single-unit sealed mappings. CardTrader exposes
            # bundle_size so a box/multipack cannot be treated as one booster.
            if _bundle_size(row) != 1:
                continue

            parsed_price = _price(row)
            if parsed_price is None:
                continue
            price_minor, currency = parsed_price
            quote = await quote_for(currency)
            price_gbp_minor = _to_gbp_minor(price_minor, quote)
            if price_gbp_minor <= 0:
                continue

            listing_id = _listing_id(row)
            if listing_id is None:
                continue
            seller_country = _seller_country(row)
            source_key = stable_source_record_key(
                "CARDTRADER",
                blueprint_id,
                listing_id,
                observed_at.date().isoformat(),
                price_minor,
                currency,
                1,
            )
            output[source_key] = NormalizedMarketObservation(
                source="CARDTRADER",
                source_record_key=source_key,
                observation_type="ACTIVE",
                observed_at=observed_at,
                price_minor=price_minor,
                currency=currency,
                price_gbp_minor=price_gbp_minor,
                fx_rate_to_gbp=float(quote.rate),
                catalogue_id=catalogue_id,
                condition=None,
                language=language,
                seal_status="SEALED",
                source_country=seller_country,
                sample_size=1,
                evidence_quality=0.72,
                metadata={
                    "access_method": "OFFICIAL_API",
                    "provider": "CARDTRADER",
                    "endpoint": "/marketplace/products",
                    "blueprint_id": blueprint_id,
                    "source_variant_id": source_variant_id,
                    "sealed_product_type": sealed_type,
                    "physical_language": language,
                    "provider_language_filter": language_code.lower(),
                    "listing_id": listing_id,
                    "quantity": _quantity(row),
                    "bundle_size": 1,
                    "seller_country": seller_country,
                    "fx_source": quote.source,
                    "fx_effective_at": quote.effective_at.isoformat(),
                    "fx_retrieved_at": quote.retrieved_at.isoformat(),
                },
            ).validate()

        return list(output.values())
