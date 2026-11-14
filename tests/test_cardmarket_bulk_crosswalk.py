"""Exact historical source-ID -> official Cardmarket daily export safeguards."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from app.cardmarket_bulk_crosswalk import match_pokemon_bulk, SCHEMA
from app.cardmarket_public_pilot import PilotError

NOW = datetime(2026, 11, 14, 14, tzinfo=timezone.utc)


def fixtures(count=1, *, explicit_set=True, reverse=False):
    stamp = (NOW - timedelta(hours=4)).isoformat()
    products = []
    guides = []
    links = []
    for i in range(count):
        product_id = 70000 + i
        name = f"Card {i}"
        products.append({
            "idProduct": product_id, "name": name,
            "categoryName": "Pokemon Single", "idCategory": 51,
            "idExpansion": 123, "number": str(i + 1),
            **({"expansionName": "Example Set"} if explicit_set else {}),
        })
        guides.append({
            "idProduct": product_id, "idCategory": 51,
            "avg7": 2.50, "avg7-holo": 3.75,
            "trend": 4000, "low": 0.05, "avg30": 5.00,
        })
        links.append({
            "provider": "TCGdex", "system_code": "POKEMON_TCG",
            "language": "English", "provider_id": f"set-{i+1}",
            "name": name, "set_name": "Example Set",
            "card_number": f"{i+1:03d}/100",
            "cardmarket_id": str(product_id),
            "source": "TCGDEX_CARDMARKET",
            "source_field": "trend-holo" if reverse else "trend",
            "finish": "Reverse Holofoil" if reverse else "Normal",
            "variant_id": f"variant-{i}",
        })
    return links, {"version": 1, "createdAt": stamp, "products": products}, {
        "version": 1, "createdAt": stamp, "priceGuides": guides
    }


def run(links=None, products=None, guides=None, count=1, **kwargs):
    l, p, g = fixtures(count, **kwargs)
    return match_pokemon_bulk(links=l if links is None else links,
                              products_export=p if products is None else products,
                              price_export=g if guides is None else guides, now=NOW)


def test_direct_source_id_and_exact_set_produces_candidate_only():
    l, p, g = fixtures()
    before = deepcopy((l, p, g))
    result = run(l, p, g)
    assert (l, p, g) == before
    assert result["schema"] == SCHEMA
    assert result["candidate_count"] == 1
    assert result["canonical_references_covered"] == 1
    assert result["physical_market_value_eligible"] == 0
    assert result["writes"] == {"supabase": 0, "shopify": 0, "retail": 0}
    c = result["candidates"][0]
    assert c["daily_guide_eur_minor"] == 250
    assert c["source_field"] == "avg7"
    assert c["match_basis"] == "EXPLICIT_SET_AND_TRUSTED_SOURCE_ID"
    assert c["is_exact_variant"] is True
    assert c["publishable"] is False and c["physical_valuation_eligible"] is False
    assert c["grade_specific"] is False and c["language_specific_guide"] is False


def test_reverse_holo_matches_own_source_column_and_no_active_asking():
    l, p, g = fixtures(reverse=True)
    result = run(l, p, g)
    assert result["candidate_count"] == 1
    c = result["candidates"][0]
    assert c["source_field"] == "avg7-holo"
    assert c["daily_guide_eur_minor"] == 375
    assert c["finish"] == "Reverse Holofoil"


def test_official_attack_bracket_suffix_requires_direct_product_id():
    links, products, guides = fixtures()
    products["products"][0]["name"] = "Card 0 [Move One | Move Two]"
    report = run(links, products, guides)
    assert report["candidate_count"] == 1
    assert report["exact_variant_candidate_count"] == 1


def test_bracket_suffix_cannot_loosen_number_only_cardtrader_mapping():
    links, products, guides = fixtures()
    products["products"][0]["name"] = "Card 0 [Move One | Move Two]"
    links[0].update(source="CARDMARKET_CATALOGUE", finish="Printing guide",
                    variant_id=None,
                    match_basis="CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID")
    assert run(links, products, guides)["candidate_count"] == 0


def test_character_name_prefix_does_not_match_different_printing():
    links, products, guides = fixtures()
    products["products"][0]["name"] = "Card 0 V [Different printing]"
    result = run(links, products, guides)
    assert result["candidate_count"] == 0
    assert result["rejections"]["NAME_MISMATCH"] == 1


def test_product_name_only_never_creates_printing_mapping():
    l, p, g = fixtures()
    l[0]["cardmarket_id"] = "unknown"
    result = run(l, p, g)
    assert result["candidate_count"] == 0
    assert result["rejections"]["INVALID_TRUSTED_SOURCE_LINK"] == 1


@pytest.mark.parametrize("changed", ["name", "number", "expansionName", "categoryName"])
def test_wrong_identity_is_rejected(changed):
    l, p, g = fixtures()
    p["products"][0][changed] = "wrong"
    result = run(l, p, g)
    assert result["candidate_count"] == 0


def test_expansion_without_explicit_set_requires_eight_independent_names():
    l, p, g = fixtures(7, explicit_set=False)
    assert run(l, p, g)["candidate_count"] == 0
    l, p, g = fixtures(8, explicit_set=False)
    result = run(l, p, g)
    assert result["candidate_count"] == 8
    assert all(x["match_basis"] == "EIGHT_NAME_COHORT_AND_TRUSTED_SOURCE_ID"
               for x in result["candidates"])


def test_repeated_name_does_not_satisfy_eight_anchor_rule():
    l, p, g = fixtures(8, explicit_set=False)
    for link, product in zip(l, p["products"]):
        link["name"] = product["name"] = "Identical reprint"
    result = run(l, p, g)
    assert result["candidate_count"] == 0


def test_reused_product_id_across_two_canonical_references_quarantined():
    l, p, g = fixtures()
    other = deepcopy(l[0])
    other["provider_id"] = "another-printing"
    l.append(other)
    result = run(l, p, g)
    assert result["provider_ids_conflicting"] == 1
    assert result["candidate_count"] == 0


def test_reused_id_across_languages_quarantined():
    l, p, g = fixtures()
    other = deepcopy(l[0])
    other["language"] = "Japanese"
    l.append(other)
    assert run(l, p, g)["candidate_count"] == 0


def test_same_product_and_field_but_different_variant_quarantined():
    l, p, g = fixtures()
    other = deepcopy(l[0])
    other["variant_id"] = "other-variant"
    l.append(other)
    result = run(l, p, g)
    assert result["variant_price_slots_conflicting"] == 1
    assert result["candidate_count"] == 0


@pytest.mark.parametrize("bad", [False, -1, 0, "NaN", "Infinity", 1.001, 1000001])
def test_bad_7day_guide_no_30day_or_low_fallback(bad):
    l, p, g = fixtures()
    g["priceGuides"][0]["avg7"] = bad
    assert run(l, p, g)["candidate_count"] == 0


def test_number_only_cardtrader_match_is_not_variant_proof():
    l, p, g = fixtures()
    l[0].update(source="CARDMARKET_CATALOGUE", finish="Printing guide",
                variant_id=None, match_basis="CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID")
    candidate = run(l, p, g)["candidates"][0]
    assert candidate["is_exact_variant"] is False
    assert candidate["physical_valuation_eligible"] is False


def test_name_only_cardtrader_match_is_not_admitted():
    l, p, g = fixtures()
    l[0].update(source="CARDMARKET_CATALOGUE", finish="Printing guide",
                variant_id=None, match_basis="UNIQUE_NAME_IN_COMPLETE_RELEASE_CHECKLISTS")
    result = run(l, p, g)
    assert result["candidate_count"] == 0


def test_duplicate_provider_id_in_catalogue_or_guide_fails_closed():
    l, p, g = fixtures()
    p["products"].append(deepcopy(p["products"][0]))
    with pytest.raises(PilotError, match="duplicate"):
        run(l, p, g)
    l, p, g = fixtures()
    g["priceGuides"].append(deepcopy(g["priceGuides"][0]))
    with pytest.raises(PilotError, match="duplicate"):
        run(l, p, g)


def test_unreviewed_payload_version_and_stale_exports_fail_closed():
    l, p, g = fixtures()
    p["version"] = 2
    with pytest.raises(PilotError, match="version"):
        run(l, p, g)
    l, p, g = fixtures()
    p["createdAt"] = (NOW - timedelta(days=4)).isoformat()
    with pytest.raises(PilotError, match="stale"):
        run(l, p, g)


def test_wrong_price_category_blocked():
    l, p, g = fixtures()
    g["priceGuides"][0]["idCategory"] = 101
    result = run(l, p, g)
    assert result["candidate_count"] == 0
    assert result["rejections"]["PRICE_CATEGORY_MISMATCH"] == 1


def test_unbounded_links_blocked():
    l, p, g = fixtures()
    with pytest.raises(PilotError, match="unbounded"):
        run(l * 120001, p, g)
