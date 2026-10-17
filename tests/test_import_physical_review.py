"""Pending-row corrections cannot erase unrelated issues or source identity."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.import_physical_review import ImportCardDetails, apply_card_details


def test_raw_correction_keeps_original_source_and_unrelated_review_gates():
    source = {"product_type": "CARD", "condition": None, "grade": "10",
              "grading_company": None, "certificate_number": "old-export-value",
              "_collectr_source_identity": ["original", "source"],
              "acquisition_cost_minor": None, "quantity": 3}
    before = deepcopy(source)
    issues = {"unrecognised_card_condition", "incomplete_grading_pair",
              "certificate_without_grade", "invalid_quantity", "invalid_purchase_cost",
              "language_conflict", "collectr_quantity_decrease"}
    corrected, remaining = apply_card_details(source, issues, ImportCardDetails(
        card_state="RAW", condition="Lightly Played"), quantity=3)
    assert corrected["condition"] == "Lightly Played"
    assert all(corrected[key] is None for key in ("grade", "grading_company", "certificate_number"))
    assert remaining == {"invalid_quantity", "invalid_purchase_cost", "language_conflict", "collectr_quantity_decrease"}
    assert source == before and "incomplete_grading_pair" in issues
    assert corrected["_collectr_source_identity"] == before["_collectr_source_identity"]
    assert corrected["quantity"] == 3 and corrected["acquisition_cost_minor"] is None


def test_graded_correction_normalizes_whitespace_and_keeps_raw_condition_empty():
    details = ImportCardDetails(card_state="GRADED", grading_company=" BGS ",
                                grade=" 9.5 ", certificate_number=" SAMPLE-123 ")
    corrected, issues = apply_card_details({"product_type": "CARD", "condition": "Near Mint"},
        {"unrecognised_collectr_grade"}, details, quantity=1)
    assert corrected["condition"] is None and not issues
    assert (corrected["grading_company"], corrected["grade"], corrected["certificate_number"]) == ("BGS", "9.5", "SAMPLE-123")


def test_unknown_raw_condition_is_explicitly_allowed_without_a_mint_default():
    result, issues = apply_card_details({"product_type": "CARD"}, {"unrecognised_card_condition"},
        ImportCardDetails(card_state="RAW"), quantity=1)
    assert result["condition"] is None and not issues


@pytest.mark.parametrize("fields", [
    {}, {"card_state": "OTHER"}, {"card_state": "RAW", "condition": "Mint"},
    {"card_state": "RAW", "grade": "10"}, {"card_state": "RAW", "certificate_number": "123"},
    {"card_state": "GRADED"}, {"card_state": "GRADED", "grading_company": " "},
    {"card_state": "GRADED", "grading_company": "PSA", "grade": " "},
    {"card_state": "GRADED", "grading_company": "PSA", "grade": "10", "condition": "Near Mint"},
    {"card_state": "RAW", "quantity": 99}, {"card_state": "RAW", "acquisition_cost_minor": 0},
    {"card_state": "RAW", "identity_confirmed": True},
])
def test_incomplete_contradictory_or_unrelated_fields_are_rejected(fields):
    with pytest.raises(ValidationError):
        ImportCardDetails(**fields)


@pytest.mark.parametrize("product_type", ["SEALED", "COLLECTION", "COMIC"])
def test_card_corrections_do_not_cross_product_types(product_type):
    with pytest.raises(ValueError, match="only apply to single cards"):
        apply_card_details({"product_type": product_type}, set(), ImportCardDetails(card_state="RAW"), quantity=1)


def test_one_certificate_cannot_be_copied_to_multiple_slabs():
    with pytest.raises(ValueError, match="one slab"):
        apply_card_details({"product_type": "CARD"}, set(), ImportCardDetails(
            card_state="GRADED", grading_company="PSA", grade="10", certificate_number="SAMPLE"), quantity=2)


def test_existing_seal_conflict_is_not_silently_cleared():
    with pytest.raises(ValueError, match="seal status"):
        apply_card_details({"product_type": "CARD", "seal_status": "SEALED"}, set(),
                           ImportCardDetails(card_state="RAW"), quantity=1)
