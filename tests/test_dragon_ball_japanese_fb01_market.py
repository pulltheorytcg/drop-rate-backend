"""Batch 1: only independently verifiable non-English FB01 marketplace guides.

Source data is a Cardmarket Non-English regional pricing guide; none of these
tests imply a verified Japanese-only completed sale or physical-copy value.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app import dragon_ball_market as market
from app.dragon_ball_japanese_fb01_market import (
    MATCH_BASIS, EN_BOOSTER, NON_EN_BOOSTER,
    matched_japanese_fb01, japanese_fb01_quote,
)
from app.fx import FxQuote

NOW = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)


def refs():
    english = {
        "provider": "Bandai Official",
        "system_code": "DRAGON_BALL_SUPER_FUSION_WORLD",
        "language": "English",
        "provider_id": "583001:FB01-003",
        "set_id": "583001",
        "set_name": "BOOSTER PACK -AWAKENED PULSE- [FB01]",
        "card_number": "FB01-003",
        "name": "Vados",
        "rarity": None,
    }
    japanese = {
        **english,
        "language": "Japanese",
        "provider_id": "584001:FB01-003",
        "set_id": "584001",
        "set_name": "ブースターパック 覚醒の鼓動[FB01]",
        "name": "ヴァドス",
    }
    return english, japanese


def marketplace():
    english = {
        "idProduct": 756838, "idCategory": 1049,
        "categoryName": "Dragon Ball Super Singles",
        "name": "Vados (FB01-003) [Fusion World]",
        "idExpansion": 5552,
    }
    japanese_region = {**english, "idProduct": 768554, "idExpansion": 5731}
    english_pack = {
        "idProduct": 1, "idCategory": 1050,
        "categoryName": "Dragon Ball Super Boosters",
        "name": EN_BOOSTER, "idExpansion": 5552,
    }
    non_english_pack = {
        **english_pack, "idProduct": 2, "name": NON_EN_BOOSTER,
        "idExpansion": 5731,
    }
    return {"en": english, "non-en": japanese_region}, {
        "en": english_pack, "non-en": non_english_pack,
    }


def fx():
    return FxQuote("EUR", "GBP", Decimal(".85"), NOW, NOW,
                   "ECB_EURO_REFERENCE_RATES")


def test_real_public_fb01_product_ids_are_region_separated_and_printing_exact():
    english, japanese = refs()
    singles, packaging = marketplace()
    found = matched_japanese_fb01([english, japanese], singles, packaging)
    assert list(found) == ["584001:FB01-003"]
    match = found[japanese["provider_id"]]
    assert match["product"]["idProduct"] == 768554
    assert match["english_set_id"] == "583001"
    assert match["english_expansion_id"] == 5552
    assert match["region_expansion_id"] == 5731
    quote = japanese_fb01_quote(
        japanese, match, {"idProduct": 768554, "idCategory": 1049, "trend": "0.80"},
        NOW, fx(),
    )
    assert quote["price_gbp_minor"] == 68
    assert quote["source"] == "CARDMARKET_BULK_SINGLES"
    assert quote["original_currency"] == "EUR"
    assert quote["valuation_role"] == "MIXED_NON_ENGLISH_REFERENCE"
    assert quote["reference_language"] == "Japanese"
    assert quote["marketplace_region_label"] == "Non-English"
    assert quote["match_basis"] == MATCH_BASIS
    assert quote["english_checklist_provider_id"] == "583001:FB01-003"
    assert quote["reference_identity"]["name"] == "ヴァドス"
    assert quote["physical_language_confirmed"] is False
    assert quote["condition_specific"] is False
    assert quote["physical_valuation_eligible"] is False


@pytest.mark.parametrize("mutation", [
    "no_japanese", "no_english", "jp_promo", "jp_parallel",
    "en_parallel", "wrong_set", "wrong_game", "wrong_language",
    "wrong_card_no", "wrong_english_name", "duplicate_official_jp",
    "duplicate_official_en", "duplicate_regional_product",
    "wrong_market_no", "missing_regional_pack", "only_english_market",
    "incorrect_regional_name", "missing_english_pack",
    "duplicate_non_english_expansion", "duplicate_english_expansion",
    "wrong_market_category", "wrong_market_expansion",
    "same_english_and_non_english_expansion",
])
def test_false_matches_fail_closed(mutation):
    english, japanese = refs()
    singles, packaging = marketplace()
    references = [english, japanese]
    if mutation == "no_japanese": references = [english]
    if mutation == "no_english": references = [japanese]
    if mutation == "jp_promo": japanese["set_name"] = "プロモーションカード"
    if mutation == "jp_parallel": japanese["provider_id"] += "_p1"
    if mutation == "en_parallel": english["provider_id"] += "_p1"
    if mutation == "wrong_set": japanese["set_id"] = "584002"
    if mutation == "wrong_game": japanese["system_code"] = "DRAGON_BALL_SUPER_MASTERS"
    if mutation == "wrong_language": japanese["language"] = "English"
    if mutation == "wrong_card_no": japanese["card_number"] = "FB01-004"
    if mutation == "wrong_english_name": english["name"] = "Someone Else"
    if mutation == "duplicate_official_jp": references.append(deepcopy(japanese))
    if mutation == "duplicate_official_en": references.append(deepcopy(english))
    if mutation == "duplicate_regional_product":
        singles["other"] = {**singles["non-en"], "idProduct": 768555}
    if mutation == "wrong_market_no":
        singles["non-en"]["name"] = "Vados (FB01-004) [Fusion World]"
    if mutation == "missing_regional_pack": del packaging["non-en"]
    if mutation == "only_english_market": del singles["non-en"]
    if mutation == "incorrect_regional_name":
        packaging["non-en"]["name"] = EN_BOOSTER + " (English)"
    if mutation == "missing_english_pack": del packaging["en"]
    if mutation == "duplicate_non_english_expansion":
        packaging["other"] = {**packaging["non-en"], "idExpansion": 9999}
    if mutation == "duplicate_english_expansion":
        packaging["other"] = {**packaging["en"], "idExpansion": 9999}
    if mutation == "wrong_market_category":
        singles["non-en"]["idCategory"] = 1050
    if mutation == "wrong_market_expansion":
        singles["non-en"]["idExpansion"] = 5552
    if mutation == "same_english_and_non_english_expansion":
        packaging["non-en"]["idExpansion"] = 5552
    assert not matched_japanese_fb01(references, singles, packaging)


@pytest.mark.parametrize("mutation", [
    "missing", "wrong_category", "wrong_product", "zero",
    "negative", "small_rounds_to_zero", "malformed",
])
def test_quote_fail_closed_on_missing_or_corrupt_price(mutation):
    english, japanese = refs()
    singles, packaging = marketplace()
    match = matched_japanese_fb01([english, japanese], singles, packaging)[japanese["provider_id"]]
    price = {"idProduct": 768554, "idCategory": 1049, "trend": "0.80"}
    if mutation == "missing": price = None
    if mutation == "wrong_category": price["idCategory"] = 1050
    if mutation == "wrong_product": price["idProduct"] = 756838
    if mutation == "zero": price["trend"] = "0"
    if mutation == "negative": price["trend"] = "-1"
    if mutation == "small_rounds_to_zero": price["trend"] = "0.001"
    if mutation == "malformed": price["trend"] = "not a price"
    assert japanese_fb01_quote(japanese, match, price, NOW, fx()) is None


@pytest.mark.asyncio
async def test_existing_refresh_updates_only_global_reference_prices(monkeypatch):
    english, japanese = refs()
    singles, packaging = marketplace()
    now = NOW
    written = []

    async def download(client, path, **kwargs):
        if "nonsingles" in path:
            return packaging, now
        if "singles" in path:
            return singles, now
        return {
            "756838": {"idProduct": 756838, "idCategory": 1049, "trend": "0.80"},
            "768554": {"idProduct": 768554, "idCategory": 1049, "trend": "0.80"},
        }, now

    class Connection:
        async def fetch(self, sql):
            assert "r.set_id='584001'" in sql
            assert "reference_cards" in sql
            return [english, japanese]
        async def executemany(self, sql, values):
            assert "reference_market_prices" in sql
            assert "inventory_items" not in sql
            assert "shopify" not in sql.lower()
            written.extend(values)

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    class FX:
        async def quote(self, **kwargs):
            return fx()

    monkeypatch.setattr(market, "download", download)
    monkeypatch.setattr(market, "user_connection", connection)
    result = await market.refresh_dragon_ball_prices(object(), uuid4(), FX())
    assert result["provider_failures"] == 0
    assert result["japanese_fb01_checked"] == 1
    assert result["japanese_fb01_matched"] == 1
    assert result["japanese_fb01_priced"] == 1
    japanese_writes = [values for values in written if values[2] == "Japanese"]
    assert len(japanese_writes) == 1
    assert japanese_writes[0][0] == "Bandai Official"
    assert japanese_writes[0][3] == "584001:FB01-003"
    assert japanese_writes[0][4][0]["physical_valuation_eligible"] is False
    assert japanese_writes[0][5] == 68


def test_randomized_corruptions_never_select_a_wrong_regional_market_product():
    rng = Random(510309)
    for _ in range(256):
        english, japanese = refs()
        singles, packaging = marketplace()
        alternate_id = rng.randint(1000000, 9000000)
        if rng.randint(0, 1):
            singles["bad"] = {
                **singles["non-en"], "idProduct": alternate_id,
            }
        else:
            packaging["bad"] = {
                **packaging["non-en"], "idExpansion": alternate_id,
            }
        assert matched_japanese_fb01([english, japanese], singles, packaging) == {}
