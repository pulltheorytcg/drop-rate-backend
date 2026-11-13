"""One Piece: canonical set aliases and shortened eBay card-number aspects.

These tests never contact eBay. Alias evidence is from the exact canonical
provider release label, never guessed by the seller, AI or an unknown source.
"""
from datetime import datetime, timezone

from app.reference_multi_query_search import build_reference_search_plan
from app.reference_asking_estimator import (
    _matches, _number_matches, _reference_spec,
    estimate_reference_asking_price, reference_asking_eligibility,
)


NOW = datetime(2026, 11, 13, 13, tzinfo=timezone.utc)


def one_piece(**overrides):
    data = {
        "provider": "Punk Records", "system_code": "ONE_PIECE_CARD_GAME",
        "language": "English", "provider_id": "OP01-006",
        "name": "Otama", "card_number": "OP01-006",
        "set_id": "569101", "set_name": "BOOSTER PACK -ROMANCE DAWN- [OP-01]",
        "finish": None, "rarity": "Common",
        "reference_group_count": 1, "evidence": {},
    }
    data.update(overrides)
    return data


def listing(i, *, number="OP01-006", aspect_number="006",
            set_name="Romance Dawn", price="50.00"):
    return {
        "itemId": f"v1|{111111110000+i}|0",
        "title": f"ONE PIECE Otama {number} English {set_name} Foil Near Mint Ungraded",
        "seller": {"username": f"seller{i}"},
        "price": {"value": price, "currency": "GBP"},
        "buyingOptions": ["FIXED_PRICE"],
        "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "GBP"}}],
        "itemLocation": {"country": "GB"},
        "condition": "Ungraded",
        "localizedAspects": [
            {"name": "Card Number", "value": aspect_number},
            {"name": "Set", "value": set_name},
            {"name": "Game", "value": "One Piece CCG"},
            {"name": "Language", "value": "English"},
            {"name": "Finish", "value": "Foil"},
            {"name": "Card Condition", "value": "Near Mint or Better"},
        ],
        "_evidence_acquisition": "GET_ITEM",
    }


def test_one_piece_provider_label_supplies_only_its_own_short_set_alias():
    spec, reason = _reference_spec(one_piece())
    assert reason is None
    assert ("ROMANCE DAWN",) in spec["set_alternatives"]
    assert spec["set_alias_source"] == "CANONICAL_PROVIDER_SET_LABEL"
    assert _matches(listing(1), one_piece(), spec) is None


def test_three_real_item_style_rows_yield_low_confidence_active_asking_only():
    evidence = [listing(1, price="50"), listing(2, price="60"), listing(3, price="70")]
    result = estimate_reference_asking_price(one_piece(), evidence, observed_at=NOW, now=NOW)
    assert result["status"] == "READY"
    assert result["basis"] == "ASKING_PRICE_ESTIMATE"
    assert result["estimate_minor"] == 6000
    assert result["seller_count"] == 3
    assert result["physical_valuation_eligible"] is False
    assert result["comparables"][0]["listing_evidence"]["acquisition"] == "GET_ITEM"


def test_short_aspect_needs_full_exact_title_number_and_never_forgives_wrong_set_code():
    assert _number_matches("ONE PIECE Otama OP01-006", "006", "OP01-006")
    assert not _number_matches("ONE PIECE Otama OP02-006", "006", "OP01-006")
    assert not _number_matches("ONE PIECE Otama OP01-007", "006", "OP01-006")
    assert not _number_matches("ONE PIECE Otama 006", "006", "OP01-006")
    assert not _number_matches("ONE PIECE Otama OP01-006", "007", "OP01-006")
    assert not _number_matches("ONE PIECE Otama OP01-006 OP02-006", "006", "OP01-006")


def test_wrong_set_or_conflicting_evidence_is_not_normalized_away():
    spec, _ = _reference_spec(one_piece())
    assert _matches(listing(1, set_name="Paramount War"), one_piece(), spec) == "SET_MISMATCH"
    assert _matches(listing(1, number="OP02-006"), one_piece(), spec) == "CARD_NUMBER_MISMATCH"
    assert _matches(listing(1, aspect_number="008"), one_piece(), spec) == "CARD_NUMBER_MISMATCH"
    assert _matches(
        listing(1, set_name="Not Romance Dawn"), one_piece(), spec
    ) == "SET_MISMATCH"


def test_mismatched_canonical_code_never_auto_derives_a_short_set_name():
    ref = one_piece(set_name="BOOSTER PACK -ROMANCE DAWN- [OP-02]")
    spec, reason = _reference_spec(ref)
    assert reason is None
    assert ("ROMANCE DAWN",) not in spec["set_alternatives"]
    assert spec["set_alias_source"] is None


def test_no_automatic_unverified_parallel_or_alt_art_price():
    ref = one_piece(
        provider_id="OP01-006_p1", finish="Alt Art",
        evidence={}, reference_group_count=2,
    )
    assert reference_asking_eligibility(ref) == "UNRESOLVED_PARALLEL_IDENTITY"


def test_multi_query_prefers_verified_romance_dawn_alias_not_marketing_label():
    plan = build_reference_search_plan(one_piece())
    assert len(plan) >= 2
    assert any("ROMANCE DAWN" in query for query in plan)
    assert all("BOOSTER PACK" not in query for query in plan)
    assert any("OP01-006" in query for query in plan)
