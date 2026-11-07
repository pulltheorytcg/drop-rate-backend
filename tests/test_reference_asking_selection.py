"""Spend bounded detail reads on the most plausible exact raw comparables."""
from copy import deepcopy

import pytest

from app.reference_asking_backfill import item_detail_candidates
from test_reference_asking_backfill import reference


def summary(index=1, **changes):
    result = {"itemId": f"v1|{100000000000 + index}|0",
              "title": "Pokemon Bulbasaur 44 Base Set English Normal Near Mint",
              "condition": "Ungraded", "conditionId": "4000",
              "seller": {"username": f"seller-{index}"}}
    result.update(changes)
    return result


@pytest.mark.parametrize("changes", [
    {"condition": "PSA 10"}, {"conditionId": "2750"},
    {"localizedAspects": [{"name": "Professional Grader", "value": "CGC"}]},
    {"conditionDescriptors": [{"name": "Grade", "values": [{"content": "10"}]}]},
    {"conditionDescriptors": [{"name": "Graded", "values": [{"content": "Yes"}]}]},
    {"title": "Pokemon Bulbasaur 44 Base Set English Normal NM Slabs"},
    {"localizedAspects": [{"name": "Type", "value": "Digital Proxy"}]},
    {"title": "Pokemon Bulbasaur 44 Base Set English Normal NM Bundle"},
])
def test_explicit_graded_multi_item_and_nonphysical_summary_never_spends_detail(changes):
    assert item_detail_candidates(reference(), [summary(**changes)]) == []


@pytest.mark.parametrize("changes", [
    {"title": "Pokemon Bulbasaur 44 Base Set Japanese Normal Near Mint"},
    {"localizedAspects": [{"name": "Language", "value": "Japanese"}]},
    {"title": "Pokemon Bulbasaur 44 Base Set Not English Normal NM"},
    {"title": "Pokemon Bulbasaur 44 Base Set 2 English Normal NM"},
    {"localizedAspects": [{"name": "Set", "value": "Jungle"}]},
    {"localizedAspects": [{"name": "Card Number", "value": "45"}]},
    {"title": "Pokemon Bulbasaur 44 Base Set English Normal NM First Edition"},
    {"title": "Pokemon Bulbasaur 44 Base Set English Holo Near Mint"},
])
def test_explicit_language_set_number_or_printing_conflict_is_skipped(changes):
    assert item_detail_candidates(reference(), [summary(**changes)]) == []


def test_unknown_detail_resolvable_facts_remain_candidates_but_proven_summary_ranks_first():
    unknown = summary(1, title="Bulbasaur 44", condition="Ungraded")
    language_only = summary(2, title="Bulbasaur 44 English", condition="Ungraded")
    proven = summary(3)
    rows = [unknown, language_only, proven]
    before = deepcopy(rows)
    assert item_detail_candidates(reference(), rows) == [proven["itemId"], language_only["itemId"], unknown["itemId"]]
    assert rows == before


def test_summary_aspects_can_prioritize_evidence_without_transferring_it_to_details():
    unknown = summary(1, title="Bulbasaur 44", condition="Ungraded")
    explicit = summary(2, title="Bulbasaur 44", condition="Ungraded", localizedAspects=[
        {"name": "Language", "value": "English"}, {"name": "Set", "value": "Base Set"},
        {"name": "Finish", "value": "Normal"}, {"name": "Card Condition", "value": "Near Mint"}])
    assert item_detail_candidates(reference(), [unknown, explicit]) == [explicit["itemId"], unknown["itemId"]]


def test_ordinary_ungraded_descriptor_is_not_mistaken_for_a_slab():
    value = summary(conditionDescriptors=[{"name": "Professional Grader",
        "values": [{"content": "Not Professionally Graded"}]}])
    assert item_detail_candidates(reference(), [value]) == [value["itemId"]]


def test_special_finish_with_holo_hint_is_not_rejected_as_ordinary_holo():
    ref = reference()
    ref.update(finish="Alt Art", evidence={"variant_title_terms": ["Alt Art"]})
    value = summary(title="Pokemon Bulbasaur 44 Base Set English Alt Art Holo NM")
    assert item_detail_candidates(ref, [value]) == [value["itemId"]]


def test_best_candidate_per_seller_is_prioritized_then_sellers_are_diversified():
    weak = summary(1, title="Bulbasaur 44", seller={"username": "same"})
    strong = summary(2, seller={"username": "Same"})
    other = summary(3, title="Bulbasaur 44")
    assert item_detail_candidates(reference(), [weak, strong, other]) == [strong["itemId"], other["itemId"], weak["itemId"]]


def test_detail_limit_default_six_and_explicit_twenty_four_preserve_unique_items():
    rows = [summary(i) for i in range(30)]
    assert len(item_detail_candidates(reference(), rows)) == 6
    assert len(item_detail_candidates(reference(), rows, limit=24)) == 24
    assert len(item_detail_candidates(reference(), rows + rows, limit=24)) == 24


@pytest.mark.parametrize("limit", [0, 25, True, None, "24", 2.5])
def test_invalid_detail_limits_fail_before_selection(limit):
    with pytest.raises(ValueError, match="integer from 1 to 24"):
        item_detail_candidates(reference(), [], limit=limit)
