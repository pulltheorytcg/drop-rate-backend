import pytest

from app.imports import (
    _detect_adapter,
    _field_map,
    _json_value,
    _money_minor,
    _normalized_row,
    _quantity,
)


def test_generic_header_mapping_accepts_common_names() -> None:
    mapping = _field_map(["Card Name", "Set Name", "Card Number", "Qty", "Price Paid", "Condition"])
    assert mapping["name"] == "Card Name"
    assert mapping["set_name"] == "Set Name"
    assert mapping["card_number"] == "Card Number"
    assert mapping["quantity"] == "Qty"
    assert mapping["purchase_price"] == "Price Paid"


def test_ebay_adapter_detection() -> None:
    assert _detect_adapter(["Item Title", "Item Number", "Seller Username"], "AUTO") == "EBAY_PURCHASES"


def test_quantity_defaults_to_one_and_rejects_invalid() -> None:
    assert _quantity(None) == (1, [])
    assert _quantity("3") == (3, [])
    assert _quantity("0")[1] == ["invalid_quantity"]
    assert _quantity("abc")[1] == ["invalid_quantity"]


def test_gbp_cost_becomes_minor_units_without_forcing_unknown_to_zero() -> None:
    assert _money_minor(None, "GBP") == (None, [])
    assert _money_minor("£12.34", "GBP") == (1234, [])
    assert _money_minor("1,200.00", None) == (120000, [])


def test_non_gbp_cost_is_flagged_not_converted() -> None:
    value, issues = _money_minor("10.00", "USD")
    assert value is None
    assert issues == ["non_gbp_purchase_cost"]


def test_persisted_json_decodes_text_or_accepts_decoded_value() -> None:
    payload = {"condition": "Near Mint", "acquisition_cost_minor": None}
    assert _json_value(payload, expected_type=dict, fallback={}) == payload
    assert _json_value(
        '{"condition":"Near Mint","acquisition_cost_minor":null}',
        expected_type=dict,
        fallback={},
    ) == payload
    assert _json_value('["catalogue_not_found"]', expected_type=list, fallback=[]) == [
        "catalogue_not_found"
    ]


def test_persisted_json_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="unexpected shape"):
        _json_value('["not", "a", "dict"]', expected_type=dict, fallback={})


def test_card_condition_uses_tcgplayer_scale() -> None:
    row = {
        "Card Name": "Charizard",
        "Set": "Base Set",
        "Card Number": "4/102",
        "Game": "Pokemon",
        "Condition": "NM",
        "Language": "English",
    }
    mapping = _field_map(list(row))
    normalized, issues = _normalized_row(row, mapping, None)
    assert normalized["condition"] == "Near Mint"
    assert normalized["quantity"] == 1
    assert issues == []


def test_incomplete_card_identity_is_sent_to_review() -> None:
    row = {"Card Name": "Charizard", "Set": "Base Set"}
    mapping = _field_map(list(row))
    normalized, issues = _normalized_row(row, mapping, None)
    assert normalized["name"] == "Charizard"
    assert "missing_game" in issues
    assert "missing_card_number" in issues


def test_sealed_products_do_not_use_raw_card_condition() -> None:
    row = {
        "Product Name": "151 Elite Trainer Box",
        "Set": "151",
        "Game": "Pokemon",
        "Sealed": "Yes",
    }
    mapping = _field_map(list(row))
    normalized, issues = _normalized_row(row, mapping, None)
    assert normalized["product_type"] == "SEALED"
    assert normalized["seal_status"] == "SEALED"
    assert normalized["condition"] is None
    assert issues == []


def test_language_can_be_preserved_from_trailing_set_token() -> None:
    row = {
        "Product Name": "Monkey.D.Luffy",
        "Set": "One Piece Promotion Cards (JP)",
        "Card Number": "P-001",
        "Category": "One Piece",
    }
    mapping = _field_map(list(row))
    normalized, issues = _normalized_row(row, mapping, None, adapter="COLLECTR")
    assert normalized["name"] == "Monkey.D.Luffy"
    assert normalized["set_name"] == "One Piece Promotion Cards (JP)"
    assert normalized["language"] == "Japanese"
    assert "missing_language" not in issues


def test_conflicting_title_and_set_language_evidence_fails_closed() -> None:
    row = {
        "Product Name": "Charizard (EN)",
        "Set": "Promo Set (JP)",
        "Card Number": "001",
        "Game": "Pokemon",
    }
    mapping = _field_map(list(row))
    normalized, issues = _normalized_row(row, mapping, None)
    assert normalized["language"] == "English"
    assert "language_conflict" in issues
