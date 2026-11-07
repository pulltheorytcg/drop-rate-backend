"""Narrow release-name aliases verified against Bandai's eleven category pages."""
from copy import deepcopy

import pytest

from test_reference_asking_estimator import estimate, reference, row


RELEASES = [
    ("428021", "Z04 Booster -WILD RESURGENCE-", "Wild Resurgence", "BT21-079"),
    ("428022", "Z05 Booster -CRITICAL BLOW-", "Critical Blow", "BT22-079"),
    ("428023", "Z06 Booster -PERFECT COMBINATION-", "Perfect Combination", "BT23-079"),
    ("428024", "Z07 Booster -BEYOND GENERATIONS-", "Beyond Generations", "BT24-079"),
    ("428025", "Z08 Booster -LEGEND OF THE DRAGON BALLS-", "Legend of the Dragon Balls", "BT25-079"),
    ("428026", "Z09 Booster -ULTIMATE ADVENT-", "Ultimate Advent", "BT26-079"),
    ("428027", "Z10 Booster -HISTORY OF Z-", "History of Z", "BT27-079"),
    ("428028", "UB01 Booster -PRISMATIC CLASH-", "Prismatic Clash", "BT28-079"),
    ("428029", "UB02 Booster -FEARSOME RIVALS-", "Fearsome Rivals", "BT29-079"),
    ("428030", "UB03 Booster -THREE GLORIOUS FIGHTERS-", "Three Glorious Fighters", "BT30-079"),
    ("428031", "UB04 Booster -IMPACT BEYOND DIMENSIONS-", "Impact Beyond Dimensions", "BT31-079"),
]


def masters(release=RELEASES[0], **changes):
    set_id, canonical, _, number = release
    value = reference(provider="Bandai Official", system_code="DRAGON_BALL_SUPER_MASTERS",
        language="English", provider_id=set_id + ":" + number + ".png",
        set_id=set_id, set_name=canonical, name="Testcard", card_number=number,
        finish="Normal", rarity="Common")
    value.update(changes)
    return value


def listings(release=RELEASES[0], *, location="aspect", set_value=None, suffix=""):
    _, _, alias, number = release
    value = alias if set_value is None else set_value
    title = f"DBS Masters Testcard {number} English Normal NM"
    if location == "title":
        title += " " + value
    title += " " + suffix
    return [row(i, title=title, localizedAspects=(
        [{"name": "Set", "value": value}] if location == "aspect" else [])) for i in range(3)]


@pytest.mark.parametrize("release", RELEASES)
@pytest.mark.parametrize("location", ["aspect", "title"])
def test_exact_known_release_accepts_explicit_official_short_name(release, location):
    result = estimate(listings(release, location=location), masters(release))
    assert result["status"] == "READY"
    proof = result["comparables"][0]["match_proof"]
    assert proof["set_terms"] == [release[1]]
    assert proof["set_alternatives"] == [[release[1]], [release[2]]]
    assert proof["set_alias_source"].endswith("category=" + release[0])


@pytest.mark.parametrize("release", RELEASES)
def test_existing_full_canonical_name_still_matches(release):
    assert estimate(listings(release, set_value=release[1]), masters(release))["status"] == "READY"


@pytest.mark.parametrize("change", [
    {"set_id": "428999"},
    {"set_id": "428022"},
    {"set_name": "Z04 Booster -WILD RESURGENCE- Collector Edition"},
    {"provider": "Other Provider"},
    {"language": "Japanese"},
    {"system_code": "DRAGON_BALL_SUPER_FUSION_WORLD"},
])
def test_alias_requires_full_known_canonical_identity(change):
    assert estimate(listings(), masters(**change))["status"] != "READY"


@pytest.mark.parametrize("release", RELEASES[6:])
@pytest.mark.parametrize("field", ["set_id", "set_name"])
def test_new_aliases_require_the_exact_canonical_id_and_name_pair(release, field):
    change = {field: RELEASES[0][0] if field == "set_id" else release[1] + " Collector Edition"}
    result = estimate(listings(release), masters(release, **change))
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


@pytest.mark.parametrize("release", RELEASES[6:])
@pytest.mark.parametrize("new_reference", [False, True])
def test_new_and_existing_release_names_cannot_both_claim_the_listing(release, new_reference):
    canonical, conflicting = (release, RELEASES[0]) if new_reference else (RELEASES[0], release)
    result = estimate(listings(canonical, suffix=conflicting[2]), masters(canonical))
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


@pytest.mark.parametrize("terms", [["Z04 Booster -WILD RESURGENCE-"], ["Other Set"], [], None])
def test_explicit_set_title_terms_never_receive_an_automatic_alias(terms):
    result = estimate(listings(), masters(evidence={"set_title_terms": terms}))
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


def test_evidence_name_does_not_substitute_for_missing_canonical_set_name():
    result = estimate(listings(), masters(set_name=None, evidence={"set_name": RELEASES[0][1]}))
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


@pytest.mark.parametrize("conflict", ["Critical Blow", "Unknown Release", "Wild Resurgence Collector Edition"])
def test_conflicting_structured_set_overrides_a_positive_title(conflict):
    rows = listings(location="title")
    for value in rows:
        value["localizedAspects"] = [{"name": "Set", "value": conflict}]
    result = estimate(rows, masters())
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


@pytest.mark.parametrize("suffix", ["Critical Blow", "Not Wild Resurgence", "Not Z04 Booster Wild Resurgence"])
def test_explicit_title_conflict_or_denial_overrides_positive_structured_alias(suffix):
    result = estimate(listings(suffix=suffix), masters())
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


@pytest.mark.parametrize("suffix", ["Reprint", "Alt Art", "Parallel", "Promo", "Stamped"])
def test_set_alias_does_not_weaken_printing_requirements(suffix):
    result = estimate(listings(suffix=suffix), masters())
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["rejection_counts"]["VARIANT_MISMATCH"] == 3


def test_collector_prefix_alone_never_proves_the_release():
    result = estimate(listings(location="title", set_value=""), masters())
    assert result["rejection_counts"]["SET_MISMATCH"] == 3


def test_unresolved_parallel_reference_remains_ineligible():
    result = estimate(listings(), masters(reference_group_count=2))
    assert result["status"] == "IDENTITY_UNSUPPORTED"
    assert result["rejection_counts"] == {"UNRESOLVED_PARALLEL_IDENTITY": 1}


def test_alias_evaluation_does_not_modify_reference_or_listing_inputs():
    rows, ref = listings(), masters()
    before = deepcopy((rows, ref))
    estimate(rows, ref)
    assert (rows, ref) == before
