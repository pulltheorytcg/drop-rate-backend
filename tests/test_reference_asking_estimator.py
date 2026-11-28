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


def test_known_listing_end_time_survives_into_cached_comparable_evidence():
    end = (NOW + timedelta(hours=1)).isoformat()
    result = estimate([row(1, itemEndDate=end), row(2), row(3)])
    assert result["status"] == "READY"
    evidence = {item["item_id"]: item["listing_evidence"] for item in result["comparables"]}
    assert evidence["100000000001"]["item_end_date"] == end
    assert evidence["100000000002"]["item_end_date"] is None


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
    ("Holo", "Reverse Holo"),
])
def test_exact_identity_required(replacement):
    bad = row(1)
    bad["title"] = bad["title"].replace(*replacement)
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"


def unstated_language_rows(extra=""):
    return [row(i, str(100 + i), title=f"Pokemon Charizard 4/102 Base Set Holo Near Mint{extra}")
            for i in range(1, 4)]


def test_english_reference_accepts_a_uk_listing_that_names_no_language():
    # UK sellers rarely write "English" on an English card.
    result = estimate(unstated_language_rows())
    assert result["status"] == "READY"
    assert result["funnel"]["missing_language_evidence"] == 0


def test_japanese_reference_still_requires_the_language_to_be_named():
    result = estimate(unstated_language_rows(), reference(language="Japanese"))
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["LANGUAGE_MISMATCH_OR_UNKNOWN"] == 3
    assert result["funnel"]["missing_language_evidence"] == 3


@pytest.mark.parametrize("code", ["sv2a", "s12a", "SM12a", "s8b"])
def test_japanese_release_code_blocks_the_english_default(code):
    result = estimate(unstated_language_rows(" " + code))
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["LANGUAGE_MISMATCH_OR_UNKNOWN"] == 3


@pytest.mark.parametrize("language", ["Japanese", "German", "FR"])
def test_another_language_in_a_specific_overrides_the_english_default(language):
    rows = unstated_language_rows()
    rows[0]["localizedAspects"] = [{"name": "Language", "value": language}]
    result = estimate(rows)
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["LANGUAGE_MISMATCH_OR_UNKNOWN"] == 1


def test_unrelated_specifics_do_not_invent_a_bundle_grade_or_condition():
    # Joined specifics used to read as "2023 card" (a bundle), and a specific
    # worded "Good" or "Excellent" as the card's condition.
    aspects = [{"name": "Year Manufactured", "value": "2023"}, {"name": "Material", "value": "Card Stock"},
               {"name": "Character", "value": "Ace"}, {"name": "Features", "value": "Good Value"},
               {"name": "Professional Grader", "value": "Not Specified"},
               {"name": "Graded", "value": "No"}, {"name": "Grade", "value": "Does not apply"},
               {"name": "Certification Number", "value": "N/A"}]
    rows = [row(i, str(100 + i), localizedAspects=aspects) for i in range(1, 4)]
    assert estimate(rows)["status"] == "READY"


@pytest.mark.parametrize("field,value", [
    ("Professional Grader", "Professional Sports Authenticator (PSA)"),
    ("Grader", "ACE"), ("Grade", "9.5"), ("Graded", "Yes")])
def test_a_real_grading_specific_still_rejects(field, value):
    bad = row(1, localizedAspects=[{"name": field, "value": value}])
    result = estimate([bad, row(2), row(3)])
    assert result["rejection_counts"]["GRADED_OR_SLAB"] == 1


def test_bundle_wording_in_the_title_still_rejects():
    bad = row(1, title=row(1)["title"] + " 2 cards")
    assert estimate([bad, row(2), row(3)])["rejection_counts"]["MULTI_ITEM_OR_NON_PHYSICAL"] == 1


