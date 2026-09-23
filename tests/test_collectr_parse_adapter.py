from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.collectr_parse_adapter import CollectrParseAdapter
from app.fx import FxQuote


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"


class FakeParseClient:
    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        assert endpoint == "get_graded_prices"
        assert params["product_id"] == "106999"
        return {
            "name": "Charizard",
            "psa10": [
                {
                    "price": 116992.5,
                    "history": [
                        {"date": "2025-09-07", "price": 47970},
                        {"date": "2025-09-09", "price": 50000},
                    ],
                    "sub_type": "Shadowless Holofoil",
                    "price_date": "2026-09-02",
                },
                {
                    "price": 200000,
                    "history": [{"date": "2025-09-07", "price": 150000}],
                    "sub_type": "1st Edition Holofoil",
                    "price_date": "2026-09-02",
                },
            ],
            "graded": [
                {
                    "grade": "9.5",
                    "price": 11500,
                    "company": "BGS",
                    "sub_type": "Shadowless Holofoil",
                    "grade_name": "Gem Mint",
                    "price_date": "2026-09-02",
                    "grade_label": "9.5",
                },
                {
                    "grade": "10",
                    "price": 300000,
                    "company": "PSA",
                    "sub_type": "1st Edition Holofoil",
                    "grade_name": "Gem Mint",
                    "price_date": "2026-09-02",
                    "grade_label": "10",
                },
            ],
            "rarity": "Holo Rare",
            "set_id": "1663",
            "is_card": True,
            "category": "Pokemon",
            "set_name": "Base Set (1st Edition & Shadowless)",
            "sub_types": ["1st Edition Holofoil", "Shadowless Holofoil"],
            "product_id": "106999",
            "card_number": "4",
            "market_price": 16800,
            "market_price_change": 0,
            "market_price_change_pct": 0,
        }


class SingleSubtypeParseClient:
    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        return {
            "name": "Charizard ex",
            "psa10": [],
            "graded": [],
            "rarity": "Special Illustration Rare",
            "set_id": "23237",
            "is_card": True,
            "category": "Pokemon",
            "set_name": "SV: 151",
            "sub_types": ["Holofoil"],
            "product_id": "106999",
            "card_number": "199/165",
            "market_price": 363.66,
            "market_price_change": -10.25,
            "market_price_change_pct": -2.74,
        }


class FakeFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        assert base_currency == "USD"
        assert quote_currency == "GBP"
        return FxQuote(
            base_currency="USD",
            quote_currency="GBP",
            rate=Decimal("0.75"),
            effective_at=at,
            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
            source="TEST_FX",
        )


class MissingFxProvider:
    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        raise RuntimeError("FX unavailable")


@pytest.mark.asyncio
async def test_multi_subtype_mapping_only_returns_requested_variant() -> None:
    adapter = CollectrParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="106999",
        source_variant_id="Shadowless Holofoil",
    )

    assert observations
    assert all(item.source == "COLLECTR" for item in observations)
    assert all(item.observation_type == "MARKET_AGGREGATE" for item in observations)
    assert all(item.source_country is None for item in observations)
    assert all(item.metadata["market_scope"] == "GLOBAL" for item in observations)
    assert all(item.metadata.get("observed_sub_type") != "1st Edition Holofoil" for item in observations)

    # The product-wide ungraded price is deliberately excluded when the product
    # contains more than one print sub-type.
    assert not any(item.grading_company is None for item in observations)

    psa = [item for item in observations if item.grading_company == "PSA" and item.grade == "10"]
    assert len(psa) == 3
    assert any(item.price_minor == 11699250 for item in psa)
    assert all(item.price_gbp_minor == round(item.price_minor * 0.75) for item in psa)

    bgs = next(item for item in observations if item.grading_company == "BGS")
    assert bgs.grade == "9.5"
    assert bgs.price_minor == 1150000
    assert bgs.metadata["grade_name"] == "Gem Mint"


@pytest.mark.asyncio
async def test_multi_subtype_product_requires_verified_variant() -> None:
    adapter = CollectrParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    with pytest.raises(ValueError, match="requires source_variant_id"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="106999",
            source_variant_id=None,
        )


@pytest.mark.asyncio
async def test_wrong_variant_is_rejected() -> None:
    adapter = CollectrParseAdapter(client=FakeParseClient(), fx_provider=FakeFxProvider())

    with pytest.raises(ValueError, match="does not match"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="106999",
            source_variant_id="Reverse Holofoil",
        )


@pytest.mark.asyncio
async def test_single_subtype_can_use_product_ungraded_market_price() -> None:
    adapter = CollectrParseAdapter(client=SingleSubtypeParseClient(), fx_provider=FakeFxProvider())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id="106999",
        source_variant_id="Holofoil",
    )

    assert len(observations) == 1
    item = observations[0]
    assert item.observation_type == "MARKET_AGGREGATE"
    assert item.grading_company is None
    assert item.price_minor == 36366
    assert item.price_gbp_minor == 27275
    assert item.metadata["price_kind"] == "UNGRADED_CURRENT"
    assert item.metadata["provider_timestamp_absent"] is True
    assert item.metadata["resolved_sub_type"] == "Holofoil"


@pytest.mark.asyncio
async def test_fx_is_required_and_never_guessed() -> None:
    adapter = CollectrParseAdapter(client=SingleSubtypeParseClient(), fx_provider=MissingFxProvider())

    with pytest.raises(RuntimeError, match="FX unavailable"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="106999",
            source_variant_id="Holofoil",
        )


@pytest.mark.asyncio
async def test_rejects_non_numeric_collectr_product_id() -> None:
    adapter = CollectrParseAdapter(client=SingleSubtypeParseClient(), fx_provider=FakeFxProvider())

    with pytest.raises(ValueError, match="must be numeric"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="charizard",
            source_variant_id=None,
        )
