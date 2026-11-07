from pathlib import Path

import pytest

from app.recognition import _candidate_review_payload
from app.recognition_engine import _provider_identity_fingerprint, resolve_candidates
from app.reference_feeds import ReferenceFeedError
from app.reference_one_piece import OFFICIAL_SETS, official_cards
from test_recognition_engine import observation


FIXTURE = Path(__file__).parent / "fixtures" / "one_piece_op16_buggy.html"


def test_official_buggy_parallel_is_distinct_from_base_and_leader_life_is_not_cost():
    cards = official_cards(FIXTURE.read_text(), {**OFFICIAL_SETS[0], "declared_card_count": 2})
    assert [row["provider_id"] for row in cards] == ["OP16-041", "OP16-041_p1"]
    assert all(row["card_number"] == "OP16-041" for row in cards)
    assert cards[1]["evidence"]["art_treatment"] == "Parallel"
    assert cards[1]["evidence"]["life"] == 5
    assert cards[1]["evidence"]["cost"] is None
    assert cards[1]["evidence"]["types"] == ["Impel Down", "Buggy Pirates"]


@pytest.mark.parametrize("broken", ["count", "duplicate", "image"])
def test_official_import_fails_closed_on_incomplete_or_conflicting_printing(broken):
    html = FIXTURE.read_text()
    record = {**OFFICIAL_SETS[0], "declared_card_count": 2}
    if broken == "count":
        record["declared_card_count"] = 3
    elif broken == "duplicate":
        html = html.replace("OP16-041_p1", "OP16-041")
    else:
        html = html.replace("../images/cardlist/card/", "https://example.invalid/")
    with pytest.raises(ReferenceFeedError):
        official_cards(html, record)


def test_missing_number_retrieves_official_buggy_without_auto_verifying_it():
    obs = observation(name_guess="Buggy", language="English", card_number="", card_number_confidence=.05,
        set_name_guess="", cost=None, power=5000, colors=["Blue"], traits=["Impel Down", "Buggy Pirates"],
        card_type_text="Leader", effect_text="", attributes=[], rarity_text="")
    items = []
    for card in official_cards(FIXTURE.read_text(), {**OFFICIAL_SETS[0], "declared_card_count": 2}):
        item = {**card["evidence"], **card, "provider": "Bandai Official", "language": "English",
                "base_card_id": card["card_number"], "library_reference": True, "exact_printing_verified": False}
        item.update(_provider_identity_fingerprint(obs, item))
        items.append(item)
    result = resolve_candidates(obs, [], provider_evidence=items, exact_threshold=.94,
        min_margin=.08, high_value_review_minor=20000)
    assert result["decision"] == "NEEDS_REVIEW"
    assert {row["provider_id"] for row in result["candidates"]} == {"OP16-041", "OP16-041_p1"}
    assert all(row["catalogue_id"] is None for row in result["candidates"])


def test_reference_confirmation_metadata_does_not_invent_price_or_identity():
    candidate = _candidate_review_payload({"catalogue_id": None, "market_value_minor": None,
        "reference_selection": '{"provider":"Punk Records","provider_id":"OP12-106_p2"}'})
    assert candidate["catalogue_id"] is None
    assert candidate["market_value_minor"] is None
    assert candidate["pricing_status"] == "NO_VERIFIED_VALUATION"
    assert candidate["reference_selection"]["provider_id"] == "OP12-106_p2"
