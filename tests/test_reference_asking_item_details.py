"""Official Browse descriptor shapes and Bandai's documented Masters rename."""
from copy import deepcopy
from datetime import timedelta

import pytest

from test_reference_asking_estimator import NOW, estimate, reference, reference_asking_eligibility, row


def descriptor(name, content, **changes):
    value = {"content": content}
    value.update(changes)
    return {"name": name, "values": [value]}


def detailed(index=1, **changes):
    value = row(index, title="Pokemon Charizard 4/102 Base Set Holo English",
        condition="Ungraded", conditionId="4000",
        conditionDescriptors=[descriptor("Card Condition", "Near mint or better",
            additionalInfo=["Minor corner and edge wear"])])
    value.update(changes)
    return value


def test_browse_card_condition_descriptor_proves_nm_without_title_condition():
    result = estimate([detailed(i) for i in range(3)])
    assert result["status"] == "READY"
    assert result["sample_count"] == 3


def test_ungraded_alone_does_not_establish_near_mint():
    result = estimate([detailed(i, conditionDescriptors=[]) for i in range(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["CONDITION_OUTSIDE_NM_MINT"] == 3


@pytest.mark.parametrize("bad", [
    descriptor("Card Condition", "Excellent"),
    descriptor("Card Condition", "Not Near Mint"),
    descriptor("Card Condition", "Near Mint", additionalInfo=["Damaged"]),
    descriptor("Professional Grader", "PSA"),
    descriptor("Grade", "10"),
    descriptor("Certification Number", "123456789"),
])
def test_conflicting_or_graded_descriptor_cannot_be_overridden_by_positive_title(bad):
    bad_row = row(1, conditionDescriptors=[bad])
    result = estimate([bad_row, row(2), row(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["estimate_minor"] is None


def test_descriptor_does_not_override_a_conflicting_existing_aspect():
    bad_row = detailed(1, localizedAspects=[{"name": "Card Condition", "value": "Lightly Played"}])
    result = estimate([bad_row, detailed(2), detailed(3)])
    assert result["rejection_counts"]["CONDITION_OUTSIDE_NM_MINT"] == 1


@pytest.mark.parametrize("availability", [
    [{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}],
    [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 0}],
    [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": True}],
    [{"estimatedAvailabilityStatus": "UNKNOWN"}],
    "IN_STOCK", [], [None],
])
def test_explicit_unavailable_or_malformed_availability_is_rejected(availability):
    result = estimate([detailed(1, estimatedAvailabilities=availability), detailed(2), detailed(3)])
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["UNAVAILABLE_OR_INVALID_LISTING"] == 1


@pytest.mark.parametrize("status", ["IN_STOCK", "LIMITED_STOCK"])
def test_positive_listing_availability(status):
    result = estimate([detailed(i, estimatedAvailabilities=[{
        "estimatedAvailabilityStatus": status, "estimatedAvailableQuantity": 1,
        "deliveryOptions": ["SHIP_TO_HOME"]}]) for i in range(3)])
    assert result["status"] == "READY"


def masters(number="BT21-079", **changes):
    value = reference(provider="Bandai Official", system_code="DRAGON_BALL_SUPER_MASTERS",
        provider_id="428021:" + number + ".png", set_id="428021", set_name="Wild Resurgence",
        name="Testcard", card_number=number, finish="Normal")
    value.update(changes)
    return value


@pytest.mark.parametrize("number", ["BT21-079", "TB1-001", "EX21-01", "SD1-01"])
def test_original_full_game_name_matches_documented_masters_number_families(number):
    rows = [row(i, title=f"Testcard {number} Wild Resurgence English Normal NM",
        localizedAspects=[{"name": "Game", "value": "Dragon Ball Super Card Game"}]) for i in range(3)]
    assert estimate(rows, masters(number))["status"] == "READY"


@pytest.mark.parametrize("number", ["FB01-001", "FS01-01", "ST01-01", "SB01-001", "1/100"])
def test_legacy_alias_never_guesses_other_number_families(number):
    rows = [row(i, title=f"Dragon Ball Super Card Game Testcard {number} Wild Resurgence English Normal NM") for i in range(3)]
    result = estimate(rows, masters(number))
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["GAME_MISMATCH"] == 3


@pytest.mark.parametrize("conflict", ["Fusion World", "Not Dragon Ball Super Card Game"])
def test_legacy_alias_does_not_override_explicit_game_conflict(conflict):
    rows = [row(i, title=f"Dragon Ball Super Card Game Testcard BT21-079 Wild Resurgence English Normal NM {conflict}") for i in range(3)]
    assert estimate(rows, masters())["rejection_counts"]["GAME_MISMATCH"] == 3


def test_legacy_game_alias_does_not_replace_set_or_variant_evidence():
    rows = [row(i, title="Dragon Ball Super Card Game Testcard BT21-079 Other Release English Normal NM") for i in range(3)]
    assert estimate(rows, masters())["rejection_counts"]["SET_MISMATCH"] == 3
    rows = [row(i, title="Dragon Ball Super Card Game Testcard BT21-079 Wild Resurgence English Normal NM Alt Art") for i in range(3)]
    assert estimate(rows, masters())["rejection_counts"]["VARIANT_MISMATCH"] == 3


def test_detail_inputs_remain_unchanged():
    rows = [detailed(i) for i in range(3)]
    before = deepcopy(rows)
    estimate(rows)
    assert rows == before


def test_reused_evidence_cannot_keep_a_now_ended_listing_active():
    rows = [detailed(i, itemEndDate=(NOW + timedelta(seconds=30)).isoformat()) for i in range(3)]
    result = estimate(rows, observed_at=NOW, now=NOW + timedelta(seconds=60))
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["ENDED_OR_INVALID_LISTING_TIME"] == 3


@pytest.mark.parametrize("location", ["aspect", "descriptor"])
def test_explicit_not_professionally_graded_means_raw(location):
    rows = [detailed(i) for i in range(3)]
    for value in rows:
        if location == "aspect":
            value["localizedAspects"] = [{"name": "Professional Grader", "value": "Not Professionally Graded"}]
        else:
            value["conditionDescriptors"].append(descriptor("Professional Grader", "Not Professionally Graded"))
    assert estimate(rows)["status"] == "READY"


@pytest.mark.parametrize("suffix", ["PR", "PR02", "SPR", "SPR02", "BD", "GDR", "S"])
def test_unresolved_official_masters_special_print_is_excluded_before_discovery(suffix):
    ref = masters("BT21-102_" + suffix, name="Golden Frieza, Shining Emperor")
    assert reference_asking_eligibility(ref) == "UNRESOLVED_PARALLEL_IDENTITY"
    assert ref["card_number"] == "BT21-102_" + suffix  # No silent base-number rewrite.


def test_graded_yes_overrides_ungraded_sentinel():
    bad = detailed(1, localizedAspects=[
        {"name": "Professional Grader", "value": "Not Professionally Graded"},
        {"name": "Graded", "value": "Yes"}])
    result = estimate([bad, detailed(2), detailed(3)])
    assert result["rejection_counts"]["GRADED_OR_SLAB"] == 1


@pytest.mark.parametrize("finish", ["Non-Holofoil", "non holofoil", "NonHolofoil"])
@pytest.mark.parametrize("location", ["title", "aspect"])
def test_explicit_non_holofoil_spelling_proves_normal_finish(finish, location):
    rows = [detailed(i, title="Pokemon Charizard 4/102 Base Set English") for i in range(3)]
    for value in rows:
        if location == "title":
            value["title"] += " " + finish
        else:
            value["localizedAspects"] = [{"name": "Finish", "value": finish}]
    result = estimate(rows, reference(finish=finish))
    assert result["status"] == "READY"
    assert result["selected_finish"] == "Normal"


@pytest.mark.parametrize("finish", ["Non-Holofoil Holo", "NonHolofoil Foil"])
def test_non_holofoil_does_not_hide_a_conflicting_finish(finish):
    rows = [detailed(i, localizedAspects=[{"name": "Finish", "value": finish}]) for i in range(3)]
    assert estimate(rows, reference(finish="Normal"))["rejection_counts"]["FINISH_MISMATCH_OR_UNKNOWN"] == 3


@pytest.mark.parametrize("source", ["same_array", "second_array", "descriptor"])
def test_duplicate_ungraded_value_is_corroboration_across_browse_sources(source):
    rows = [detailed(i, localizedAspects=[{
        "name": "Professional Grader", "value": "Not Professionally Graded"}]) for i in range(3)]
    for value in rows:
        duplicate = {"name": "professional grader", "value": "not-professionally-graded"}
        if source == "same_array":
            value["localizedAspects"].append(duplicate)
        elif source == "second_array":
            value["localizedItemAspects"] = [duplicate]
        else:
            value["conditionDescriptors"].append(descriptor("Professional Grader", "not-professionally-graded"))
    before = deepcopy(rows)
    assert estimate(rows)["status"] == "READY"
    assert rows == before


def test_duplicate_exact_set_and_card_number_do_not_create_compound_identities():
    aspects = [{"name": "Set", "value": "Base Set"}, {"name": "Card Number", "value": "4/102"}]
    rows = [detailed(i, localizedAspects=deepcopy(aspects), localizedItemAspects=deepcopy(aspects)) for i in range(3)]
    result = estimate(rows)
    assert result["status"] == "READY"
    assert result["comparables"][0]["listing_evidence"]["aspects"]["set"] == "base set"
    assert result["comparables"][0]["listing_evidence"]["aspects"]["card number"] == "4 102"


@pytest.mark.parametrize("name,good,bad,reason", [
    ("Professional Grader", "Not Professionally Graded", "PSA", "GRADED_OR_SLAB"),
    ("Set", "Base Set", "Base Set 2", "SET_MISMATCH"),
    ("Language", "English", "Japanese", "LANGUAGE_MISMATCH_OR_UNKNOWN"),
    ("Finish", "Holo", "Non-Holofoil", "FINISH_MISMATCH_OR_UNKNOWN"),
    ("Card Condition", "Near Mint", "Lightly Played", "CONDITION_OUTSIDE_NM_MINT"),
])
def test_normalization_preserves_distinct_conflicting_values(name, good, bad, reason):
    rows = [detailed(i,
        localizedAspects=[{"name": name, "value": good}, {"name": name, "value": good}],
        localizedItemAspects=[{"name": name, "value": good}, {"name": name, "value": bad}]) for i in range(3)]
    assert estimate(rows)["rejection_counts"][reason] == 3


def test_duplicate_condition_content_still_retains_conflicting_additional_information():
    rows = [detailed(i, localizedAspects=[{"name": "Card Condition", "value": "Near Mint"}],
        conditionDescriptors=[descriptor("Card Condition", "Near Mint", additionalInfo=["Near Mint", "Damaged"])])
        for i in range(3)]
    assert estimate(rows)["rejection_counts"]["CONDITION_OUTSIDE_NM_MINT"] == 3
