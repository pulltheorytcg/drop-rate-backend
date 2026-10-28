from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.reference_asking_estimator import (
    estimate_reference_asking_price,
    reference_asking_eligibility,
)


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def reference(**changes):
    value = {"provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "English",
             "provider_id": "base1-4", "set_id": "base1", "set_name": "Base Set",
             "name": "Charizard", "card_number": "4/102", "finish": "Holo", "rarity": "Rare",
             "evidence": {}, "reference_group_count": 1}
    value.update(changes)
    return value


def row(index=1, price="100.00", *, title=None, finish="Holo", **changes):
    value = {"itemId": f"v1|{100000000000 + index}|0", "seller": {"username": f"seller{index}"},
             "title": title or f"Pokemon Charizard 4/102 Base Set English {finish} Near Mint Ungraded",
             "price": {"currency": "GBP", "value": price}, "buyingOptions": ["FIXED_PRICE"],
             "shippingOptions": [{"shippingCost": {"currency": "GBP", "value": "0.00"}}],
             "itemLocation": {"country": "GB"}, "condition": "Near Mint or Better"}
    value.update(changes)
    return value


def estimate(rows=None, ref=None, **kwargs):
    return estimate_reference_asking_price(ref or reference(), rows if rows is not None else [row(1), row(2, "110"), row(3, "120")], observed_at=kwargs.pop("observed_at", NOW), now=kwargs.pop("now", NOW), **kwargs)


def test_free_shipping_is_known_and_delivered_median_is_asking_only():
    rows = [row(1, "100"), row(2, "100", shippingOptions=[{"shippingCost": {"currency": "GBP", "value": "10"}}]), row(3, "120")]
    result = estimate(rows)
    assert result["status"] == "READY"
    assert result["basis"] == "ASKING_PRICE_ESTIMATE"
    assert result["source"] == "EBAY_OFFICIAL_BROWSE"
    assert result["method_version"] == "EBAY_UK_RAW_ASK_V1"
    assert result["estimate_minor"] == result["price_gbp_minor"] == 11000
    assert (result["estimate_low_minor"], result["estimate_high_minor"]) == (10500, 11500)
    assert result["sample_count"] == result["seller_count"] == 3
    assert result["confidence"] == "LOW"
    assert result["evidence"]["finish"] == "Holo"
    assert result["evidence"]["condition"] == "Near Mint"
    assert result["physical_valuation_eligible"] is False
    assert "seller1" not in str(result)
    assert len(result["comparables"][0]["seller_hash"]) == 64
    assert result["expires_at"] == (NOW + timedelta(days=3)).isoformat()


def test_input_data_is_not_mutated():
    rows, ref = [row(1), row(2), row(3)], reference()
    before = deepcopy((rows, ref))
    estimate(rows, ref)
    assert (rows, ref) == before


