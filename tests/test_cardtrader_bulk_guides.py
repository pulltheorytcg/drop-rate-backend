"""Bulk CardTrader catalogue pricing must not equate lookalike printings."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.cardtrader_bulk_guides import (
    SOURCE, asking_guide, eligible_seller_offers, masters_printings,
    pokemon_printings,
)
from app.fx import FxQuote


def listing(seller, *, price=250, blueprint=111, expansion=30, condition="Near Mint",
            foil=False, graded=False, language="en", quantity=1, signed=False):
    return {
        "id": 10000 + seller, "blueprint_id": blueprint,
        "expansion": {"id": expansion},
        "price": {"cents": price, "currency": "GBP"},
        "user": {"id": seller}, "graded": graded,
        "quantity": quantity, "bundle_size": 1, "on_vacation": False,
        "properties_hash": {"condition": condition, "dragonball_language": language,
                            "dragonball_foil": foil, "signed": signed},
    }


class SameCurrencyFx:
    async def quote(self, *, base_currency, quote_currency, at):
        assert base_currency == quote_currency == "GBP"
        return FxQuote(base_currency="GBP", quote_currency="GBP", rate=Decimal(1),
                       effective_at=at, retrieved_at=at, source="ECB_TEST")


def ref(**overrides):
    value = dict(provider="Bandai Official", system_code="DRAGON_BALL_SUPER_MASTERS",
                 language="English", provider_id="428001:BT1-001.png",
                 name="Son Goku", set_id="428001", set_name="Galactic Battle",
                 card_number="BT1-001", rarity="Common[C]", image_url="https://example.org/image.png",
                 evidence={"detail_level": "OFFICIAL_CHECKLIST", "card_type": "BATTLE"})
    value.update(overrides)
    return value


def test_three_independent_nm_english_raw_sellers_required():
    assert len(eligible_seller_offers([listing(1), listing(2), listing(3)], 111, 30)) == 3
    assert not eligible_seller_offers([listing(1), listing(1), listing(2)], 111, 30)
    assert not eligible_seller_offers([listing(1), listing(2), listing(3, graded=True)], 111, 30)
    assert not eligible_seller_offers([listing(1), listing(2), listing(3, language="jp")], 111, 30)
    assert not eligible_seller_offers([listing(1), listing(2), listing(3, signed=True)], 111, 30)
    assert not eligible_seller_offers([listing(1), listing(2), listing(3, condition="Played")], 111, 30)


def test_foil_and_nonfoil_not_mixed():
    assert not eligible_seller_offers(
        [listing(1), listing(2), listing(3), listing(4, foil=True)], 111, 30)


@pytest.mark.asyncio
async def test_median_asking_guide_labelled_not_sold_and_no_physical_reprice():
    now = datetime.now(timezone.utc)
    quote, amount = await asking_guide(
        ref(), 111, 30, [listing(1, price=220), listing(2, price=245),
                         listing(3, price=260), listing(4, price=290)],
        SameCurrencyFx(), now, {})
    assert amount == 253  # median of 245 and 260, rounded to nearest penny
    assert quote["source"] == SOURCE
    assert quote["observation_type"] == "ACTIVE_ASKING"
    assert quote["sold_comparable"] is False
    assert quote["physical_valuation_eligible"] is False
    assert quote["reference_identity"]["name"] == "Son Goku"
    assert quote["seller_count"] == 4


@pytest.mark.asyncio
async def test_spread_floor_and_distinct_seller_requirements():
    now = datetime.now(timezone.utc)
    for offers in (
        [listing(1, price=100), listing(2, price=200), listing(3, price=400)],
        [listing(1, price=40), listing(2, price=70), listing(3, price=80)],
        [listing(1, price=200), listing(1, price=220), listing(2, price=210)],
    ):
        assert await asking_guide(ref(), 111, 30, offers,
                                  SameCurrencyFx(), now, {}) is None


def test_masters_exact_number_name_rarity_singleton():
    expansion = {"id": 30, "game_id": 13, "code": "BT1", "name": "Galactic Battle"}
    blueprint = {"id": 111, "game_id": 13, "expansion_id": 30, "category_id": 99,
                 "name": "Son Goku", "fixed_properties": {
                     "dragonball_rarity": "Common", "collector_number": "BT1-001"}}
    assert masters_printings([ref()], [blueprint], expansion, {99}) == {
        "428001:BT1-001.png": 111}
    assert not masters_printings([ref()], [blueprint,
        {**blueprint, "id": 112}], expansion, {99})
    assert not masters_printings([ref(rarity="Rare[R]")], [blueprint], expansion, {99})


def test_pokemon_rejects_duplicate_variant_even_if_one_is_unpriced():
    expansion = {"id": 33, "game_id": 5, "name": "Some Pokemon Set"}
    reference = {"provider_id": "ab1-1", "set_id": "ab1", "card_number": "1",
                 "name": "Pikachu", "declared_card_count": 1}
    blueprint = {"id": 111, "game_id": 5, "expansion_id": 33,
                 "category_id": 22, "name": "Pikachu",
                 "fixed_properties": {"collector_number": "1"}}
    assert pokemon_printings([reference], [blueprint], expansion, {22}) == {"ab1-1": 111}
    assert not pokemon_printings([reference], [blueprint, {**blueprint, "id": 112}],
                                 expansion, {22})
