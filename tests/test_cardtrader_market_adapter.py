from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.cardtrader_market_adapter import CardTraderMarketAdapter
from app.fx import FxQuote


class FakeCardTrader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list_marketplace_products(self, *, blueprint_id, language=None, foil=None):
        self.calls.append(
            {
                "blueprint_id": blueprint_id,
                "language": language,
                "foil": foil,
            }
        )
        return list(self.rows)


class FakeFx:
    def __init__(self):
        self.calls = []

    async def quote(self, *, base_currency: str, quote_currency: str, at: datetime) -> FxQuote:
        self.calls.append((base_currency, quote_currency, at))
        rate = {
            "GBP": Decimal("1"),
            "EUR": Decimal("0.86"),
            "USD": Decimal("0.75"),
        }[base_currency]
        return FxQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=rate,
            effective_at=at,
            retrieved_at=datetime.now(timezone.utc),
            source="TEST_FX",
        )


def listing(
    *,
    listing_id=101,
    cents=500,
    currency="EUR",
    bundle_size=1,
    quantity=2,
    on_vacation=False,
    country="JP",
):
    return {
        "id": listing_id,
        "blueprint_id": 7003,
        "quantity": quantity,
        "bundle_size": bundle_size,
        "on_vacation": on_vacation,
        "price": {"cents": cents, "currency": currency},
        "user": {"country_code": country},
    }


@pytest.mark.asyncio
async def test_cardtrader_sealed_pack_normalizes_active_single_unit_listing() -> None:
    client = FakeCardTrader([listing()])
    fx = FakeFx()
    adapter = CardTraderMarketAdapter(client=client, fx_provider=fx)

    rows = await adapter.fetch_observations(
        catalogue_id="catalogue-1",
        source_product_id="7003",
        source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
    )

    assert client.calls == [{"blueprint_id": 7003, "language": "jp", "foil": None}]
    assert len(rows) == 1
    row = rows[0]
    assert row.source == "CARDTRADER"
    assert row.observation_type == "ACTIVE"
    assert row.price_minor == 500
    assert row.currency == "EUR"
    assert row.price_gbp_minor == 430
    assert row.language == "Japanese"
    assert row.seal_status == "SEALED"
    assert row.source_country == "JP"
    assert row.evidence_quality == 0.72
    assert row.metadata["sealed_product_type"] == "BOOSTER_PACK"
    assert row.metadata["bundle_size"] == 1
    assert row.metadata["access_method"] == "OFFICIAL_API"


@pytest.mark.asyncio
async def test_cardtrader_single_pack_mapping_rejects_box_or_multi_pack_bundle() -> None:
    client = FakeCardTrader(
        [
            listing(listing_id=1, bundle_size=24, cents=8000),
            listing(listing_id=2, bundle_size=1, cents=450),
        ]
    )
    adapter = CardTraderMarketAdapter(client=client, fx_provider=FakeFx())

    rows = await adapter.fetch_observations(
        catalogue_id="catalogue-1",
        source_product_id="7003",
        source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
    )

    assert len(rows) == 1
    assert rows[0].price_minor == 450
    assert rows[0].metadata["listing_id"] == "2"


@pytest.mark.asyncio
async def test_cardtrader_skips_vacation_zero_quantity_and_invalid_prices() -> None:
    client = FakeCardTrader(
        [
            listing(listing_id=1, on_vacation=True),
            listing(listing_id=2, quantity=0),
            listing(listing_id=3, cents=0),
            listing(listing_id=4, cents=600, quantity=1),
        ]
    )
    adapter = CardTraderMarketAdapter(client=client, fx_provider=FakeFx())

    rows = await adapter.fetch_observations(
        catalogue_id="catalogue-1",
        source_product_id="7003",
        source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
    )

    assert len(rows) == 1
    assert rows[0].metadata["listing_id"] == "4"


@pytest.mark.asyncio
async def test_cardtrader_observation_key_changes_when_listing_price_changes() -> None:
    first_adapter = CardTraderMarketAdapter(
        client=FakeCardTrader([listing(listing_id=1, cents=500)]),
        fx_provider=FakeFx(),
    )
    second_adapter = CardTraderMarketAdapter(
        client=FakeCardTrader([listing(listing_id=1, cents=550)]),
        fx_provider=FakeFx(),
    )

    first = await first_adapter.fetch_observations(
        catalogue_id="catalogue-1",
        source_product_id="7003",
        source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
    )
    second = await second_adapter.fetch_observations(
        catalogue_id="catalogue-1",
        source_product_id="7003",
        source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
    )

    assert first[0].source_record_key != second[0].source_record_key


@pytest.mark.asyncio
async def test_cardtrader_sealed_mapping_requires_explicit_type_language_and_single_unit() -> None:
    adapter = CardTraderMarketAdapter(client=FakeCardTrader([]), fx_provider=FakeFx())

    with pytest.raises(ValueError, match="TYPE:LANGUAGE:SINGLE_UNIT"):
        await adapter.fetch_observations(
            catalogue_id="catalogue-1",
            source_product_id="7003",
            source_variant_id="JP",
        )

    with pytest.raises(ValueError, match="positive blueprint id"):
        await adapter.fetch_observations(
            catalogue_id="catalogue-1",
            source_product_id="not-an-id",
            source_variant_id="BOOSTER_PACK:JP:SINGLE_UNIT",
        )
