"""No network, no R2, no Supabase: exact Cardmarket daily source pilot contracts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.cardmarket_public_pilot import PilotError, read_only_mtg_pilot, SOURCE, SCHEMA
from app.fx import ECB_SOURCE, FxQuote

NOW = datetime(2026,11,5,12,tzinfo=timezone.utc)
CARD_ID = "2db28f9c-776b-45d0-9ab3-14bfe0862ff9"
CARD = {"uuid": CARD_ID,"name":"Fixture Legend","set_name":"Example Edition",
        "language":"English","paper":True,"finishes":["nonfoil","foil"],
        "identifiers":{"mcmId":"12345"}}


def _fixtures():
    products={"createdAt":(NOW-timedelta(hours=5)).isoformat(),
      "products":[{"idProduct":12345,"categoryName":"Magic Single",
                   "name":"Fixture Legend","expansionName":"Example Edition"}]}
    guides={"createdAt":(NOW-timedelta(hours=4)).isoformat(),
      "priceGuides":[{"idProduct":12345,"trend":1.25,"avg30":1.22,
                      "trend-foil":2.50,"avg30-foil":2.22}]}
    fx=FxQuote(base_currency="EUR", quote_currency="GBP", rate=Decimal(".8"),
               source=ECB_SOURCE,effective_at=NOW-timedelta(hours=10),
               retrieved_at=NOW-timedelta(hours=2))
    return [deepcopy(CARD)],products,guides,fx


def run(cards=None,products=None,guides=None,fx=None,now=NOW):
    base = _fixtures()
    return read_only_mtg_pilot(mtg_cards=base[0] if cards is None else cards,
        products_export=base[1] if products is None else products,
        price_export=base[2] if guides is None else guides,
        fx=base[3] if fx is None else fx,now=now)


def test_exact_id_release_and_finish_is_read_only_and_not_a_sold_value():
    cards,products,guides,fx=_fixtures()
    before=deepcopy((cards,products,guides))
    report=run(cards,products,guides,fx)
    assert report["schema"] == SCHEMA
    assert report["status"] == "PILOT_ONLY_NO_PUBLICATION"
    assert report["candidate_count"] == 2
    assert report["verified_sold_value_count"] == 0
    assert report["database_writes"] == report["object_storage_writes"] == 0
    assert [c["finish"] for c in report["candidates"]] == ["foil","nonfoil"]
    assert [c["guide_gbp_minor"] for c in report["candidates"]] == [200,100]
    assert set(c["source_field"] for c in report["candidates"]) == {"trend","trend-foil"}
    assert all(c["source"]==SOURCE and c["sold_observation_count"]==0
        and c["physical_valuation_eligible"] is False and c["publishable"] is False
        and c["provider_id"].startswith("mtgjson:"+str(UUID(CARD_ID))+":")
        and "market_value_minor" not in c for c in report["candidates"])
    assert (cards,products,guides)==before


@pytest.mark.parametrize("change", [
    {"name":"Wrong identity"}, {"set_name":"Wrong release"},
    {"language":"Japanese"}, {"paper":False}, {"identifiers":{"mcmMetaId":"12345"}},
    {"identifiers":{"mcmId":"-1"}}, {"finishes":["etched"]},
    {"finishes":["foil","foil"]}, {"uuid":"invalid"}, {"name":""},
])
def test_unconfirmed_mtg_identity_never_generates_a_guide(change):
    card=deepcopy(CARD)
    card.update(change)
    report=run(cards=[card])
    assert report["candidate_count"]==0


@pytest.mark.parametrize("change", [
    {"name":"Wrong identity"}, {"expansionName":"Wrong release"},
    {"categoryName":"Magic Sealed"},
])
def test_wrong_cardmarket_product_never_matches(change):
    _,products,_,_=_fixtures()
    products["products"][0].update(change)
    result=run(products=products)
    assert result["candidate_count"]==0
    expected = ("NAME_MISMATCH" if "name" in change else
                "SET_NAME_MISMATCH" if "expansionName" in change else "CATEGORY_MISMATCH")
    assert result["rejected"]=={expected:1}


def test_same_mcm_id_for_two_distinct_printings_is_quarantined():
    other=deepcopy(CARD)
    other["uuid"]="4197c8ab-826c-4214-b95f-0014d223f002"
    result=run(cards=[deepcopy(CARD),other])
    assert result["crosswalk_collision_ids"]==1
    assert result["candidate_count"]==0


@pytest.mark.parametrize("money", [False,"NaN","Infinity",-1,1e100])
def test_invalid_primary_guide_fail_closed_without_asking_price_fallback(money):
    _,_,guides,_=_fixtures()
    guides["priceGuides"][0]["trend"]=money
    result=run(guides=guides)
    assert all(c["finish"]=="foil" for c in result["candidates"])


def test_missing_trend_may_use_explicit_30_day_same_finish_aggregate():
    _,_,guides,_=_fixtures()
    guides["priceGuides"][0]["trend"]=0
    result=run(guides=guides)
    nonfoil=next(c for c in result["candidates"] if c["finish"]=="nonfoil")
    assert nonfoil["source_field"]=="avg30"
    assert nonfoil["guide_gbp_minor"]==98


@pytest.mark.parametrize("source",["products","priceGuides"])
def test_duplicate_provider_ids_abort_not_pick_a_priced_duplicate(source):
    _,products,guides,_=_fixtures()
    payload=products if source=="products" else guides
    payload[source].append(deepcopy(payload[source][0]))
    with pytest.raises(PilotError,match="duplicate"):run(products=products,guides=guides)


def test_stale_future_export_and_unsafe_ecb_fx_are_rejected():
    _,products,guides,fx=_fixtures()
    products["createdAt"]=(NOW-timedelta(days=4)).isoformat()
    with pytest.raises(PilotError,match="stale"):run(products=products)
    products["createdAt"]=(NOW+timedelta(minutes=1)).isoformat()
    with pytest.raises(PilotError,match="future"):run(products=products)
    products["createdAt"]=(NOW-timedelta(hours=1)).isoformat()
    badfx=FxQuote(base_currency="USD",quote_currency="GBP",rate=Decimal("1"),
                  source=ECB_SOURCE,effective_at=NOW-timedelta(hours=1),retrieved_at=NOW)
    with pytest.raises(PilotError,match="ECB"):run(products=products,fx=badfx)


def test_pilot_only_supports_explicit_english_paper_mtg_ids():
    _,products,guides,fx=_fixtures()
    no_paper=deepcopy(CARD)
    no_paper["paper"]=False
    report=run(cards=[no_paper],products=products,guides=guides,fx=fx)
    assert report["candidate_count"]==0

def test_corrupt_finish_list_and_nonfinite_fx_fail_without_exception_leak():
    invalid=deepcopy(CARD)
    invalid["finishes"]=[{"type":"foil"}]
    assert run(cards=[invalid])["candidate_count"] == 0
    _,_,_,fx=_fixtures()
    invalidfx=FxQuote(base_currency="EUR",quote_currency="GBP",rate=Decimal("NaN"),
                      source=ECB_SOURCE,effective_at=fx.effective_at,retrieved_at=fx.retrieved_at)
    with pytest.raises(PilotError,match="ECB"):
        run(fx=invalidfx)

def test_source_cards_only_extracts_actual_paper_printings():
    from scripts.pilot_cardmarket_public_daily_mtg import source_cards
    payload={"data":{"name":"Example Edition","cards":[
        {"uuid":CARD_ID,"name":"Fixture Legend","availability":["paper"],"finishes":["nonfoil"],
         "identifiers":{"mcmId":"12345"}},
        {"uuid":CARD_ID,"name":"Digital only","availability":["mtgo"],"finishes":["nonfoil"],
         "identifiers":{"mcmId":"12346"}},
    ]}}
    rows=source_cards(payload)
    assert len(rows)==1
    assert rows[0]["set_name"]=="Example Edition"
    assert rows[0]["language"]=="English"
    assert rows[0]["paper"] is True
    assert rows[0]["identifiers"]=={"mcmId":"12345"}


def cohort_sample(n: int = 9, *, prefix: int = 50000, set_name: str = "Example Edition",
                  expansion_id: int = 900) -> tuple[list[dict], dict, dict]:
    """Independent exact MCM-ID and NAME evidence, no provider sets invented."""
    _, products, guides, _ = _fixtures()
    products["products"] = []
    guides["priceGuides"] = []
    cards = []
    for i in range(n):
        source_id = prefix + i
        card = deepcopy(CARD)
        card["uuid"] = str(UUID(int=source_id))
        card["name"] = f"Fixture Card {source_id}"
        card["set_name"] = set_name
        card["identifiers"] = {"mcmId": str(source_id)}
        cards.append(card)
        products["products"].append({
            "idProduct": source_id, "name": card["name"], "categoryName": "Magic Single",
            "idExpansion": expansion_id, "expansionName": None,
        })
        guides["priceGuides"].append({
            "idProduct": source_id, "trend": 1.25, "trend-foil": 2.50,
        })
    return cards, products, guides


def test_numeric_expansion_id_works_only_after_multiple_independent_name_proofs():
    cards, products, guides = cohort_sample(9)
    originals = deepcopy((cards, products, guides))
    result = run(cards=cards, products=products, guides=guides)
    assert result["candidate_count"] == 18  # Nine exact IDs, two explicitly supported finishes
    assert result["expansion_cohorts_corroborated"] == 1
    assert result["expansion_ids_ambiguous"] == 0
    assert result["min_distinct_anchor_names"] >= 8
    assert all(value["expansion_evidence"] == "COHORT_CORROBORATED_PILOT"
               and value["match_basis"].endswith("CORROBORATED_EXPANSION_ID_V1")
               and value["cardmarket_expansion_id"] == 900
               and value["expansion_anchor_names"] == 9
               and value["physical_valuation_eligible"] is False
               and value["publishable"] is False
               and value["sold_observation_count"] == 0
               and "market_value_minor" not in value
               for value in result["candidates"])
    assert (cards, products, guides) == originals


def test_one_or_seven_matching_ids_cannot_guess_a_release_from_name():
    for count in (1, 7):
        cards, products, guides = cohort_sample(count)
        result = run(cards=cards, products=products, guides=guides)
        assert result["candidate_count"] == 0
        assert result["rejected"]["INSUFFICIENT_EXPANSION_PROOF"] == count


def test_two_different_source_sets_with_same_numeric_expansion_id_quarantine_both():
    first = cohort_sample(9, prefix=50000, set_name="Example Edition", expansion_id=900)
    second = cohort_sample(9, prefix=60000, set_name="Other Edition", expansion_id=900)
    cards = first[0] + second[0]
    products = deepcopy(first[1])
    products["products"] += second[1]["products"]
    guides = deepcopy(first[2])
    guides["priceGuides"] += second[2]["priceGuides"]
    result = run(cards=cards, products=products, guides=guides)
    assert result["candidate_count"] == 0
    assert result["expansion_ids_ambiguous"] == 1
    assert result["rejected"]["EXPANSION_ID_CONFLICT"] == 18


def test_explicit_wrong_release_never_override_with_numeric_cohort():
    cards, products, guides = cohort_sample(9)
    products["products"][0]["expansionName"] = "Wrong Edition"
    result = run(cards=cards, products=products, guides=guides)
    assert result["candidate_count"] == 16
    assert result["rejected"]["SET_NAME_MISMATCH"] == 1


@pytest.mark.parametrize("invalid_expansion", [None, "", "0", -1, False, "unknown"])
def test_missing_numeric_expansion_without_explicit_set_fails_closed(invalid_expansion):
    cards, products, guides = cohort_sample(9)
    products["products"][0]["idExpansion"] = invalid_expansion
    result = run(cards=cards, products=products, guides=guides)
    assert result["rejected"]["EXPANSION_ID_MISSING"] == 1
    assert result["candidate_count"] == 16


def test_fake_expansion_proof_with_only_repeated_card_name_is_rejected():
    cards, products, guides = cohort_sample(9)
    for card, product in zip(cards, products["products"]):
        card["name"] = product["name"] = "Same Reprinted Name"
    result = run(cards=cards, products=products, guides=guides)
    assert result["candidate_count"] == 0
    assert result["rejected"]["INSUFFICIENT_EXPANSION_PROOF"] == 9
