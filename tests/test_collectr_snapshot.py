from pathlib import Path

from app.language import display_title, language_code, parse_title_language
from app.collectr_snapshot import (
    collectr_adapter_headers,
    collectr_catalogue_identity_key,
    collectr_cost_minor,
    collectr_grade,
    collectr_product_type,
    collectr_snapshot_key,
)
from app.imports import _detect_adapter, _field_map, _normalized_row


ROOT = Path(__file__).parents[1]
IMPORTS = ROOT / "backend" / "app" / "imports.py"
LANGUAGE_MIGRATION = ROOT / "database" / "migrations" / "20260924195341_normalize_explicit_card_languages.sql"
LANGUAGE_ROLLBACK_MIGRATION = ROOT / "database" / "migrations" / "20260924220735_revert_unsupported_english_language_backfill.sql"


def collectr_row(**overrides):
    row = {
        "Portfolio Name": "Main",
        "Category": "One Piece",
        "Set": "500 Years in the Future",
        "Product Name": "Basil Hawkins",
        "Card Number": "OP07-029",
        "Rarity": "SR",
        "Variance": "Foil",
        "Grade": "Ungraded",
        "Card Condition": "Near Mint",
        "Average Cost Paid": "0.0000",
        "Quantity": "3",
        "Market Price (As of 2026-09-24)": "0.26",
        "Price Override": "0",
        "Watchlist": "false",
        "Date Added": "2026-09-04",
        "Notes": "",
        "Language": "English",
    }
    row.update(overrides)
    return row


def test_collectr_export_is_auto_detected_from_real_headers() -> None:
    headers = list(collectr_row())
    assert collectr_adapter_headers(headers)
    assert _detect_adapter(headers, "AUTO") == "COLLECTR"


def test_collectr_variance_maps_to_variant_and_zero_cost_stays_unknown() -> None:
    row = collectr_row()
    normalized, issues = _normalized_row(
        row,
        _field_map(list(row)),
        None,
        adapter="COLLECTR",
    )
    assert issues == []
    assert normalized["variant"] == "Foil"
    assert normalized["quantity"] == 3
    assert normalized["acquisition_cost_minor"] is None
    assert normalized["grading_company"] is None
    assert normalized["grade"] is None


def test_collectr_positive_cost_is_preserved_but_zero_is_not_free() -> None:
    assert collectr_cost_minor("0.0000") == (None, [])
    assert collectr_cost_minor("1.8700") == (187, [])
    assert collectr_cost_minor("2.6300") == (263, [])


def test_collectr_grades_are_normalized_without_scientific_notation() -> None:
    assert collectr_grade("Ungraded") == (None, None, [])
    assert collectr_grade("PSA 10.0 GEM - MT") == ("PSA", "10", [])
    assert collectr_grade("PSA 9.0 MINT") == ("PSA", "9", [])
    assert collectr_grade("ACE 10.0 GEM MINT") == ("ACE", "10", [])


def test_collectr_collection_and_don_product_types_are_conservative() -> None:
    assert collectr_product_type(
        name="Premium Card Collection -6 assort vol.1-",
        card_number=None,
        rarity=None,
    ) == "COLLECTION"
    assert collectr_product_type(
        name="One Piece Tin Pack Set Vol. 2 -Portgas.D.Ace-",
        card_number=None,
        rarity=None,
    ) == "COLLECTION"
    assert collectr_product_type(
        name="DON!! Card (Egghead)",
        card_number=None,
        rarity="DON!!",
    ) == "CARD"


def test_snapshot_identity_includes_finish_grade_and_condition() -> None:
    row = collectr_row()
    normalized, _ = _normalized_row(row, _field_map(list(row)), None, adapter="COLLECTR")
    raw_key = collectr_snapshot_key(normalized)

    reverse = dict(normalized, variant="Reverse Holofoil")
    psa = dict(normalized, grading_company="PSA", grade="10")
    played = dict(normalized, condition="Lightly Played")
    japanese = dict(normalized, language="Japanese")
    legacy_japanese = dict(normalized, name="Basil Hawkins (JP)", language=None)

    assert collectr_snapshot_key(reverse) != raw_key
    assert collectr_snapshot_key(psa) != raw_key
    assert collectr_snapshot_key(played) != raw_key
    assert collectr_snapshot_key(japanese) != raw_key
    assert collectr_snapshot_key(legacy_japanese) == collectr_snapshot_key(japanese)


