from copy import deepcopy

import pytest

from app.ebay_sales import _ebay_aspects, _ebay_card_name, _ebay_description, _inventory_payload


def test_campaign_name_keeps_variant_and_separate_card_number_within_ebay_limit():
    item = {
        "name": "Monkey.D.Luffy - ST10-006 (3rd Anniversary Treasure Campaign Pack)",
        "card_number": "ST10-006", "game": "One Piece", "language": "English",
        "set_name": "One Piece Promotion Cards", "grading_company": "PSA", "grade": "9",
        "certificate_number": "12345678", "inventory_code": "INV-TEST-ONE",
    }
    original = deepcopy(item)
    assert len(item["name"]) == 66
    payload = _inventory_payload(item, image_urls=["https://example.test/front", "https://example.test/back"])
    assert payload["product"]["aspects"]["Card Name"] == [
        "Monkey.D.Luffy (3rd Anniversary Treasure Campaign Pack)"
    ]
    assert payload["product"]["aspects"]["Card Number"] == ["ST10-006"]
    assert item["name"] in payload["product"]["description"]
    assert payload["availability"]["shipToLocationAvailability"]["quantity"] == 1
    assert item == original


@pytest.mark.parametrize("name", ["Charizard", "A" * 65, "長" * 65])
def test_valid_card_names_are_unchanged(name):
    assert _ebay_card_name({"name": name, "card_number": "004"}) == name


@pytest.mark.parametrize("name", ["Long card name " * 10, "A" * 90, "長" * 90])
def test_long_specifics_are_bounded_but_full_name_remains_in_description(name):
    item = {"name": name, "card_number": "004"}
    assert 1 <= len(_ebay_aspects(item)["Card Name"][0]) <= 65
    assert name in _ebay_description(item)
    assert item["name"] == name


def test_number_prefix_inside_another_identifier_is_not_removed():
    item = {"name": "Long Card - ST10-006A (" + "Variant " * 10 + ")", "card_number": "ST10-006"}
    assert "ST10-006A" in _ebay_card_name(item)
