"""Observed legacy Masters imports use exact, finish-specific read-only guides."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from uuid import uuid4

import pytest

from app.inventory_catalogue_reference import catalogue_guide,catalogue_system,reference_candidates,add_catalogue_references,PRODUCTS_SQL
from app.catalogue_display_prices import read_shared_prices,reference_key
from app.recognition_games import SYSTEM_BY_GAME

NOW=datetime(2026,10,26,23,tzinfo=timezone.utc)
MASTERS="DRAGON_BALL_SUPER_MASTERS"


def fixture():
    product=dict(id=uuid4(),product_type="CARD",game="Dragon Ball Super",
        profile_system_code=MASTERS,name="A Sudden Escape",set_name="Supreme Rivalry",
        card_number="BT13-029",rarity="Common",variant="Normal",language="English",blocked=False)
    row=dict(catalogue_id=str(product["id"]),provider="Bandai Official",system_code=MASTERS,
        language="English",provider_id="428013:BT13-029.png",set_id="428013",
        name="A Sudden Escape",card_number="BT13-029",rarity="Common[C]",
        set_name="UW04 Booster -Supreme Rivalry-",catalogue_quotes=[])
    quote=dict(source="CARDMARKET_BULK_SINGLES",product_id="549841",expansion_id=3796,
        match_basis="UNIQUE_RELEASE_AND_PRINTING_IN_BOTH_CHECKLISTS",
        finish="Normal",source_field="trend",valuation_role="MIXED_LANGUAGE_REFERENCE",
        condition_specific=False,physical_language_confirmed=False,
        reference_printing_id=row["provider_id"],reference_rarity=row["rarity"],
        reference_identity={k:row[k] for k in ("name","set_id","card_number","set_name")},
        observed_at="2026-10-26T02:47:35+01:00",original_currency="EUR",original_minor=4,
        price_gbp_minor=3,fx_source="ECB_EURO_REFERENCE_RATES",fx_rate_to_gbp="0.8382")
    row["quotes"]=[quote,dict(quote,finish="Holofoil",source_field="trend-foil",original_minor=13,price_gbp_minor=11)]
    return product,row,quote


def test_observed_normal_guide_does_not_include_the_foil_price_or_mutate_inputs():
    product,row,quote=fixture()
    before=deepcopy((product,row))
    guide=catalogue_guide(product,[row],"English",now=NOW)
    assert guide["market_value_minor"]==guide["market_value_high_minor"]==3
    assert guide["checked_at"]==datetime.fromisoformat(quote["observed_at"])
    assert guide["label"]=="Normal finish guide" and guide["physical_valuation_eligible"] is False
    assert guide["recommended_retail_minor"] is None
    assert (product,row)==before
    product["variant"]="Foil"
    guide=catalogue_guide(product,[row],"English",now=NOW)
    assert guide["market_value_minor"]==guide["market_value_high_minor"]==11
    assert guide["label"]=="Foil finish guide"


@pytest.mark.parametrize("change",[
    {"profile_system_code":None},{"profile_system_code":"DRAGON_BALL_SUPER_FUSION_WORLD"},
    {"language":None},{"language":"Japanese"},{"set_name":"Supreme Rivalry Pre-Release Cards"},
    {"set_name":"Unknown Release"},{"card_number":"BT13-029_PR1"},{"card_number":"BT18-029"},
    {"name":"A Different Card"},{"name":"A Sudden Escape // Other Face"},
    {"variant":"Alternate Art"},{"rarity":"Unknown"},{"blocked":True},
])
def test_legacy_profile_release_and_printing_must_match(change):
    product,row,_=fixture();product.update(change)
    assert catalogue_guide(product,[row],"English",now=NOW) is None


def test_legacy_label_is_not_a_global_game_alias():
    product,_,_=fixture()
    assert catalogue_system(product)==MASTERS
    assert "Dragon Ball Super" not in SYSTEM_BY_GAME
    product.pop("profile_system_code")
    assert catalogue_system(product) is None
    assert "profile.system_code" in PRODUCTS_SQL and "profile.catalogue_id=p.id" in PRODUCTS_SQL


@pytest.mark.parametrize("change",[
    {"provider":"Other"},{"language":"Japanese"},{"set_id":"different"},
    {"set_name":"Promotion"},{"provider_id":"428013:BT13-029_p1.png"},
    {"card_number":"BT13-030"},{"rarity":"Super Rare[SR]"},{"name":"Wrong Name"},
])
def test_official_identity_is_not_inferred_from_price_availability(change):
    product,row,_=fixture();row.update(change)
    assert catalogue_guide(product,[row],"English",now=NOW) is None


def test_unpriced_same_rarity_parallel_and_unclassified_sibling_block_resolution():
    product,row,_=fixture()
    parallel=dict(row,provider_id="428013:BT13-029_p1.png",quotes=[])
    assert reference_candidates(product,[row,parallel],"English")==[]
    parallel["rarity"]="Unrecognised"
    assert reference_candidates(product,[row,parallel],"English")==[]


@pytest.mark.parametrize("change",[
    {"source":"CARDMARKET_CATALOGUE"},{"reference_identity":{}},{"reference_printing_id":"wrong"},
    {"reference_rarity":"Rare[R]"},{"reference_language":"Japanese"},
    {"valuation_role":"EXACT_VALUE"},{"physical_language_confirmed":True},
    {"condition_specific":True},{"physical_valuation_eligible":True},{"physical_valuation_eligible":0},
    {"source_field":"low"},{"product_id":"0"},{"expansion_id":True},
    {"match_basis":"NAME_ONLY"},{"price_gbp_minor":999},{"original_currency":"USD"},
    {"observed_at":(NOW-timedelta(days=8)).isoformat()},
])
def test_source_and_fx_proof_is_required(change):
    product,row,quote=fixture();quote.update(change)
    assert catalogue_guide(product,[row],"English",now=NOW) is None


def test_an_unpriced_competing_source_product_cannot_be_ignored():
    product,row,quote=fixture()
    row["quotes"].append(dict(quote,product_id="999999",price_gbp_minor=None))
    assert catalogue_guide(product,[row],"English",now=NOW) is None


def piccolo_fixture():
    product,row,quote=fixture()
    product.update(name="Piccolo, Combo With an Old Enemy",set_name="Perfect Combination",
        card_number="BT23-048",rarity="Super Rare",variant="Foil")
    row.update(name=product["name"],set_id="428023",set_name="Z06 Booster -PERFECT COMBINATION-",
        card_number="BT23-048",provider_id="428023:BT23-048.png",rarity="Super Rare[SR]")
    quote.update(product_id="747944",expansion_id=5534,finish="Holofoil",source_field="trend-foil",
        original_minor=30,price_gbp_minor=25,reference_printing_id=row["provider_id"],
        reference_rarity=row["rarity"],reference_identity={k:row[k] for k in ("name","set_id","card_number","set_name")},
        match_basis="CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID",
        mapping_source="CARDTRADER",physical_valuation_eligible=False,
        cardtrader_blueprint_id=271644,cardtrader_expansion_id=3580,
        cardtrader_collector_number="BT23-048s",cardtrader_rarity="Super Rare",
        cardtrader_rarity_source="rarity",cardtrader_version="Super Rare")
    row["quotes"]=[quote]
    return product,row,quote


def test_cardtrader_proof_and_intrinsic_foil_super_rare_are_explicit():
    product,row,quote=piccolo_fixture()
    assert catalogue_guide(product,[row],"English",now=NOW)["market_value_minor"]==25
    product["variant"]="Normal"
    quote.update(finish="Normal",source_field="trend",original_minor=12,price_gbp_minor=10)
    assert catalogue_guide(product,[row],"English",now=NOW) is None


@pytest.mark.parametrize("change",[
    {"mapping_source":"OTHER"},{"cardtrader_blueprint_id":True},{"cardtrader_expansion_id":0},
    {"cardtrader_collector_number":"BT23-049s"},{"cardtrader_rarity":"Special Rare"},
    {"cardtrader_version":"Special Rare"},{"cardtrader_rarity_source":"guessed"},
    {"physical_valuation_eligible":None},
])
def test_cardtrader_bridge_metadata_cannot_silently_change_printing(change):
    product,row,quote=piccolo_fixture();quote.update(change)
    assert catalogue_guide(product,[row],"English",now=NOW) is None


@pytest.mark.asyncio
async def test_owner_and_catalogue_paths_share_guide_without_copy_money_changes():
    product,row,_=fixture()
    class Connection:
        async def fetch(self,sql,*args):
            if "snapshot_id" in sql:return []
            if "jsonb_to_recordset" in sql:
                lookups=json.loads(args[0]);assert lookups[0]["system_code"]==MASTERS
                return [row]
            return [product]
    item=dict(catalogue_id=product["id"],product_type="CARD",language="English",
        condition="Near Mint",store_price_minor=100,market_value_minor=None)
    await add_catalogue_references(Connection(),[item],now=NOW)
    assert item["catalogue_reference"]["market_value_minor"]==3
    assert item["market_value_minor"] is None and item["store_price_minor"]==100
    prices=await read_shared_prices(Connection(),[{"card_number":"BT13-029"}],now=NOW)
    assert prices["c:"+str(product["id"])]["market_value_minor"]==3
    assert prices[reference_key(row)]["shared_price"]["physical_valuation_eligible"] is False