def test_collectr_catalogue_identity_key_is_deterministic() -> None:
    row = collectr_row()
    normalized, _ = _normalized_row(row, _field_map(list(row)), None, adapter="COLLECTR")
    assert collectr_catalogue_identity_key(normalized) == collectr_catalogue_identity_key(dict(normalized))


def test_import_commit_contains_snapshot_baseline_concurrency_guard() -> None:
    source = IMPORTS.read_text()
    assert "Collectr baseline changed after preview" in source
    assert "collectr_quantity_decrease" in source
    assert "collectr_identity_missing_from_snapshot" in source
    assert "previous_quantity" in source
    assert "snapshot_quantity" in source
    assert "delta_quantity" in source
    assert "collectr_create_catalogue" in source


def test_explicit_title_language_is_parsed_and_removed_from_card_name() -> None:
    assert parse_title_language("Eiscue ex (JP)") == ("Eiscue ex", "Japanese")
    assert parse_title_language("Charizard - English") == ("Charizard", "English")
    assert parse_title_language("Luffy [EN]") == ("Luffy", "English")


def test_language_aliases_and_display_codes_are_deterministic() -> None:
    assert language_code("English") == "EN"
    assert language_code("EN") == "EN"
    assert language_code("Japanese") == "JP"
    assert language_code("JPN") == "JP"
    assert display_title("Eiscue ex (JP)", "Japanese") == "Eiscue ex · JP"


def test_collectr_title_language_populates_structured_language() -> None:
    row = collectr_row(**{"Product Name": "Eiscue ex (JP)", "Language": ""})
    normalized, issues = _normalized_row(
        row,
        _field_map(list(row)),
        None,
        adapter="COLLECTR",
    )
    assert issues == []
    assert normalized["name"] == "Eiscue ex"
    assert normalized["language"] == "Japanese"


def test_collectr_missing_language_requires_review() -> None:
    row = collectr_row(**{"Language": ""})
    normalized, issues = _normalized_row(
        row,
        _field_map(list(row)),
        None,
        adapter="COLLECTR",
    )
    assert normalized["language"] is None
    assert "missing_language" in issues


def test_explicit_language_conflict_requires_review() -> None:
    row = collectr_row(**{"Product Name": "Eiscue ex (JP)", "Language": "English"})
    row["Language"] = "English"
    headers = list(row)
    normalized, issues = _normalized_row(
        row,
        _field_map(headers),
        None,
        adapter="COLLECTR",
    )
    assert normalized["language"] == "English"
    assert "language_conflict" in issues


def test_explicit_language_backfill_is_fail_closed() -> None:
    sql = LANGUAGE_MIGRATION.read_text()
    assert "set language = 'Japanese'" in sql
    assert "bool_and" in sql
    assert "language is null" in sql
    assert "jp|jpn|japanese" in sql.lower()
    assert "set language = 'english'" not in sql.lower()


def test_unsupported_english_rollback_is_evidence_scoped_and_fail_closed() -> None:
    sql = LANGUAGE_ROLLBACK_MIGRATION.read_text()
    lowered = sql.lower()
    assert "old_values->>'language' is null" in lowered
    assert "new_values->>'language' = 'english'" in lowered
    assert "source_record->>'language'" in lowered
    assert "identity_verification_events" in lowered
    assert "i.identity_confirmed" in lowered
    assert "event_type = 'confirmed'" in lowered
    assert "set language = null" in lowered
    assert "set language = \'japanese\'" not in lowered
    assert "update tcg.inventory_items" in lowered
    assert "update tcg.catalogue_products" in lowered