@pytest.mark.parametrize("bad", [
    {"buyingOptions": ["AUCTION"]}, {"buyingOptions": ["FIXED_PRICE", "AUCTION"]},
    {"buyingOptions": None}, {"itemLocation": {"country": "US"}}, {"itemLocation": {}},
    {"price": {"currency": "USD", "value": "100"}},
    {"price": {"currency": "GBP", "value": "NaN"}},
    {"price": {"currency": "GBP", "value": "Infinity"}},
    {"price": {"currency": "GBP", "value": "-1"}},
    {"price": {"currency": "GBP", "value": "0"}},
    {"price": {"currency": "GBP", "value": "100.001"}},
    {"shippingOptions": None}, {"shippingOptions": []}, {"shippingOptions": [{}]},
    {"shippingOptions": [{"shippingCost": {"currency": "GBP", "value": None}}]},
    {"shippingOptions": [{"shippingCost": {"currency": "GBP", "value": "-1"}}]},
    {"shippingOptions": [{"shippingCost": {"currency": "USD", "value": "0"}}]},
    {"shippingOptions": [{"shippingCost": {"currency": "GBP", "value": "0"}}, {}]},
    {"itemId": ""}, {"seller": {}}, {"seller": {"username": " "}},
])
def test_missing_or_unsafe_transaction_details_fail_closed(bad):
    result = estimate([row(1, **bad), row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["estimate_minor"] is None


@pytest.mark.parametrize("suffix", ["PSA 10", "BGS 9.5", "CGC 10", "Beckett", "slab", "graded", "Gem Mint 10", "bundle", "lot of 2", "playset", "proxy", "replica", "custom", "digital", "x4", "4x", "choose your card", "First Edition", "Shadowless", "Reverse Holo", "Japanese", "LP", "Damaged"])
def test_non_comparable_title_is_rejected(suffix):
    bad = row(1)
    bad["title"] += " " + suffix
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["estimate_minor"] is None


@pytest.mark.parametrize("field,value", [("grading company", "PSA"), ("professional grader", "CGC"), ("grade", "10"), ("certification number", "123456")])
def test_structured_grading_evidence_rejected(field, value):
    bad = row(1, localizedAspects=[{"name": field, "value": value}])
    assert estimate([bad, row(2), row(3)])["status"] == "INSUFFICIENT_COMPARABLES"


@pytest.mark.parametrize("condition", ["Near Mint", "Mint", "NM", "Near Mint or Better", "Ungraded Near Mint", "Gem Mint Ungraded"])
def test_ordinary_raw_conditions_are_not_confused_with_grading(condition):
    rows = [row(i, title=f"Pokemon Charizard 4/102 Base Set English Holo {condition}", condition=condition) for i in range(3)]
    assert estimate(rows)["status"] == "READY"


@pytest.mark.parametrize("condition", [
    "Not Near Mint", "not mint", "not NM", "Not quite Near Mint",
    "Not in mint condition", "Non-mint", "isn't near mint", "No NM",
    "below Near Mint", "less than mint", "worse than NM", "far from mint",
])
@pytest.mark.parametrize("location", ["title", "aspect"])
def test_negative_raw_condition_overrides_positive_listing_label(condition, location):
    # Keep the ordinary provider condition positive: contradictions must still
    # exclude this seller from the minimum three-comparable estimate.
    bad = row(1)
    if location == "title":
        bad["title"] += " " + condition
    else:
        bad["localizedAspects"] = [{"name": "Card Condition", "value": condition}]
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["CONDITION_OUTSIDE_NM_MINT"] == 1
    assert result["estimate_minor"] is None


@pytest.mark.parametrize("denial,reason", [
    ("not English", "LANGUAGE_MISMATCH_OR_UNKNOWN"),
    ("not in English", "LANGUAGE_MISMATCH_OR_UNKNOWN"),
    ("not holo", "FINISH_MISMATCH_OR_UNKNOWN"),
    ("No holo", "FINISH_MISMATCH_OR_UNKNOWN"),
    ("not Charizard", "NAME_MISMATCH"),
    ("not Base Set", "SET_MISMATCH"),
])
def test_direct_identity_denial_cannot_supply_positive_match(denial, reason):
    bad = row(1, title=row(1)["title"] + " " + denial)
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"][reason] == 1


def test_denied_first_edition_is_not_exact_print_proof():
    ref = reference(reference_group_count=2, evidence={"variant_title_terms": ["First Edition"]})
    rows = [row(i, title=row(i)["title"] + " Not First Edition") for i in range(3)]
    result = estimate(rows, ref)
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["VARIANT_MISMATCH"] == 3


def test_explicit_non_holo_remains_a_valid_normal_finish():
    rows = [row(i, title=row(i)["title"].replace(" Holo ", " Non-Holo ")) for i in range(3)]
    assert estimate(rows, reference(finish="Normal"))["status"] == "READY"


@pytest.mark.parametrize("replacement", [
    ("Charizard", "Charmeleon"), ("4/102", "44/102"), ("4/102", "4/130"),
    ("Base Set", "Base Set 2"), ("Pokemon", "One Piece"), ("English", "Japanese"),
    ("English", ""), ("Holo", "Reverse Holo"),
])
def test_exact_identity_required(replacement):
    bad = row(1)
    bad["title"] = bad["title"].replace(*replacement)
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"


def test_multiple_card_identifiers_reject_a_disguised_bundle():
    bad = row(1)
    bad["title"] += " Blastoise 2/102"
    assert estimate([bad, row(2), row(3)])["status"] == "INSUFFICIENT_COMPARABLES"


def test_structured_language_and_finish_are_valid_explicit_evidence():
    rows = [row(i, title="Pokemon Charizard 4/102 Base Set Near Mint", localizedAspects=[{"name": "Language", "value": "English"}, {"name": "Finish", "value": "Holo"}]) for i in range(3)]
    assert estimate(rows)["status"] == "READY"


def test_conflicting_structured_language_is_rejected():
    assert estimate([row(i, localizedAspects=[{"name": "Language", "value": "Japanese"}]) for i in range(3)])["status"] == "INSUFFICIENT_COMPARABLES"


def test_one_piece_printed_set_code_and_name_are_exact():
    ref = reference(provider="Bandai Official", system_code="ONE_PIECE_CARD_GAME", provider_id="OP01-001", set_id="OP01", set_name=None, name="Roronoa Zoro", card_number="OP01-001", finish="Foil")
    rows = [row(i, title="One Piece Roronoa Zoro OP01-001 English Foil NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"
    rows[0]["title"] = rows[0]["title"].replace("OP01-001", "OP02-001")
    assert estimate(rows, ref)["status"] == "INSUFFICIENT_COMPARABLES"


def test_japanese_identity_is_not_destroyed_by_ascii_normalisation():
    ref = reference(name="リザードン", language="Japanese")
    rows = [row(i, title="Pokemon リザードン 4/102 Base Set Japanese Holo NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"
    rows[0]["title"] = rows[0]["title"].replace("リザードン", "ピカチュウ")
    assert estimate(rows, ref)["status"] == "INSUFFICIENT_COMPARABLES"


@pytest.mark.parametrize("change,reason", [
    ({"name": ""}, "MISSING_CANONICAL_IDENTITY"),
    ({"language": "Unknown"}, "UNSUPPORTED_GAME_OR_LANGUAGE"),
    ({"system_code": "UNKNOWN"}, "UNSUPPORTED_GAME_OR_LANGUAGE"),
    ({"finish": "Unknown"}, "UNSUPPORTED_FINISH"),
    ({"set_name": None}, "MISSING_SET_IDENTITY"),
    ({"ambiguous_variant": True}, "UNRESOLVED_PARALLEL_IDENTITY"),
    ({"reference_group_count": 2}, "UNRESOLVED_PARALLEL_IDENTITY"),
    ({"evidence": {"provider_variant": "_p1"}}, "UNRESOLVED_PARALLEL_IDENTITY"),
])
def test_unresolved_reference_skips_acquisition(change, reason):
    ref = reference(**change)
    assert reference_asking_eligibility(ref) == reason
    result = estimate(ref=ref)
    assert result["status"] == "IDENTITY_UNSUPPORTED"
    assert result["estimate_minor"] is None


def test_approved_exact_print_terms_allow_an_ambiguous_reference():
    ref = reference(reference_group_count=2, evidence={"variant_title_terms": ["First Edition"]})
    rows = [row(i, title="Pokemon Charizard 4/102 Base Set English Holo First Edition NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"
    rows[0]["title"] = rows[0]["title"].replace("First Edition", "")
    assert estimate(rows, ref)["status"] == "INSUFFICIENT_COMPARABLES"


def test_unknown_canonical_finish_uses_one_proven_finish_bucket_without_changing_identity():
    ref = reference(finish=None, evidence={"physical_finish_unresolved": True, "shared_finish_artwork": True})
    rows = [row(i, finish="Holo", price="100") for i in range(3)] + [row(i + 10, finish="Reverse Holo", price="900") for i in range(2)]
    result = estimate(rows, ref)
    assert result["status"] == "READY"
    assert result["estimate_minor"] == 10000
    assert result["sample_count"] == 3
    assert result["selected_finish"] == "Holo"
    assert result["identity"]["finish"] is None
    assert result["physical_valuation_eligible"] is False


def test_three_mixed_finish_listings_cannot_create_a_comparable_cohort():
    rows = [row(1, finish="Normal"), row(2, finish="Holo"), row(3, finish="Reverse Holo")]
    assert estimate(rows, reference(finish=None))["status"] == "INSUFFICIENT_COMPARABLES"


def test_finish_tie_uses_stable_order_not_cheapest_median():
    rows = [row(i, finish="Normal", price="200") for i in range(3)] + [row(i + 10, finish="Holo", price="100") for i in range(3)]
    result = estimate(rows, reference(finish=None))
    assert result["selected_finish"] == "Normal"
    assert result["estimate_minor"] == 20000


def test_unstated_or_conflicting_finish_is_never_inferred_as_normal():
    for finish in ("", "Non Holo Holo", "Reverse"):
        assert estimate([row(i, finish=finish) for i in range(3)], reference(finish=None))["status"] == "INSUFFICIENT_COMPARABLES"


def test_same_item_ids_and_seller_alias_case_do_not_inflate_evidence():
    rows = [row(1), row(1), row(2, seller={"username": "SELLER1"}), row(3)]
    result = estimate(rows)
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["sample_count"] == 2
    assert result["rejection_counts"]["DUPLICATE_ITEM"] == 1
    assert result["rejection_counts"]["DUPLICATE_SELLER"] == 1


def test_duplicate_id_conflicts_quarantine_all_versions():
    rows = [row(1, "100"), row(1, "200"), row(2), row(3)]
    result = estimate(rows)
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["CONFLICTING_DUPLICATE_ITEM"] == 2


def test_browse_id_and_plain_legacy_id_are_the_same_listing():
    rows = [row(1), row(2, itemId="100000000001", seller={"username": "seller1"}), row(3)]
    assert estimate(rows)["sample_count"] == 2


def test_multiple_same_seller_listings_count_once_using_lowest_delivered_price():
    rows = [row(1, "100"), row(2, "400", seller={"username": "seller1"}), row(3, "110"), row(4, "120")]
    result = estimate(rows)
    assert result["status"] == "READY"
    assert result["sample_count"] == 3
    assert result["estimate_minor"] == 11000


def test_robust_median_removes_large_outlier_and_still_requires_three_sellers():
    result = estimate([row(i, price=str(price)) for i, price in enumerate([100, 100, 100, 1000])])
    assert result["status"] == "READY"
    assert result["estimate_minor"] == 10000
    assert result["sample_count"] == 3
    assert result["rejection_counts"]["PRICE_OUTLIER"] == 1
    assert estimate([row(1, "100"), row(2, "100"), row(3, "1000")])["status"] == "INSUFFICIENT_COMPARABLES"


def test_widely_dispersed_comparables_do_not_publish_an_estimate():
    result = estimate([row(i, str(price)) for i, price in enumerate([60, 80, 100, 120, 140])])
    assert result["status"] == "EXCESSIVE_DISPERSION"
    assert result["estimate_minor"] is None


def test_more_sellers_increases_confidence_only_to_medium_for_asking_prices():
    result = estimate([row(i, "100") for i in range(10)])
    assert result["confidence"] == "MEDIUM"


@pytest.mark.parametrize("observed,current,status", [
    (NOW, NOW + timedelta(days=3), "STALE_EVIDENCE"),
    (NOW, NOW + timedelta(days=4), "STALE_EVIDENCE"),
    (NOW + timedelta(seconds=1), NOW, "INVALID_EVIDENCE_TIME"),
    (NOW.replace(tzinfo=None), NOW, "INVALID_EVIDENCE_TIME"),
    (NOW, NOW.replace(tzinfo=None), "INVALID_EVIDENCE_TIME"),
])
def test_invalid_future_or_expired_acquisition_is_fail_closed(observed, current, status):
    result = estimate(observed_at=observed, now=current)
    assert result["status"] == status
    assert result["estimate_minor"] is None


def test_rerunning_does_not_refresh_expiry():
    result = estimate(now=NOW + timedelta(days=2))
    assert result["status"] == "READY"
    assert result["expires_at"] == (NOW + timedelta(days=3)).isoformat()


def test_malformed_rows_do_not_raise_or_become_prices():
    result = estimate([None, "bad", {}, row(1)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["sample_count"] == 1


def test_output_is_deterministic_under_input_order():
    rows = [row(1), row(2, "110"), row(3, "120"), row(4, "1000")]
    assert estimate(rows) == estimate(list(reversed(rows)))


@pytest.mark.parametrize("suffix", ["10x", "x10", "2 cards", "Charizard ex", "GX", "V", "VMAX", "VSTAR", "Radiant", "Shining", "Shiny", "Tera"])
def test_multiples_and_distinct_pokemon_prints_are_not_base_card_comps(suffix):
    bad = row(1)
    bad["title"] += " " + suffix
    assert estimate([bad, row(2), row(3)])["status"] == "INSUFFICIENT_COMPARABLES"


@pytest.mark.parametrize("changes", [
    {"itemEndDate": "2026-10-28T11:59:00Z"}, {"itemEndDate": "2026-10-28T12:00:00Z"},
    {"itemEndDate": "2026-10-28T13:00:00"}, {"itemEndDate": "bad"},
    {"itemEndDate": 123}, {"currentBidPrice": {"value": "100", "currency": "GBP"}},
    {"bidCount": 1}, {"buyingOptions": ["FIXED_PRICE", "CLASSIFIED_AD"]},
])
def test_ended_listings_or_conflicting_auction_evidence_are_rejected(changes):
    assert estimate([row(i, **changes) for i in range(3)])["status"] == "INSUFFICIENT_COMPARABLES"


def test_fixed_price_best_offer_remains_an_asking_price():
    result = estimate([row(i, buyingOptions=["FIXED_PRICE", "BEST_OFFER"], itemEndDate="2026-10-29T00:00:00Z") for i in range(3)])
    assert result["status"] == "READY"
    assert result["basis"] == "ASKING_PRICE_ESTIMATE"


def test_provider_id_alone_can_reveal_unresolved_parallel_identity():
    assert reference_asking_eligibility(reference(provider_id="100:OP01-001_p2")) == "UNRESOLVED_PARALLEL_IDENTITY"


def test_reprint_set_code_cannot_ride_alongside_original_card_code():
    ref = reference(system_code="ONE_PIECE_CARD_GAME", provider_id="OP01-001", set_id="OP01", set_name=None, name="Roronoa Zoro", card_number="OP01-001", finish="Foil")
    rows = [row(i, title="One Piece Roronoa Zoro OP01-001 PRB01 English Foil NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "INSUFFICIENT_COMPARABLES"


def test_ordinary_set_word_collection_is_not_a_bundle_on_its_own():
    ref = reference(set_name="Legendary Collection", set_id="base6", provider_id="base6-3", card_number="3/110")
    rows = [row(i, title="Pokemon Charizard 3/110 Legendary Collection English Holo NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"


@pytest.mark.parametrize("suffix", ["TAG 10", "ACE 10", "ARS 10", "KSA 10", "MNT 9.5", "AGS 10", "HGA 9", "GMA 10", "PSA10", "BGS9.5", "CGC10", "TAG10", "pair", "two cards", "set of 3", "2-card", "2 card"])
def test_other_graders_and_written_quantities_cannot_enter_raw_single_cohort(suffix):
    rows = [row(i, title=row(i)["title"] + " " + suffix) for i in range(3)]
    assert estimate(rows)["status"] == "INSUFFICIENT_COMPARABLES"


@pytest.mark.parametrize("name,value", [("Features", "1st Edition"), ("Features", "Shadowless"), ("Card Condition", "Very Good"), ("Card Condition", "Excellent"), ("Card Condition", "Fair")])
def test_structured_aspects_cannot_contradict_title_variant_or_condition(name, value):
    rows = [row(i, localizedAspects=[{"name": name, "value": value}]) for i in range(3)]
    assert estimate(rows)["status"] == "INSUFFICIENT_COMPARABLES"


def test_portgas_d_ace_is_a_card_name_not_a_grading_company():
    ref = reference(system_code="ONE_PIECE_CARD_GAME", provider_id="OP02-013", set_id="OP02", set_name=None, name="Portgas D Ace", card_number="OP02-013", finish="Foil")
    rows = [row(i, title="One Piece Portgas D Ace OP02-013 English Foil NM Not Graded") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"


@pytest.mark.parametrize("system,game_title", [
    ("POKEMON_TCG", "Pokemon"), ("ONE_PIECE_CARD_GAME", "One Piece"),
    ("DRAGON_BALL_SUPER_FUSION_WORLD", "Dragon Ball Super Fusion World"),
    ("DRAGON_BALL_SUPER_MASTERS", "Dragon Ball Super Card Game Masters"),
    ("NARUTO_BANDAI_LEGACY", "Naruto Card Game Bandai"),
    ("NARUTO_KAYOU", "Naruto Trading Card Kayou"),
])
def test_supported_game_identity_requires_all_game_discriminators(system, game_title):
    ref = reference(system_code=system, provider_id="universe-1", set_id="universe", set_name="Universe Set", name="Testcard", card_number="1/100", finish="Normal")
    rows = [row(i, title=f"{game_title} Testcard 1/100 Universe Set English Normal NM") for i in range(3)]
    assert estimate(rows, ref)["status"] == "READY"
