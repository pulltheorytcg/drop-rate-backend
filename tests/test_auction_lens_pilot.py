"""Index-only UK pilot exact-card rules: no false matches, no invented valuation."""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.auction_lens_pilot import (
    ObservedCard, confirm_exact_printing, MIN_EXACT_VISUAL_SIMILARITY,
)

CATALOGUE_ID = uuid4()
MEDIA_ID = uuid4()
OBS = ObservedCard(
    game="Pokemon", language="English", name="Rapidash",
    set_name="Temporal Forces", card_number="048/162", finish="Normal"
)


def row(**kw):
    item = {
        "catalogue_id": CATALOGUE_ID, "media_asset_id": MEDIA_ID,
        "product_type": "CARD", "game": "Pokemon", "name": "Rapidash",
        "set_name": "Temporal Forces", "card_number": "048/162",
        "variant": "Normal", "language": "English",
        "approval_status": "APPROVED", "source_status": "ACTIVE",
        "rights_status": "VERIFIED",
    }
    item.update(kw)
    return item


def hint(**kw):
    item = {"catalogue_id": CATALOGUE_ID, "media_asset_id": MEDIA_ID,
            "similarity": 0.975, "trust_level": "VERIFIED"}
    item.update(kw)
    return item


def match(hints=None, rows=None, observed=OBS):
    return confirm_exact_printing(hints if hints is not None else [hint()],
                                  rows if rows is not None else [row()], observed)


def test_approved_unambiguous_exact_print_can_be_identified_without_price():
    value = match()
    assert value["catalogue_id"] == str(CATALOGUE_ID)
    assert "048/162" in value["title"]
    assert "market_value_minor" not in value
    assert "value" not in value


@pytest.mark.parametrize("change", [
    {"name": "Rapidash ex"}, {"set_name": "Twilight Masquerade"},
    {"card_number": "049/162"}, {"variant": "Reverse Holofoil"},
    {"language": "Japanese"}, {"game": "One Piece"},
    {"approval_status": "PENDING"}, {"source_status": "REVOKED"},
    {"rights_status": "INTERNAL_REFERENCE_ONLY"}, {"product_type": "SEALED"},
    {"media_asset_id": uuid4()},
])
def test_wrong_printing_wrong_rights_or_wrong_asset_never_promotes_exact(change):
    assert match(rows=[row(**change)]) is None


@pytest.mark.parametrize("change", [
    {"finish": "Reverse Holofoil"}, {"language": "Japanese"},
    {"card_number": "049/162"}, {"set_name": ""},
    {"name": ""}, {"object_type": "GRADED_CARD"},
    {"game": "One Piece"},
])
def test_wrong_or_insufficient_observation_never_promotes_exact(change):
    assert match(observed=replace(OBS, **change)) is None


@pytest.mark.parametrize("change", [
    {"trust_level": "PROVISIONAL"},
    {"similarity": MIN_EXACT_VISUAL_SIMILARITY - 0.001},
])
def test_untrusted_or_weak_visual_hint_is_not_exact(change):
    assert match(hints=[hint(**change)]) is None


def test_similar_printing_is_ambiguity_even_if_missing_a_database_row():
    rival = hint(catalogue_id=uuid4(), media_asset_id=uuid4(), similarity=0.96)
    assert match(hints=[hint(), rival]) is None


def test_distant_visual_runner_can_not_change_an_exact_unique_match():
    rival = hint(catalogue_id=uuid4(), media_asset_id=uuid4(), similarity=0.80)
    assert match(hints=[hint(), rival]) is not None


def test_no_hints_no_match_no_value():
    assert match(hints=[]) is None
    assert match(rows=[]) is None


def test_card_number_padding_uses_existing_collector_identity_rules():
    assert match(rows=[row(card_number="048/162")]) is not None
    assert match(rows=[row(card_number="048/163")]) is None
