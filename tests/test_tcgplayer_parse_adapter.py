from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.tcgplayer_parse_adapter import FxQuote, TcgplayerParseAdapter


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"


class FakeParseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        self.calls.append((endpoint, params))
        if endpoint == "get_latest_sales":
            return {
                "sales": [
                    {
                        "date": "2026-09-11T23:13:09.527+00:00",
                        "price": 180,
                        "variant": "Holofoil",
                        "language": "English",
                        "quantity": 1,
                        "condition": "Near Mint",
                        "listing_type": "ListingWithoutPhotos",
                        "listing_title": "Charizard",
                        "shipping_price": 1.49,
                    }
                ]
            }
        if endpoint == "get_card_details":
            return {
                "pricing_by_condition": [
                    {
                        "sku_id": 2999652,
                        "variant": "Holofoil",
                        "language": "English",
                        "condition": "Near Mint",
                        "price_count": 13,
                        "market_price": 882.02,
                        "calculated_at": "2026-09-10T20:26:18.801Z",
                    },
                    {
                        "sku_id": 999,
                        "variant": "Reverse Holofoil",
                        "language": "English",
                        "condition": "Near Mint",
                        "price_count": 7,
                        "market_price": 50,
                        "calculated_at": "2026-09-10T20:26:18.801Z",
                    },
                ]
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakeFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        return FxQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=Decimal("0.75"),
            effective_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            source="TEST_FX",
        )


class MissingFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        raise RuntimeError("FX unavailable")


@pytest.mark.asyncio
async def test_normalizes_us_sales_and_condition_aggregate() -> None:
    adapter = TcgplayerParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="42382",
        source_variant_id="Holofoil",
    )

    assert len(observations) == 2

    sold = next(item for item in observations if item.observation_type == "SOLD")
    aggregate = next(item for item in observations if item.observation_type == "MARKET_AGGREGATE")

    assert sold.source == "TCGPLAYER"
    assert sold.source_country == "US"
    assert sold.currency == "USD"
    assert sold.price_minor == 18000
    assert sold.price_gbp_minor == 13500
    assert sold.shipping_minor == 149
    assert sold.condition == "Near Mint"
    assert sold.language == "English"
    assert sold.metadata["observed_variant"] == "Holofoil"
    assert sold.metadata["access_method"] == "PARSE_BOT"
    assert sold.metadata["fx_source"] == "TEST_FX"

    assert aggregate.source_country == "US"
    assert aggregate.price_minor == 88202
    assert aggregate.price_gbp_minor == 66152
    assert aggregate.sample_size == 13
    assert aggregate.metadata["sku_id"] == 2999652
    assert aggregate.metadata["observed_variant"] == "Holofoil"


@pytest.mark.asyncio
async def test_variant_filter_excludes_other_printings() -> None:
    adapter = TcgplayerParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="42382",
        source_variant_id="Holofoil",
    )

    assert all(item.metadata.get("observed_variant") == "Holofoil" for item in observations)


@pytest.mark.asyncio
async def test_source_record_keys_are_stable() -> None:
    adapter = TcgplayerParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    first = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="42382",
        source_variant_id="Holofoil",
    )
    second = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="42382",
        source_variant_id="Holofoil",
    )

    assert [item.source_record_key for item in first] == [item.source_record_key for item in second]


@pytest.mark.asyncio
async def test_fx_is_required_and_never_guessed() -> None:
    adapter = TcgplayerParseAdapter(client=FakeParseClient(), fx_provider=MissingFxProvider())

    with pytest.raises(RuntimeError, match="FX unavailable"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="42382",
            source_variant_id="Holofoil",
        )


@pytest.mark.asyncio
async def test_rejects_non_numeric_tcgplayer_product_id() -> None:
    adapter = TcgplayerParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    with pytest.raises(ValueError, match="must be numeric"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="not-a-product-id",
            source_variant_id=None,
        )
