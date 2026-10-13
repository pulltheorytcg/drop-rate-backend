"""High-gap Dragon Ball Masters price recovery cannot guess parallel artworks.

Real first-party Cardmarket public source labels/IDs were replayed against 902
official Bandai card references (October 2026). Synthetic tests assert that
the released matcher fails closed on collisions, altered set/number/region,
wrong publisher, missing data and price-based disambiguation.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app import dragon_ball_market
from app.dragon_ball_masters_missing_market import (
    RELEASES, RELEASE_BASIS, _release_expansion_ids,
    exact_masters_supplemental_matches, supplemental_coverage,
)
from app.fx import FxQuote

NOW = datetime(2026,10,13,15,0,tzinfo=timezone.utc)
EXPS={
    "428601":2505,"428602":2966,"428603":3520,
    "428101":2312,"428102":2353,"428103":2416,"428201":3733,
}
PUBLIC_PRODUCTS={
    "428601": ("DB1-001","Son Goku, Might of Many",393712,"0.12"),
    "428602": ("DB2-002","Ultra Instinct Son Goku, Monumental Presence",441443,"1.21"),
    "428603": ("DB3-002","Son Goku, Off to Defeat King Piccolo",508450,"0.82"),
    "428101": ("TB1-045","Universe 9 Striker Roselle",355305,"0.05"),
    "428201": ("EB1-02","Yamcha, Wolf Fang Pitching Fistball",538068,"0.05"),
}

def ref(set_id="428602",number="DB2-002",name="Ultra Instinct Son Goku, Monumental Presence"):
    return {
        "provider":"Bandai Official","system_code":"DRAGON_BALL_SUPER_MASTERS",
        "language":"English","set_id":set_id,
        "set_name":RELEASES[set_id][0],
        "card_number":number,
        "provider_id":f"{set_id}:{number}.png",
        "name":name,"rarity":"Common[C]",
    }

def product(set_id="428602",number="DB2-002",name="Ultra Instinct Son Goku, Monumental Presence",product_id=441443):
    return {"idProduct":product_id,"idExpansion":EXPS[set_id],
            "idCategory":1049,"categoryName":"Dragon Ball Super Singles","name":name}

def packaging(set_id="428602",expansion=None):
    title=RELEASES[set_id][1]
    return {"idProduct":888,"idExpansion":EXPS[set_id] if expansion is None else expansion,
            "idCategory":1050,"categoryName":"Dragon Ball Super Boosters",
            "name":title+" Booster"}

def key(record):
    return ("DRAGON_BALL_SUPER_MASTERS",record["provider_id"])


@pytest.mark.parametrize("set_id",list(PUBLIC_PRODUCTS))
def test_real_official_masters_release_uses_unique_named_cardmarket_product(set_id):
    number,name,pid,_=PUBLIC_PRODUCTS[set_id]
    official=ref(set_id,number,name)
    market=product(set_id,number,name,pid)
    pack=packaging(set_id)
    matches=exact_masters_supplemental_matches([official],{"single":market},{"booster":pack})
    assert matches[key(official)]["idProduct"]==pid
    assert matches[key(official)]["idExpansion"]==EXPS[set_id]
    assert len(matches)==1
    assert RELEASE_BASIS.startswith("EXACT_BANDAI_MASTERS")


@pytest.mark.parametrize("mutation", [
    "fake_provider","wrong_game","wrong_language","wrong_set_id",
    "wrong_official_title","wrong_source_name","invalid_number",
    "mismatched_provider_file","parallel","number_collides",
    "same_name_promo","different_official_same_name",
    "no_release_pack","wrong_pack_name","wrong_pack_category_id",
    "wrong_market_expansion","duplicate_expansion",
    "duplicate_market_product","duplicate_market_unpriced",
    "market_other_game","market_wrong_id","market_missing_name",
    "market_suffix_wrong_number","bad_market_id_type",
])
def test_unsafe_identity_and_source_mutations_never_select_price(mutation):
    official=ref()
    refs=[official]
    m=product()
    packs={"release":packaging()}
    singles={"base":m}
    if mutation=="fake_provider":official["provider"]="Unofficial"
    if mutation=="wrong_game":official["system_code"]="DRAGON_BALL_SUPER_FUSION_WORLD"
    if mutation=="wrong_language":official["language"]="Japanese"
    if mutation=="wrong_set_id":official["set_id"]="428603"
    if mutation=="wrong_official_title":official["set_name"]="DRAFT BOX 05 -OTHER-"
    if mutation=="wrong_source_name":m["name"]="Different Son Goku"
    if mutation=="invalid_number":official["card_number"]="DB2-2"
    if mutation=="mismatched_provider_file":official["provider_id"]+="wrong"
    if mutation=="parallel":
        official["card_number"]+="_PR"
        official["provider_id"]=f"428602:{official['card_number']}.png"
    if mutation=="number_collides":
        refs.append(ref(number="DB2-002",name="Different printed face"))
    if mutation=="same_name_promo":
        refs.append(ref(number="DB2-002_PR"))
    if mutation=="different_official_same_name":
        refs.append(ref(number="DB2-003"))
    if mutation=="no_release_pack":packs={}
    if mutation=="wrong_pack_name":packs["release"]["name"]="Other Booster"
    if mutation=="wrong_pack_category_id":packs["release"]["idCategory"]=1051
    if mutation=="wrong_market_expansion":m["idExpansion"]=9999
    if mutation=="duplicate_expansion":
        packs["other"]={**packs["release"],"idExpansion":9999}
    if mutation=="duplicate_market_product":
        singles["other"]={**m,"idProduct":9999}
    if mutation=="duplicate_market_unpriced":
        singles["other"]={**m,"idProduct":9999} # quote availability must never choose
    if mutation=="market_other_game":m["categoryName"]="One Piece Single"
    if mutation=="market_wrong_id":m["idCategory"]=1051
    if mutation=="market_missing_name":m["name"]=""
    if mutation=="market_suffix_wrong_number":m["name"]=m["name"]+" (DB2-003)"
    if mutation=="bad_market_id_type":m["idProduct"]="441443"
    assert exact_masters_supplemental_matches(refs,singles,packs)=={}


def test_back_face_and_number_collisions_block_both_printings_and_order_never_matters():
    front=ref(number="DB2-001",name="SSB Kaio-Ken Son Goku, Concentrated Destruction")
    alternate=ref(number="DB2-001",name="Another Official Face")
    market=product(number="DB2-001",name=front["name"],product_id=441438)
    assert exact_masters_supplemental_matches([front,alternate],{"x":market},{"p":packaging()})=={}
    assert exact_masters_supplemental_matches([alternate,front],{"x":market},{"p":packaging()})=={}
    # Duplicated marketplace source ID claimed by two cards must quarantine
    # both, not pick whichever provider record is visited first.
    a=ref(number="DB2-002",name="Card A")
    b=ref(number="DB2-003",name="Card B")
    pa=product(number=a["card_number"],name=a["name"],product_id=999)
    pb=product(number=b["card_number"],name=b["name"],product_id=999)
    for pair in [(a,b),(b,a)]:
        assert exact_masters_supplemental_matches(
            list(pair),{"a":pa,"b":pb},{"set":packaging()}
        )=={}


def test_wrong_region_or_product_subtype_cannot_be_source_of_release():
    official=ref()
    market=product()
    variants=[
        {"name":"Divine Multiverse Pre-Release Pack","idCategory":1050,
         "categoryName":"Dragon Ball Super Boosters","idExpansion":EXPS["428602"]},
        {"name":"Divine Multiverse Booster (Non-English)","idCategory":1050,
         "categoryName":"Dragon Ball Super Boosters","idExpansion":999},
        {"name":"Divine Multiverse Booster","idCategory":1051,
         "categoryName":"Dragon Ball Super Boosters","idExpansion":EXPS["428602"]},
        {"name":"Other: Common Set","idCategory":1051,
         "categoryName":"DBS Set","idExpansion":EXPS["428602"]},
        {"name":"Draft Box 05: Divine Multiverse","idCategory":1053,
         "categoryName":"Dragon Ball Super Starter Decks","idExpansion":EXPS["428602"]},
    ]
    for pack in variants:
        assert exact_masters_supplemental_matches([official],{"x":market},{"release":pack})=={}


def test_multiple_corroborrating_packaging_records_must_share_exact_expansion():
    official=ref()
    market=product()
    source=packaging()
    pack_sets={
        "booster":source,
        "full":{**source,"name":"Divine Multiverse: Full Set",
                 "idCategory":1051,"categoryName":"DBS Set"},
        "box":{**source,"name":"Divine Multiverse Booster Box",
                "idCategory":1052,"categoryName":"Dragon Ball Super Booster Boxes"},
    }
    assert exact_masters_supplemental_matches([official],{"x":market},pack_sets)
    bad=deepcopy(pack_sets)
    bad["box"]["idExpansion"]=9999
    assert exact_masters_supplemental_matches([official],{"x":market},bad)=={}


def test_market_number_suffix_must_exactly_match_official_two_or_three_digit_code():
    official=ref("428201","EB1-02","Yamcha, Wolf Fang Pitching Fistball")
    p=product("428201","EB1-02",official["name"]+" (EB1-02)",538068)
    matched=exact_masters_supplemental_matches([official],{"card":p},{"booster":packaging("428201")})
    assert matched[key(official)]["idProduct"]==538068
    p["name"]=official["name"]+" (EB1-03)"
    assert not exact_masters_supplemental_matches([official],{"card":p},{"booster":packaging("428201")})


def test_supplemental_receipt_only_counts_actual_source_quotes_not_matching_card_labels():
    official=ref()
    m=product()
    entries=exact_masters_supplemental_matches([official],{"x":m},{"box":packaging()})
    prices={str(m["idProduct"]):{"idCategory":1049,"trend":1.21}}
    coverage=supplemental_coverage([official],entries,prices)
    assert coverage["428602"]=={"checked":1,"matched":1,"positive_trend_present":1}
    assert coverage["428601"]=={"checked":0,"matched":0,"positive_trend_present":0}
    prices[str(m["idProduct"])]["trend"]=0
    assert supplemental_coverage([official],entries,prices)["428602"]["positive_trend_present"]==0


@pytest.mark.asyncio
async def test_bulk_source_refresh_only_writes_global_reference_prices(monkeypatch):
    source=ref()
    m=product()
    pack=packaging()
    now=datetime.now(timezone.utc)
    writes=[]

    async def download(client,path,**kwargs):
        if "nonsingles" in path:return {"pack":pack},now
        if "singles" in path:return {"single":m},now
        return {str(m["idProduct"]):{"idProduct":m["idProduct"],"idCategory":1049,"trend":1.21}},now

    class Connection:
        async def fetch(self,sql):
            assert "reference_cards" in sql and "inventory_items" not in sql
            return [source]
        async def executemany(self,sql,values):
            assert "tcg.reference_market_prices" in sql
            assert "tcg.inventory_items" not in sql
            assert "shopify" not in sql.lower()
            writes.extend(values)

    @asynccontextmanager
    async def user_connection(*args):
        yield Connection()

    class FX:
        async def quote(self,**kwargs):
            return FxQuote("EUR","GBP",Decimal(".85"),now,now,"ECB_EURO_REFERENCE_RATES")

    monkeypatch.setattr(dragon_ball_market,"download",download)
    monkeypatch.setattr(dragon_ball_market,"user_connection",user_connection)
    report=await dragon_ball_market.refresh_dragon_ball_prices(object(),uuid4(),FX())
    assert report["provider_failures"]==0
    assert report["masters_supplemental_checked"]==1
    assert report["masters_supplemental_matched"]==1
    assert report["masters_supplemental_priced"]==1
    assert report["masters_supplemental_conflicts"]==0
    assert len(writes)==1
    quote=writes[0][4][0]
    assert quote["source"]=="CARDMARKET_BULK_SINGLES"
    assert quote["reference_identity"]["set_id"]=="428602"
    assert quote["reference_printing_id"]==source["provider_id"]
    assert quote["condition_specific"] is False
    assert quote["physical_language_confirmed"] is False
    assert writes[0][5]==103 # €1.21 at 0.85, GBP pennies, half-up


def test_replay_2048_seeded_near_duplicate_conflicts_never_choose_which_price():
    rng=Random(137210)
    for n in range(2048):
        source=ref()
        m=product()
        pack=packaging()
        source["name"]=f"Official identity {n}"
        m["name"]=source["name"]
        products={"one":m}
        packs={"release":pack}
        if rng.choice([True,False]):
            products["conflict"]={**m,"idProduct":rng.randint(3000000,5000000)}
        else:
            packs["conflict"]={**pack,"idExpansion":rng.randint(3000000,5000000)}
        assert exact_masters_supplemental_matches([source],products,packs)=={}
