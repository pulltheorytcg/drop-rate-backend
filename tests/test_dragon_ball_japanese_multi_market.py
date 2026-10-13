"""Bulk Japanese Fusion World FB02–FB11 source matching and safety regressions.

Synthetic stress fixtures demonstrate 1,585-record processing capacity; they
must never be presented as 1,263 real provider quotations.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from random import Random

import pytest

from app.dragon_ball_japanese_multi_market import (
    MATCH_BASIS, RELEASES, _official_release, match_regional_boosters,
    regional_booster_quote, regional_coverage_report,
)
from app.fx import FxQuote


NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
# These ID pairs were verified against Cardmarket's public English and
# Non-English booster/box lists, never derived from price order or translation.
EXPANSIONS = {
    "FB02": (5730, 5767),
    "FB03": (5847, 5903),
    "FB04": (5905, 5906),
    "FB05": (6027, 6076),
    "FB06": (6132, 6523),
    "FB07": (6183, 6524),
    "FB08": (6410, 6525),
    "FB09": (6502, 6526),
    "FB10": (6594, 6620),
    "FB11": (6750, 6785),  # synthetic identity; no live FB11 guide implied
}
PUBLISHED_SOURCE = {
    "FB02": (809870, "Anilaza", "FB02-002", "0.09"),
    "FB03": (790210, "Khai", "FB03-003", "0.03"),
    "FB04": (833444, "Whis", "FB04-002", "0.10"),
    "FB05": (837167, "Piccolo (Mini) : DA", "FB05-016", "0.05"),
}


def pack(code, expansion, *, region="English", box=False, name=None):
    title = name or RELEASES[code][4]
    label = f"{title} Booster{' Box' if box else ''} [Fusion World]"
    if region != "English":
        label += f" ({region})"
    return {
        "idProduct": expansion * 10 + (2 if box else 1),
        "idCategory": 1052 if box else 1050,
        "categoryName": "Dragon Ball Super Booster Boxes" if box else "Dragon Ball Super Boosters",
        "name": label, "idExpansion": expansion,
    }


def make_ref(code, number, language, name):
    en_set, jp_set, en_title, jp_title, _ = RELEASES[code]
    set_id = en_set if language == "English" else jp_set
    return dict(provider="Bandai Official",
                system_code="DRAGON_BALL_SUPER_FUSION_WORLD",
                language=language, provider_id=f"{set_id}:{number}",
                set_id=set_id, set_name=en_title if language == "English" else jp_title,
                card_number=number, name=name, rarity=None)


def single(code, number, name, expansion, product_id):
    return dict(idProduct=product_id, idCategory=1049,
                categoryName="Dragon Ball Super Singles",
                name=f"{name} ({number}) [Fusion World]", idExpansion=expansion)


def fixture(code="FB02"):
    product_id, name, number, price = PUBLISHED_SOURCE[code]
    en_exp, regional_exp = EXPANSIONS[code]
    english = make_ref(code, number, "English", name)
    japanese = make_ref(code, number, "Japanese", "カタログの日本語名")
    packs = {
        "en": pack(code, en_exp),
        "non-en": pack(code, regional_exp, region="Non-English", box=(code in {"FB02","FB04"})),
    }
    products = {
        "regional": single(code, number, name, regional_exp, product_id),
        "english": single(code, number, name, en_exp, product_id+1),
    }
    return english, japanese, packs, products, price


@pytest.mark.parametrize("code", list(PUBLISHED_SOURCE))
def test_exact_public_source_expansions_have_distinct_regional_printings(code):
    en, jp, packs, products, eur = fixture(code)
    matched = match_regional_boosters([en, jp], products, packs)
    assert list(matched) == [jp["provider_id"]]
    found = matched[jp["provider_id"]]
    en_id, jp_id = EXPANSIONS[code]
    assert found["english_expansion"] == en_id
    assert found["regional_expansion"] == jp_id
    assert found["product"]["idProduct"] == PUBLISHED_SOURCE[code][0]
    quote = regional_booster_quote(
        jp, found, {"idProduct": found["product"]["idProduct"],
                    "idCategory": 1049, "trend": eur},
        NOW, FxQuote("EUR","GBP",Decimal(".85"),NOW,NOW,"ECB_EURO_REFERENCE_RATES"),
    )
    assert quote is not None and quote["price_gbp_minor"] > 0
    assert quote["match_basis"] == MATCH_BASIS
    assert quote["source"] == "CARDMARKET_BULK_SINGLES"
    assert quote["reference_language"] == "Japanese"
    assert quote["marketplace_region_label"] == "Non-English"
    assert quote["physical_language_confirmed"] is False
    assert quote["physical_valuation_eligible"] is False
    assert quote["condition_specific"] is False
    assert quote["english_marketplace_expansion_id"] != quote["expansion_id"]
    assert quote["reference_identity"]["name"] == jp["name"]


@pytest.mark.parametrize("mutation", [
    "no_en", "no_jp", "wrong_en_number", "wrong_jp_number", "wrong_en_name",
    "wrong_game", "wrong_lang", "wrong_jp_title", "wrong_en_title", "wrong_jp_set",
    "jp_parallel", "en_parallel", "jp_promo", "duplicate_en_ref", "duplicate_jp_ref",
    "duplicate_market_print", "wrong_market_code", "wrong_market_name",
    "wrong_market_category", "wrong_market_expansion",
    "missing_english_pack", "missing_region_pack", "wrong_region_label",
    "duplicate_region_expansion", "duplicate_english_expansion",
    "region_is_english", "unverified_prefix", "marketplace_category_mismatch",
])
def test_identity_region_and_parallel_attacks_fail_closed(mutation):
    en, jp, packs, products, _ = fixture()
    refs = [en, jp]
    if mutation == "no_en": refs.remove(en)
    if mutation == "no_jp": refs.remove(jp)
    if mutation == "wrong_en_number": en["card_number"] = "FB02-004"
    if mutation == "wrong_jp_number": jp["card_number"] = "FB02-004"
    if mutation == "wrong_en_name": en["name"] = "Not Anilaza"
    if mutation == "wrong_game": jp["system_code"] = "DRAGON_BALL_SUPER_MASTERS"
    if mutation == "wrong_lang": jp["language"] = "English"
    if mutation == "wrong_jp_title": jp["set_name"] = "promo card [FB02]"
    if mutation == "wrong_en_title": en["set_name"] = "BOOSTER PACK -OTHER- [FB02]"
    if mutation == "wrong_jp_set": jp["set_id"] = "584003"
    if mutation == "jp_parallel": jp["provider_id"] += "_p1"
    if mutation == "en_parallel": en["provider_id"] += "_p1"
    if mutation == "jp_promo": jp["set_id"] = "584901"
    if mutation == "duplicate_en_ref": refs.append(deepcopy(en))
    if mutation == "duplicate_jp_ref": refs.append(deepcopy(jp))
    if mutation == "duplicate_market_print":
        products["extra"] = {**products["regional"], "idProduct": 999999}
    if mutation == "wrong_market_code":
        products["regional"]["name"] = "Anilaza (FB03-002) [Fusion World]"
    if mutation == "wrong_market_name":
        products["regional"]["name"] = "Different (FB02-002) [Fusion World]"
    if mutation == "wrong_market_category": products["regional"]["idCategory"] = 1050
    if mutation == "wrong_market_expansion": products["regional"]["idExpansion"] = 5730
    if mutation == "missing_english_pack": del packs["en"]
    if mutation == "missing_region_pack": del packs["non-en"]
    if mutation == "wrong_region_label": packs["non-en"]["name"] = "Blazing Aura Booster Box [Fusion World] (German)"
    if mutation == "duplicate_region_expansion":
        packs["regional-duplicate"] = {**packs["non-en"], "idExpansion": 9999}
    if mutation == "duplicate_english_expansion":
        packs["english-duplicate"] = {**packs["en"], "idExpansion": 9999}
    if mutation == "region_is_english": packs["non-en"]["idExpansion"] = packs["en"]["idExpansion"]
    if mutation == "unverified_prefix": jp["provider"] = "Unofficial"
    if mutation == "marketplace_category_mismatch":
        products["regional"]["categoryName"] = "Dragon Ball Super Boosters"
    assert match_regional_boosters(refs, products, packs) == {}


@pytest.mark.parametrize("bad_price", [
    None, {"idProduct":809870,"idCategory":1049,"trend":"0"},
    {"idProduct":809870,"idCategory":1049,"trend":None},
    {"idProduct":809870,"idCategory":1049,"trend":"NaN"},
    {"idProduct":809870,"idCategory":1049,"trend":"-1"},
    {"idProduct":809871,"idCategory":1049,"trend":"0.5"},
    {"idProduct":809870,"idCategory":1050,"trend":"0.5"},
])
def test_invalid_price_and_wrong_product_fail_closed(bad_price):
    en,jp,packs,products,_=fixture()
    match=match_regional_boosters([en,jp],products,packs)[jp["provider_id"]]
    quote=regional_booster_quote(
        jp,match,bad_price,NOW,
        FxQuote("EUR","GBP",Decimal(".85"),NOW,NOW,"ECB_EURO_REFERENCE_RATES"),
    )
    assert quote is None


@pytest.mark.parametrize("code", list(RELEASES))
def test_genuine_official_base_identity_is_unique_for_release(code):
    number = code + "-001"
    en = make_ref(code,number,"English","Card English Title")
    jp = make_ref(code,number,"Japanese","日本語のカード名")
    assert _official_release(en,language="English") == code
    assert _official_release(jp,language="Japanese") == code
    assert _official_release(jp,language="English") is None
    assert _official_release({**jp,"provider_id":jp["provider_id"]+"_p1"},language="Japanese") is None


def test_large_1585_reference_fixture_handles_1263_base_candidates_without_collision():
    # This is a *synthetic throughput test*, never a claim of 1,263 live prices.
    totals=[163,163,158,154,143,158,158,164,162,162]
    base=[140,140,130,120,120,122,122,123,123,123]
    assert sum(totals)==1585 and sum(base)==1263
    refs=[];products={};packs={}
    for i,(code,release) in enumerate(RELEASES.items()):
        en_exp,foreign_exp=EXPANSIONS[code]
        packs[f"en-{code}"]=pack(code,en_exp)
        packs[f"reg-{code}"]=pack(code,foreign_exp,region="Non-English",box=(code in {"FB02","FB04"}))
        for n in range(1,totals[i]+1):
            number=f"{code}-{n:03d}"
            en=make_ref(code,number,"English",f"Unique Official Name {code}-{n}")
            jp=make_ref(code,number,"Japanese",f"日本語 {code}-{n}")
            if n>base[i]:
                jp["provider_id"] += "_p1"
            refs.append(jp)
            refs.append(en)
            if n<=base[i]:
                products[f"{code}-{n}"]=single(code,number,en["name"],foreign_exp,100000+i*1000+n)
    assert sum(r["language"]=="Japanese" for r in refs)==1585
    result=match_regional_boosters(refs,products,packs)
    assert len(result)==1263
    assert len({v["product"]["idProduct"] for v in result.values()})==1263
    report=regional_coverage_report(refs,result,{})
    assert sum(v["checked"] for v in report.values())==1585
    assert sum(v["base_candidate_count"] for v in report.values())==1263
    assert sum(v["unique_market_matches"] for v in report.values())==1263


def test_512_randomized_conflicting_print_variants_never_inherit_a_price():
    rng=Random(845142)
    for _ in range(512):
        code=rng.choice(list(PUBLISHED_SOURCE))
        en,jp,packs,products,_=fixture(code)
        conflict_id=rng.randint(5000000,9000000)
        if rng.randint(0,1):
            products["conflict"]={**products["regional"],"idProduct":conflict_id}
        else:
            packs["conflict"]={**packs["non-en"],"idExpansion":conflict_id}
        assert match_regional_boosters([en,jp],products,packs)=={}
