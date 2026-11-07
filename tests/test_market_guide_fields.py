"""Free, official-bulk Cardmarket 30-day fallbacks: never invent sold prices."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.market_guide_fields import choose_bulk_price_field
from app import dragon_ball_market as dragon
from app import one_piece_market as one_piece
from app import pokemon_catalogue_market as pokemon

NOW = datetime(2026, 10, 15, 2, tzinfo=timezone.utc)
FX = SimpleNamespace(rate=Decimal("0.8"), source="ECB_EURO_REFERENCE_RATES",
                     effective_at=NOW-timedelta(hours=6), retrieved_at=NOW)


@pytest.mark.parametrize("raw", [None, 0, 0.0, "0", "0.00"])
def test_missing_trend_uses_only_positive_30_day_average(raw):
    assert choose_bulk_price_field({"trend": raw, "avg30": "2.50"}, "trend") == (250, "avg30")


@pytest.mark.parametrize("raw", [True, False, -1, "-2.0", "nan", float("inf"),
                                "invalid", [], {}, "99999999", "0.001"])
def test_malformed_present_trend_never_bypasses_safety_through_avg30(raw):
    assert choose_bulk_price_field({"trend": raw, "avg30": 2.50}, "trend") is None


@pytest.mark.parametrize("value", [None, 0, -1, True, "NaN", "invalid", 1e9])
def test_missing_or_invalid_fallback_remains_unpriced(value):
    assert choose_bulk_price_field({"trend": None, "avg30": value}, "trend") is None


def test_current_trend_always_has_precedence_and_other_columns_never_qualify():
    assert choose_bulk_price_field({"trend": 2.10, "avg30": 40}, "trend") == (210, "trend")
    assert choose_bulk_price_field({"trend": None, "low": .02, "available": 100}, "trend") is None
    assert choose_bulk_price_field({"trend": None, "avg30": 5}, "low") is None
    assert choose_bulk_price_field({}, "trend-holo") is None
    assert choose_bulk_price_field({"trend-foil": 0, "avg30-foil": 3.50}, "trend-foil") == (350, "avg30-foil")


def test_dragon_ball_official_cardmarket_base_and_foil_fallback_are_nonpublishing():
    ref = {"provider": "Bandai Official", "system_code": dragon.MASTERS,
           "language": "English", "provider_id": "428013:BT13-029.png",
           "set_id": "428013", "name": "A Sudden Escape", "card_number": "BT13-029",
           "rarity": "Common[C]", "set_name": "UW04 Booster -Supreme Rivalry-"}
    product = {"idProduct": 549841, "name": "A Sudden Escape", "idExpansion": 3796,
               "idCategory": 1049, "categoryName": "Dragon Ball Super Singles"}
    price = {"idProduct": 549841, "idCategory": 1049, "trend": None,
             "avg30": .25, "trend-foil": 0, "avg30-foil": 2.5}
    quotes = dragon.guide_quotes(ref, product, price, NOW, FX)
    assert [(q["finish"], q["source_field"], q["price_gbp_minor"])
            for q in quotes] == [("Normal", "avg30", 20), ("Holofoil", "avg30-foil", 200)]
    assert all(q["guide_window_days"] == 30 and q["physical_valuation_eligible"] is False
               and q["valuation_role"] == "MIXED_LANGUAGE_REFERENCE" for q in quotes)
    assert all(q["reference_identity"]["card_number"] == "BT13-029" for q in quotes)
    assert all(q["fx_source"] == "ECB_EURO_REFERENCE_RATES" for q in quotes)
    assert dragon.guide_quotes(ref, product, {**price, "trend": -1}, NOW, FX) == [quotes[1]]


def test_pokemon_only_uses_existing_exact_identity_and_no_foil_guess():
    ref = {"provider": "TCGdex", "system_code": "POKEMON_TCG",
           "language": "English", "provider_id": "sv01-001", "set_id": "sv01",
           "set_name": "Scarlet & Violet", "name": "Pineco", "card_number": "001/198"}
    product = {"idProduct": 123, "idExpansion": 5223, "idCategory": 51,
               "categoryName": "Pokémon Single"}
    price = {"idProduct": 123, "idCategory": 51, "trend": None,
             "avg30": .50, "trend-holo": None, "avg30-foil": 99}
    quotes = pokemon.quotes_for(ref, product, price, NOW, FX)
    assert len(quotes) == 1 and quotes[0]["source_field"] == "avg30"
    assert quotes[0]["price_gbp_minor"] == 40
    assert quotes[0]["guide_window_days"] == 30
    assert quotes[0]["physical_valuation_eligible"] is False
    assert quotes[0]["reference_identity"] == {
        key: ref[key] for key in ("name", "set_id", "card_number", "set_name")
    }
    assert pokemon.quotes_for(ref, product, {**price, "idCategory": 52}, NOW, FX) == []


@pytest.mark.asyncio
async def test_one_piece_bulk_fallback_only_after_strict_release_match(monkeypatch):
    ref = {"provider": "Punk Records", "system_code": "ONE_PIECE_CARD_GAME",
           "language": "English", "provider_id": "OP01-001", "set_id": "569101",
           "set_name": "BOOSTER PACK -ROMANCE DAWN- [OP-01]",
           "card_number": "OP01-001", "name": "Roronoa Zoro", "rarity": "L"}
    single = {"idProduct": 901, "name": "Roronoa Zoro (OP01-001)",
              "idCategory": 1621, "categoryName": "One Piece Single",
              "idExpansion": 777}
    package = {"idProduct": 902, "categoryName": "One Piece Lots",
               "name": "Common Set - Romance Dawn (OP01)", "idExpansion": 777}
    prices = {"901": {"idProduct": 901, "idCategory": 1621,
                      "trend": None, "avg30": 6.50}}
    writes = []
    async def download(client, path, **kwargs):
        if "nonsingles" in path:
            return {"902": package}, NOW
        if "singles" in path:
            return {"901": single}, NOW
        return prices, NOW
    class Conn:
        async def fetch(self, sql):
            assert "tcg.inventory_items" not in sql
            return [ref]
        async def executemany(self, sql, values):
            assert "tcg.inventory_items" not in sql
            writes.extend(values)
    @asynccontextmanager
    async def connection(*args):
        yield Conn()
    class Fx:
        async def quote(self, **kwargs):
            return FX
    monkeypatch.setattr(one_piece, "download", download)
    monkeypatch.setattr(one_piece, "user_connection", connection)
    report = await one_piece.refresh_one_piece_prices(object(), uuid4(), Fx())
    assert report["provider_failures"] == 0
    assert report["checked"] == report["matched"] == report["priced"] == 1
    quote = writes[0][4][0]
    assert quote["source_field"] == "avg30"
    assert quote["guide_window_days"] == 30
    assert quote["physical_valuation_eligible"] is False
    assert quote["reference_printing_id"] == "OP01-001"
    assert quote["original_minor"] == 650 and quote["price_gbp_minor"] == 520
    assert not one_piece.matched_products(
        [{**ref, "provider_id": "OP01-001_p1"}, ref],
        {"901": single}, {"902": package}
    ), "Base price cannot choose between exact number-sharing printings"