@pytest.mark.parametrize("aspect", ["010/025", "10 / 25", "10/025"])
def test_padded_collector_number_specific_is_the_same_number(aspect):
    ref = reference(name="Cyndaquil", card_number="10/25", set_name="McDonald's Collection 2021",
                    set_id="2021swsh", provider_id="2021swsh-10")
    rows = [row(i, str(100 + i), title="Cyndaquil 10/25 McDonald's Collection 2021 Holo Near Mint Pokemon Card",
                localizedAspects=[{"name": "Card Number", "value": aspect}]) for i in range(1, 4)]
    assert estimate(rows, ref)["status"] == "READY"


def moltres(**changes):
    return reference(name="Moltres", card_number="014/94", set_name="Phantasmal Flames", set_id="me02",
                     provider_id="me02-014", finish=None, rarity="Rare", **changes)


def moltres_rows(number_specific, title="Moltres 014/94 Holo Rare Phantasmal Flames Pokemon NM"):
    return [row(i, str(100 + i), title=title,
                localizedAspects=[{"name": "Card Number", "value": number_specific}]) for i in range(1, 4)]


@pytest.mark.parametrize("specific", ["014", "14"])
def test_number_specific_giving_only_the_part_before_the_slash_agrees(specific):
    # Seen in production: "Moltres 014/94 ..." with Card Number "014".
    assert estimate(moltres_rows(specific), moltres())["status"] == "READY"


@pytest.mark.parametrize("specific,title", [
    ("015", "Moltres 014/94 Holo Rare Phantasmal Flames Pokemon NM"),
    ("014", "Moltres Holo Rare Phantasmal Flames Pokemon NM"),  # the title must print the full number
])
def test_number_specific_shortcut_needs_the_same_number_and_the_full_title(specific, title):
    result = estimate(moltres_rows(specific, title), moltres())
    assert result["rejection_counts"]["CARD_NUMBER_MISMATCH"] == 3


@pytest.mark.parametrize("extra", ["Full Art", "Special Art", "full-art"])
def test_artwork_wording_on_a_numbered_card_does_not_reject(extra):
    # Sellers add "Full Art" freely; the name and number bind the card.
    rows = [row(i, str(100 + i), title=row(i)["title"] + " " + extra) for i in range(1, 4)]
    assert estimate(rows)["status"] == "READY"


def test_a_mega_ex_card_matches_a_title_that_also_says_full_art():
    ref = reference(name="Mega Charizard X ex", card_number="125/094", set_name="Phantasmal Flames",
                    set_id="me02", provider_id="me02-125", finish=None, rarity="Special illustration rare")
    rows = [row(i, str(100 + i),
                title="Pokemon Mega Charizard X ex 125/094 SIR Full Art Phantasmal Flames Holo NM")
            for i in range(1, 4)]
    assert estimate(rows, ref)["status"] == "READY"


@pytest.mark.parametrize("extra", ["First Edition", "Shadowless", "Stamped", "Promo", "Reprint",
                                   "Master Ball", "Alt Art", "Parallel", "VMAX", "Shiny", "Tera"])
