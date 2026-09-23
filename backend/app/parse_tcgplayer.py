from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from .market_adapters import NormalizedMarketObservation, stable_source_record_key


PARSE_BASE_URL = "https://api.parse.bot"
TCGPLAYER_SCRAPER_ID = "5d1e8a71-43a6-400a-9f41-6f2a4ad5cbe7"
DEFAULT_SNAPSHOT_VERSION = "14"


def _parse_datetime(value: str | None, *, fallback: datetime | None = None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return fallback or datetime.now(timezone.utc)


def _minor(value: Any) -> int | None:
    if value is None:
        return None
    amount = Decimal(str(value)) * Decimal("100")
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _gbp_minor(value: Any, usd_to_gbp_rate: Decimal) -> int | None:
    if value is None:
        return None
    amount = Decimal(str(value)) * usd_to_gbp_rate * Decimal("100")
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _variant_match(value: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    return (value or "").strip().casefold() == expected.strip().casefold()


def _condition_dimensions(condition: str | None) -> tuple[str | None, str | None]:
    clean = (condition or "").strip()
    if clean.casefold() == "unopened":
        return None, "SEALED"
    return (clean or None), None


def _resolve_variant(rows: list[dict[str, Any]], requested_variant: str | None) -> str | None:
    variants = sorted({str(row.get("variant") or "").strip() for row in rows if str(row.get("variant") or "").strip()})
    if requested_variant:
        if variants and not any(item.casefold() == requested_variant.strip().casefold() for item in variants):
            raise ValueError(f"Mapped TCGPlayer variant {requested_variant!r} is not available; found {variants}")
        return requested_variant.strip()
    if len(variants) > 1:
        raise ValueError(f"TCGPlayer product has multiple variants {variants}; verify the exact source variant before ingestion")
    return variants[0] if variants else None


def normalize_detail_observations(
    payload: dict[str, Any],
    *,
    catalogue_id: str,
    product_id: str,
    requested_variant: str | None,
    usd_to_gbp_rate: Decimal,
    ingested_at: datetime | None = None,
) -> tuple[list[NormalizedMarketObservation], str | None]:
    rows = list(payload.get("pricing_by_condition") or [])
    selected_variant = _resolve_variant(rows, requested_variant)
    fallback_time = ingested_at or datetime.now(timezone.utc)
    observations: list[NormalizedMarketObservation] = []

    for row in rows:
        if selected_variant and not _variant_match(row.get("variant"), selected_variant):
            continue
        market_price = row.get("market_price")
        if market_price is None:
            continue
        observed_at = _parse_datetime(row.get("calculated_at"), fallback=fallback_time)
        condition, seal_status = _condition_dimensions(row.get("condition"))
        usd_minor = _minor(market_price)
        price_gbp_minor = _gbp_minor(market_price, usd_to_gbp_rate)
        if usd_minor is None or price_gbp_minor is None or usd_minor <= 0 or price_gbp_minor <= 0:
            continue
        record_key = stable_source_record_key(
            "TCGPLAYER",
            "MARKET",
            product_id,
            row.get("sku_id"),
            row.get("condition"),
            row.get("variant"),
            row.get("calculated_at") or market_price,
            market_price,
        )
        observations.append(
            NormalizedMarketObservation(
                source="TCGPLAYER",
                source_record_key=record_key,
                observation_type="MARKET_AGGREGATE",
                observed_at=observed_at,
                price_minor=usd_minor,
                currency="USD",
                price_gbp_minor=price_gbp_minor,
                fx_rate_to_gbp=float(usd_to_gbp_rate),
                catalogue_id=catalogue_id,
                condition=condition,
                language=(row.get("language") or "English"),
                seal_status=seal_status,
                source_country="US",
                sample_size=max(1, int(row.get("price_count") or 1)),
                evidence_quality=0.82,
                metadata={
                    "access_method": "PARSE_BOT",
                    "upstream_source": "TCGPLAYER",
                    "product_id": str(product_id),
                    "sku_id": row.get("sku_id"),
                    "variant": row.get("variant"),
                    "lowest_price_usd": row.get("lowest_price"),
                    "highest_price_usd": row.get("highest_price"),
                    "price_count": row.get("price_count"),
                },
            ).validate()
        )
    return observations, selected_variant


def normalize_sales_observations(
    payload: dict[str, Any],
    *,
    catalogue_id: str,
    product_id: str,
    selected_variant: str | None,
    usd_to_gbp_rate: Decimal,
) -> list[NormalizedMarketObservation]:
    observations: list[NormalizedMarketObservation] = []
    for sale in list(payload.get("sales") or []):
        if selected_variant and not _variant_match(sale.get("variant"), selected_variant):
            continue
        price = sale.get("price")
        if price is None:
            continue
        usd_minor = _minor(price)
        price_gbp_minor = _gbp_minor(price, usd_to_gbp_rate)
        if usd_minor is None or price_gbp_minor is None or usd_minor <= 0 or price_gbp_minor <= 0:
            continue
        shipping_minor = _minor(sale.get("shipping_price"))
        shipping_gbp_minor = _gbp_minor(sale.get("shipping_price"), usd_to_gbp_rate)
        observed_at = _parse_datetime(sale.get("date"))
        condition, seal_status = _condition_dimensions(sale.get("condition"))
        record_key = stable_source_record_key(
            "TCGPLAYER",
            "SOLD",
            product_id,
            sale.get("date"),
            sale.get("condition"),
            sale.get("variant"),
            sale.get("language"),
            price,
            sale.get("shipping_price"),
            sale.get("quantity"),
            sale.get("listing_title"),
        )
        observations.append(
            NormalizedMarketObservation(
                source="TCGPLAYER",
                source_record_key=record_key,
                observation_type="SOLD",
                observed_at=observed_at,
                price_minor=usd_minor,
                shipping_minor=shipping_minor,
                currency="USD",
                price_gbp_minor=price_gbp_minor,
                shipping_gbp_minor=shipping_gbp_minor,
                fx_rate_to_gbp=float(usd_to_gbp_rate),
                catalogue_id=catalogue_id,
                condition=condition,
                language=(sale.get("language") or "English"),
                seal_status=seal_status,
                source_country="US",
                sample_size=max(1, int(sale.get("quantity") or 1)),
                evidence_quality=0.95,
                metadata={
                    "access_method": "PARSE_BOT",
                    "upstream_source": "TCGPLAYER",
                    "product_id": str(product_id),
                    "variant": sale.get("variant"),
                    "listing_type": sale.get("listing_type"),
                    "listing_title": sale.get("listing_title"),
                },
            ).validate()
        )
    return observations


class TCGPlayerParseAdapter:
    source = "TCGPLAYER"

    def __init__(
        self,
        *,
        api_key: str,
        usd_to_gbp_rate: Decimal,
        snapshot_version: str = DEFAULT_SNAPSHOT_VERSION,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Parse API key is required")
        if usd_to_gbp_rate <= 0:
            raise ValueError("USD to GBP rate must be positive")
        self.api_key = api_key.strip()
        self.usd_to_gbp_rate = usd_to_gbp_rate
        self.snapshot_version = snapshot_version.strip() or DEFAULT_SNAPSHOT_VERSION
        self.timeout_seconds = timeout_seconds

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "API-Snapshot-Version": self.snapshot_version,
        }

    async def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{PARSE_BASE_URL}/scraper/{TCGPLAYER_SCRAPER_ID}/{endpoint}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, headers=self._headers, params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            raise RuntimeError("Parse TCGPlayer endpoint returned an invalid payload")
        return payload["data"]

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        details = await self._get("get_card_details", {"product_id": str(source_product_id)})
        if str(details.get("product_id")) != str(source_product_id):
            raise ValueError("TCGPlayer product ID mismatch")

        aggregate_observations, selected_variant = normalize_detail_observations(
            details,
            catalogue_id=catalogue_id,
            product_id=str(source_product_id),
            requested_variant=source_variant_id,
            usd_to_gbp_rate=self.usd_to_gbp_rate,
        )
        sales = await self._get(
            "get_latest_sales",
            {"product_id": str(source_product_id), "limit": "5"},
        )
        if str(sales.get("product_id")) != str(source_product_id):
            raise ValueError("TCGPlayer sales product ID mismatch")
        sold_observations = normalize_sales_observations(
            sales,
            catalogue_id=catalogue_id,
            product_id=str(source_product_id),
            selected_variant=selected_variant,
            usd_to_gbp_rate=self.usd_to_gbp_rate,
        )
        return [*sold_observations, *aggregate_observations]
