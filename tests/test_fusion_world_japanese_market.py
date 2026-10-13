"""Japanese Fusion World guides require independent source, set and print proof.

The Cardmarket Non-English region is not verified Japanese-language sales.
No inventory owner, Store Price, Shopify price, or automated listing is written.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app import dragon_ball_market as core
from app.fusion_world_japanese_market import (
    MATCH_BASIS, _booster_identity, matched_japanese_products,
    japanese_nonenglish_quote,
)
from app.fx import FxQuote

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
FX = FxQuote(
    "EUR", "GBP", Decimal("0.85"), NOW, NOW, "ECB_EURO_REFERENCE_RATES"
)


def references():
    en = {
        "provider": "Bandai Official", "system_code": "DRAGON_BALL_SUPER_FUSION_WORLD",
        "language": "English", "provider_id": "583001:FB01-003",
        "set_id": "583001", "card_number": "FB01-003", "name": "Vados",
        "set_name": "BOOSTER PACK -AWAKENED PULSE- [FB01]",
        "rarity": None, "evidence": {"provider_variant": ""},
    }
    jp = {
        **en, "language": "Japanese", "provider_id": "584001:FB01-003",
        "set_id": "584001", "name": "ヴァドス",
        "set_name": "ブースターパック 覚醒の鼓動[FB01]",
    }
    return en, jp


def market():
    english = {
        "idProduct": 756838, "idExpansion": 5552, "idCategory": 1049,
        "categoryName": "Dragon Ball Super Singles",
        "name": "Vados (FB01-003) [Fusion World]",
    }
    japanese = {**english, "idProduct": 768554, "idExpansion": 5731}
    packs = {
        "english": {
            "idProduct": 200, "idExpansion": 5552, "idCategory": 1050,
            "categoryName": "Dragon Ball Super Boosters",
            "name": "Awakened Pulse Booster [Fusion World]",
        },
        "regional": {
            "idProduct": 201, "idExpansion": 5731, "idCategory": 1050,
            "categoryName": "Dragon Ball Super Boosters",
            "name": "Awakened Pulse Booster [Fusion World] (Non-English)",
        },
    }
    return {"english": english, "japanese": japanese}, packs


def test_official_independent_checklists_and_non_english_market_region():
    en,jp=references();singles,packaging=market()
    assert _booster_identity(en)==("FB01", "awakenedpulse")
    assert _booster_identity(jp)==("FB01", "")
    result=matched_japanese_products([en,jp],singles,packaging)
    assert set(result)=={"584001:FB01-003"}
    match=result["584001:FB01-003"]
    assert match["product"]["idProduct"]==768554
    assert match["region_marker"]=="Non-English"
    assert match["english_provider_id"]=="583001:FB01-003"
    quote=japanese_nonenglish_quote(jp,match,{"idProduct":768554,"idCategory":1049,"trend": "1.00"},NOW,FX)
    assert quote["price_gbp_minor"]==85
    assert quote["match_basis"]==MATCH_BASIS
    assert quote["source"]=="CARDMARKET_BULK_SINGLES"
    assert quote["valuation_role"]=="MIXED_NON_ENGLISH_REFERENCE"
    assert quote["reference_language"]=="Japanese"
    assert quote["reference_printing_id"]=="584001:FB01-003"
    assert quote["reference_identity"]["name"]=="ヴァドス"
    assert quote["marketplace_region_label"]=="Non-English"
    assert quote["physical_valuation_eligible"] is False
    assert quote["physical_language_confirmed"] is False
    assert quote["condition_specific"] is False


@pytest.mark.parametrize("change", [
    "Japanese parallel", "English parallel", "Wrong Japanese set code",
    "Wrong English set code", "Japanese promo set", "English promo set",
    "Japanese false language", "English false language", "Japanese wrong game",
    "Japanese wrong provider", "Japanese wrong number", "English wrong number",
    "Duplicate Japanese base", "Duplicate English base", "No English reference",
    "Different release title", "Different market product name",
    "Market product number conflict", "English-only expansion",
    "Duplicated Non-English expansion", "Duplicated regional product",
    "Wrong market category", "Wrong regional label", "Wrong published rarity",
    "Different English release title", "Multiple names same market ID",
])
def test_unsafe_printing_region_and_language_do_not_match(change):
    en,jp=references();products,packs=market()
    refs=[en,jp]
    if change=="Japanese parallel":jp["provider_id"]+="_p1"
    if change=="English parallel":en["provider_id"]+="_p1"
    if change=="Wrong Japanese set code":jp["set_id"]="584002";jp["provider_id"]="584002:FB01-003"
    if change=="Wrong English set code":en["set_id"]="583002";en["provider_id"]="583002:FB01-003"
    if change=="Japanese promo set":jp["set_name"]="プロモーションカード[FB01]"
    if change=="English promo set":en["set_name"]="Promotion Card [FB01]"
    if change=="Japanese false language":jp["language"]="English"
    if change=="English false language":en["language"]="Japanese"
    if change=="Japanese wrong game":jp["system_code"]="DRAGON_BALL_SUPER_MASTERS"
    if change=="Japanese wrong provider":jp["provider"]="Unverified"
    if change=="Japanese wrong number":jp["card_number"]="FB01-004";jp["provider_id"]="584001:FB01-004"
    if change=="English wrong number":en["card_number"]="FB01-004";en["provider_id"]="583001:FB01-004"
    if change=="Duplicate Japanese base":refs.append(deepcopy(jp))
    if change=="Duplicate English base":refs.append(deepcopy(en))
    if change=="No English reference":refs.remove(en)
    if change=="Different release title":jp["set_name"]="ブースターパック 別のセット[FB02]"
    if change=="Different market product name":products["japanese"]["name"]="Other (FB01-003) [Fusion World]"
    if change=="Market product number conflict":products["japanese"]["name"]="Vados (FB01-004) [Fusion World]"
    if change=="English-only expansion":del packs["regional"]
    if change=="Duplicated Non-English expansion":packs["another"]={**packs["regional"],"idExpansion":9999}
    if change=="Duplicated regional product":products["duplicate"]={**products["japanese"],"idProduct":1111}
    if change=="Wrong market category":products["japanese"]["categoryName"]="Dragon Ball Super Lots"
    if change=="Wrong regional label":packs["regional"]["name"]="Awakened Pulse Booster [Fusion World] (English)"
    if change=="Wrong published rarity":en["rarity"]="Rare"
    if change=="Different English release title":en["set_name"]="BOOSTER PACK -SOMETHING ELSE- [FB01]"
    if change=="Multiple names same market ID":products["duplicate"]={**products["japanese"],"name":"Vados (FB01-003) [Fusion World]"}
    assert not matched_japanese_products(refs,products,packs),change


def test_invalid_zero_and_other_market_quotes_fail_closed():
    en,jp=references();products,packs=market()
    match=matched_japanese_products([en,jp],products,packs)["584001:FB01-003"]
    for quote in (
        None, {}, {"idProduct":768554,"idCategory":1049,"trend":0},
        {"idProduct":768554,"idCategory":1049,"trend":-2},
        {"idProduct":768554,"idCategory":1049,"trend":"garbage"},
        {"idProduct":768555,"idCategory":1049,"trend":11},
        {"idProduct":768554,"idCategory":9999,"trend":11},
    ):
        assert japanese_nonenglish_quote(jp,match,quote,NOW,FX) is None


@pytest.mark.asyncio
async def test_actual_refresh_cannot_reuse_english_product_for_japanese(monkeypatch):
    en,jp=references();singles,pack=market();writes=[]
    # A third Japanese reference with no matching region must stay null even
    # though its printed number exists in an English catalogue.
    unmatched={**jp,"provider_id":"584001:FB01-004","card_number":"FB01-004","name":"別のカード"}
    now=NOW

    async def download(client,path,**kwargs):
        if "nonsingles" in path:return pack,now
        if "singles" in path:return singles,now
        return {
            "756838":{"idProduct":756838,"idCategory":1049,"trend":"99.00"},
            "768554":{"idProduct":768554,"idCategory":1049,"trend":"1.00"},
        },now

    class FakeConn:
        async def fetch(self,sql):
            assert "r.language='Japanese'" in sql
            return [en,jp,unmatched]
        async def executemany(self,sql,values):
            assert "tcg.reference_market_prices" in sql
            assert "inventory_items" not in sql and "shopify" not in sql.lower()
            writes.extend(values)

    @asynccontextmanager
    async def user_conn(*args):yield FakeConn()
    class Rate:
        async def quote(self,**kwargs):return FX

    monkeypatch.setattr(core,"download",download)
    monkeypatch.setattr(core,"user_connection",user_conn)
    receipt=await core.refresh_dragon_ball_prices(object(),uuid4(),Rate())
    assert receipt["checked"]==3
    assert receipt["japanese_checked"]==2
    assert receipt["japanese_matched"]==1
    assert receipt["japanese_priced"]==1
    assert len(writes)==3
    ours=next(row for row in writes if row[3]=="584001:FB01-003")
    wrong=next(row for row in writes if row[3]=="584001:FB01-004")
    assert ours[5]==ours[6]==85
    assert ours[4][0]["product_id"]=="768554"
    assert ours[4][0]["valuation_role"]=="MIXED_NON_ENGLISH_REFERENCE"
    assert wrong[5] is None and wrong[4]==[]


def test_1000_seeded_collisions_cannot_choose_by_price():
    en,jp=references()
    base,pack=market()
    for seed in range(1000):
        rng=Random(seed)
        singles=deepcopy(base);packs=deepcopy(pack);refs=[deepcopy(en),deepcopy(jp)]
        if seed%2==0:
            singles["collision"]={**singles["japanese"],"idProduct":10_000+seed}
        if seed%3==0:
            packs["collision"]={**packs["regional"],"idExpansion":10_000+seed}
        if seed%5==0:
            refs.append({**refs[1],"provider_id":"584001:FB01-003_p1"})
        matched=matched_japanese_products(refs,singles,packs)
        assert ("584001:FB01-003" in matched)==(seed%2!=0 and seed%3!=0)
        # An unrelated variant does not cause the exact base printing to
        # inherit its different regional asking/guide price.
        assert refs[1]["provider_id"]=="584001:FB01-003"