def test_wording_that_separates_printings_of_one_number_still_rejects(extra):
    bad = row(1, title=row(1)["title"] + " " + extra)
    result = estimate([bad, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["estimate_minor"] is None


@pytest.mark.parametrize("value", ["Not Applicable", "Raw Card", "Unknown", "Ungraded / Raw", "N/A - raw"])
def test_raw_card_wording_in_a_grading_specific_is_not_a_slab(value):
    rows = [row(i, str(100 + i), localizedAspects=[{"name": "Professional Grader", "value": value}])
            for i in range(1, 4)]
    assert estimate(rows)["status"] == "READY"


@pytest.mark.parametrize("value", ["PSA", "CGC Trading Cards", "Ace Grading", "9", "Yes", "12345678"])
def test_a_grading_specific_that_names_a_grade_is_still_a_slab(value):
    bad = row(1, localizedAspects=[{"name": "Grade", "value": value}])
    assert estimate([bad, row(2), row(3)])["rejection_counts"]["GRADED_OR_SLAB"] == 1


def phantasmal(name="Zacian", number="100/94", rarity="Illustration rare", **changes):
    return reference(name=name, card_number=number, set_name="Phantasmal Flames", set_id="me02",
                     provider_id="me02-" + number.split("/")[0], finish=None, rarity=rarity, **changes)


def test_a_title_naming_the_release_proves_the_game():
    # Seen live: "100/94 - Zacian - Phantasmal Flames (Normal Holo)".
    rows = [row(i, str(100 + i), title="100/94 - Zacian - Phantasmal Flames Holo NM") for i in range(1, 4)]
    assert estimate(rows, phantasmal())["status"] == "READY"


def test_a_one_word_release_does_not_prove_the_game():
    ref = reference(name="Pikachu", card_number="025/165", set_name="151", set_id="sv03.5",
                    provider_id="sv03.5-025", finish="Holo", rarity="Common")
    rows = [row(i, str(100 + i), title="Pikachu 025/165 151 Holo NM") for i in range(1, 4)]
    assert estimate(rows, ref)["rejection_counts"]["GAME_MISMATCH"] == 3


def test_another_game_in_the_game_specific_still_rejects_a_release_named_title():
    rows = [row(i, str(100 + i), title="100/94 - Zacian - Phantasmal Flames Holo NM",
                localizedAspects=[{"name": "Game", "value": "Yu-Gi-Oh! TCG"}]) for i in range(1, 4)]
    assert estimate(rows, phantasmal())["status"] == "INSUFFICIENT_COMPARABLES"


def test_a_holo_only_rarity_supplies_the_finish_a_listing_leaves_out():
    # Seen live: "Pokemon TCG - Togedemaru 104/94 - IR Phantasmal Flames".
    ref = phantasmal(name="Togedemaru", number="104/94")
    rows = [row(i, str(100 + i), title="Pokemon TCG - Togedemaru 104/94 - IR Phantasmal Flames NM")
            for i in range(1, 4)]
    result = estimate(rows, ref)
    assert result["status"] == "READY" and result["selected_finish"] == "Holo"


def test_a_common_with_no_stated_finish_is_still_rejected():
    ref = phantasmal(name="Togedemaru", number="040/94", rarity="Common")
    rows = [row(i, str(100 + i), title="Pokemon TCG Togedemaru 040/94 Phantasmal Flames NM")
            for i in range(1, 4)]
    assert estimate(rows, ref)["rejection_counts"]["FINISH_MISMATCH_OR_UNKNOWN"] == 3


def test_unrelated_specifics_do_not_invent_a_treatment():
    aspects = [{"name": "Stage", "value": "Stage 1"}, {"name": "Card Name", "value": "V Ultra Promo pack"},
               {"name": "Features", "value": "Full Art"}]
    rows = [row(i, str(100 + i), localizedAspects=aspects) for i in range(1, 4)]
    assert estimate(rows)["status"] == "READY"


def test_a_treatment_specific_still_rejects():
    bad = row(1, localizedAspects=[{"name": "Features", "value": "Promo, Stamped"}])
    assert estimate([bad, row(2), row(3)])["rejection_counts"]["VARIANT_MISMATCH"] == 1


@pytest.mark.parametrize("words", ["26-27 Regionals", "Championship", "Pre-Release", "Judge", "Winner"])
def test_event_printings_are_not_the_base_card(words):
    bad = row(1, title=row(1)["title"] + " " + words)
    assert estimate([bad, row(2), row(3)])["rejection_counts"]["VARIANT_MISMATCH"] == 1


def test_a_reprint_is_not_named_by_its_original_release_number():
    # OP07-119 reprinted in PRB-02: "OP07-119" in a title is the OP07 card.
    ref = {**one_piece(), "name": "Portgas.D.Ace", "card_number": "OP07-119", "provider_id": "OP07-119_r1",
           "set_id": "PRB02", "set_name": "PREMIUM BOOSTER -ONE PIECE CARD THE BEST vol.2- [PRB-02]"}
    rows = [row(i, str(100 + i), title="Portgas.D.Ace OP07-119 SEC One Piece TCG English NM Foil")
            for i in range(1, 4)]
    assert estimate(rows, ref)["rejection_counts"]["SET_MISMATCH"] == 3


def test_a_different_collector_number_specific_still_rejects():
    bad = row(1, localizedAspects=[{"name": "Card Number", "value": "015"}])
    assert estimate([bad, row(2), row(3)])["rejection_counts"]["CARD_NUMBER_MISMATCH"] == 1


def set_151(**changes):
    return reference(name="Pikachu", card_number="025/165", set_name="151", set_id="sv03.5",
                     provider_id="sv03.5-025", finish="Reverse Holo", rarity="Common", **changes)


def rows_151(set_value):
    return [row(i, str(100 + i), title="Pokemon TCG Pikachu 025/165 Reverse Holo EN NM",
                localizedAspects=[{"name": "Set", "value": set_value}]) for i in range(1, 4)]


@pytest.mark.parametrize("set_value", ["151", "SV: Scarlet & Violet 151", "Scarlet & Violet—151"])
def test_set_specific_that_contains_the_release_is_accepted(set_value):
    assert estimate(rows_151(set_value), set_151())["status"] == "READY"


@pytest.mark.parametrize("set_value", ["Paldea Evolved", "Scarlet & Violet", "Celebrations"])
def test_set_specific_naming_another_release_still_rejects(set_value):
    result = estimate(rows_151(set_value), set_151())
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


def one_piece(**changes):
    return reference(provider="Punk Records", system_code="ONE_PIECE_CARD_GAME", provider_id="OP16-064",
                     set_id="OP16", set_name="The Time of Battle [OP-16]", name="Koby",
                     card_number="OP16-064", finish=None, rarity="R", **changes)


def one_piece_rows(aspects=()):
    return [row(i, str(100 + i), title="Bandai One Piece Card Game Koby OP16-064 R Foil EN Mint",
                localizedAspects=list(aspects)) for i in range(1, 4)]


def test_release_coded_number_names_the_release_when_no_set_is_given():
    result = estimate(one_piece_rows(), one_piece())
    assert result["status"] == "READY"
    assert result["selected_finish"] == "Foil"


def test_release_coded_number_does_not_forgive_a_conflicting_set_specific():
    result = estimate(one_piece_rows([{"name": "Set", "value": "OP12 Legacy of the Master"}]), one_piece())
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


def test_masters_prefix_alone_still_never_names_the_release():
    ref = reference(provider="Bandai Official", system_code="DRAGON_BALL_SUPER_MASTERS",
                    provider_id="BT21-102", set_id="428021", set_name="Z04 Booster -WILD RESURGENCE-",
                    name="Son Goku", card_number="BT21-102", finish=None, rarity="R")
    rows = [row(i, str(100 + i), title="Dragon Ball Super Card Game Son Goku BT21-102 R Foil English Mint")
            for i in range(1, 4)]
    assert estimate(rows, ref)["rejection_counts"]["SET_MISMATCH"] == 3


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


def test_a_small_absolute_spread_on_a_cheap_card_is_not_excessive():
    # Seen live: six accepted sellers for a cheap One Piece rare, rejected for spread.
    result = estimate([row(i, price) for i, price in enumerate(["1.00", "1.20", "1.50", "2.50", "3.20"])])
    assert result["status"] == "READY"


def kami(provider_id="EB04-008", name="Distorted Future", rarity="R"):
    return reference(provider="Bandai Official", system_code="ONE_PIECE_CARD_GAME", provider_id=provider_id,
                     set_id="569115", set_name="BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]",
                     name=name, card_number=provider_id, finish=None, rarity=rarity)


@pytest.mark.parametrize("provider_id", ["EB04-008", "OP15-075"])
def test_a_combined_release_bracket_names_both_printed_codes(provider_id):
    rows = [row(i, str(100 + i), title=f"One Piece TCG Distorted Future {provider_id} R Adventure on KAMI's Island English Foil NM")
            for i in range(1, 4)]
    assert estimate(rows, kami(provider_id))["status"] == "READY"


def test_a_combined_release_bracket_does_not_admit_another_code():
    # ST01 is not in [OP15-EB04]; the full label then has to appear, and does not.
    ref = kami("ST01-008")
    rows = [row(i, str(100 + i), title="One Piece TCG Distorted Future ST01-008 R Adventure on KAMI's Island English Foil NM")
            for i in range(1, 4)]
    assert estimate(rows, ref)["rejection_counts"]["SET_MISMATCH"] == 3


def nami(rarity="UC", provider_id="OP17-086"):
    return reference(provider="Bandai Official", system_code="ONE_PIECE_CARD_GAME", provider_id=provider_id,
                     set_id="569117", set_name="BOOSTER PACK -THE WORLD’S STRONGEST WARRIORS- [OP-17]",
                     name="Nami", card_number="OP17-086", finish=None, rarity=rarity)


@pytest.mark.parametrize("rarity,finish", [("UC", "Normal"), ("Uncommon", "Normal"), ("L", "Normal"),
                                           ("R", "Foil"), ("SuperRare", "Foil"), ("SEC", "Foil")])
def test_one_piece_rarity_supplies_an_unstated_finish(rarity, finish):
    rows = [row(i, str(100 + i), title="Nami OP17-086 The World's Strongest Warriors One Piece English Near Mint")
            for i in range(1, 4)]
    result = estimate(rows, nami(rarity))
    assert result["status"] == "READY" and result["selected_finish"] == finish


def test_a_mislabelled_finish_on_a_single_finish_card_counts_as_the_card():
    # Seen live: "Otama OP01-006 ... Romance Dawn" (an uncommon) listed as Foil.
    rows = [row(i, str(100 + i), title="Nami OP17-086 The World's Strongest Warriors One Piece English Foil NM")
            for i in range(1, 4)]
    result = estimate(rows, nami("UC"))
    assert result["status"] == "READY" and result["selected_finish"] == "Normal"


def test_a_marked_parallel_listing_is_still_not_the_base_card():
    rows = [row(i, str(100 + i), title="Nami OP17-086 Parallel Alt Art The World's Strongest Warriors One Piece NM")
            for i in range(1, 4)]
    assert estimate(rows, nami("UC"))["rejection_counts"]["VARIANT_MISMATCH"] == 3


def test_a_one_piece_parallel_does_not_take_the_base_finish():
    ref = {**nami("UC", "OP17-086_p1"), "evidence": {"variant_title_terms": ["Parallel"]}}
    rows = [row(i, str(100 + i), title="Nami OP17-086 Parallel The World's Strongest Warriors One Piece English NM")
            for i in range(1, 4)]
    assert estimate(rows, ref)["status"] == "INSUFFICIENT_COMPARABLES"


@pytest.mark.parametrize("specific", ["OP17 086 UC", "op17-086 uc", "OP17-086"])
def test_a_number_specific_with_the_rarity_added_agrees(specific):
    rows = [row(i, str(100 + i), title="Nami OP17-086 The World's Strongest Warriors One Piece English NM",
                localizedAspects=[{"name": "Card Number", "value": specific}]) for i in range(1, 4)]
    assert estimate(rows, nami())["status"] == "READY"


def test_a_number_specific_with_other_text_added_still_rejects():
    rows = [row(i, str(100 + i), title="Nami OP17-086 The World's Strongest Warriors One Piece English NM",
                localizedAspects=[{"name": "Card Number", "value": "OP17 086 Parallel"}]) for i in range(1, 4)]
    assert estimate(rows, nami())["rejection_counts"]["CARD_NUMBER_MISMATCH"] == 3


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
