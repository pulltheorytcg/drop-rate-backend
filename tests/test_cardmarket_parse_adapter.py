from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.cardmarket_parse_adapter import CardmarketParseAdapter
from app.fx import FxQuote


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"
CARDMARKET_URL = (
    "https://www.cardmarket.com/en/Pokemon/Products/Singles/"
    "Base-Set/Charizard-V1-BS4"
)


class FakeParseClient:
    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        assert params["game"] == "Pokemon"
        assert params["expansion"] == "Base-Set"
        assert params["card"] == "Charizard-V1-BS4"

        if endpoint == "get_price_history":
            return {
                "game": "Pokemon",
                "expansion": "Base-Set",
                "card": "Charizard-V1-BS4",
                "price_history": [
                    {
                        "label": "30 days",
                        "period": "30-day",
                        "data_points": [
                            {"date": "21.09.2026", "price": 100.00},
                            {"date": "22.09.2026", "price": 110.00},
                        ],
                    },
                    {
                        "label": "recent",
                        "period": "14-day",
                        "data_points": [
                            {"date": "22.09.2026", "price": 110.00},
                        ],
                    },
                ],
            }

        if endpoint == "get_card_listings":
            return {
                "game": "Pokemon",
                "expansion": "Base-Set",
                "card": "Charizard-V1-BS4",
                "page": 1,
                "retrievable_limit": 300,
                "listings": [
                    {
                        "listing_id": "123456789",
                        "price_eur": 125.50,
                        "condition": "NM",
                        "quantity": "2",
                        "attributes": ["English", "Holo"],
                        "seller": {
                            "name": "ExampleSeller",
                            "country": "Item location: Germany",
                        },
                    }
                ],
            }

        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakeFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        assert base_currency == "EUR"
        assert quote_currency == "GBP"
        return FxQuote(
            base_currency="EUR",
            quote_currency="GBP",
            rate=Decimal("0.85"),
            effective_at=at,
            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
            source="TEST_ECB",
        )


class MissingFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        raise RuntimeError("FX unavailable")


@pytest.mark.asyncio
async def test_normalizes_history_as_aggregate_and_current_offers_as_active() -> None:
    adapter = CardmarketParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=CARDMARKET_URL,
        source_variant_id="Holo",
    )

    assert len(observations) == 3
    aggregates = [item for item in observations if item.observation_type == "MARKET_AGGREGATE"]
    active = next(item for item in observations if item.observation_type == "ACTIVE")

    assert len(aggregates) == 2
    assert all(item.source == "CARDMARKET" for item in observations)
    assert all(item.currency == "EUR" for item in observations)
    assert all(item.source_country == "EU" for item in observations)
    assert all(item.observation_type != "SOLD" for item in observations)

    day_two = next(item for item in aggregates if item.price_minor == 11000)
    assert day_two.price_gbp_minor == 9350
    assert day_two.condition is None
    assert day_two.language is None
    assert day_two.metadata["statistic"] == "DAILY_AVERAGE_SELL_PRICE"
    assert day_two.metadata["card_wide_statistic"] is True
    assert day_two.metadata["language_condition_breakdown_available"] is False

    assert active.price_minor == 12550
    assert active.price_gbp_minor == 10668
    assert active.condition == "NM"
    assert active.language == "English"
    assert active.metadata["listing_id"] == "123456789"
    assert active.metadata["listing_quantity"] == 2
    assert active.metadata["access_method"] == "PARSE_BOT"
    assert active.metadata["fx_source"] == "TEST_ECB"


@pytest.mark.asyncio
async def test_duplicate_history_points_across_chart_periods_are_deduped() -> None:
    adapter = CardmarketParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=CARDMARKET_URL,
        source_variant_id=None,
    )

    aggregates = [item for item in observations if item.observation_type == "MARKET_AGGREGATE"]
    assert len(aggregates) == 2
    assert len({item.source_record_key for item in aggregates}) == 2


@pytest.mark.asyncio
async def test_fx_is_required_and_never_guessed() -> None:
    adapter = CardmarketParseAdapter(client=FakeParseClient(), fx_provider=MissingFxProvider())

    with pytest.raises(RuntimeError, match="FX unavailable"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id=CARDMARKET_URL,
            source_variant_id=None,
        )


@pytest.mark.asyncio
async def test_rejects_non_canonical_or_ambiguous_product_identifier() -> None:
    adapter = CardmarketParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    with pytest.raises(ValueError, match="canonical HTTPS Cardmarket URL"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="Charizard Base Set 4/102",
            source_variant_id=None,
        )

    with pytest.raises(ValueError, match="one exact Singles product"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="https://www.cardmarket.com/en/Pokemon/Products/Singles/Base-Set",
            source_variant_id=None,
        )
