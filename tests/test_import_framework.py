from app.imports import (
    _detect_adapter,
    _field_map,
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


def test_card_condition_uses_tcgplayer_scale() -> None:
    row = {
        "Card Name": "Charizard",
        "Set": "Base Set",
        "Card Number": "4/102",
        "Game": "Pokemon",
        "Condition": "NM",
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
