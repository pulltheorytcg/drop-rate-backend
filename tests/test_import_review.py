from pathlib import Path

from app.import_review import remaining_issues_after_catalogue_selection


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
REVIEW = ROOT / "backend" / "app" / "import_review.py"


def test_catalogue_selection_resolves_only_identity_issues() -> None:
    issues = [
        "catalogue_not_found",
        "ambiguous_catalogue_match",
        "missing_card_number",
        "unrecognised_card_condition",
        "non_gbp_purchase_cost",
    ]
    assert remaining_issues_after_catalogue_selection(issues) == [
        "non_gbp_purchase_cost",
        "unrecognised_card_condition",
    ]


def test_catalogue_selection_can_make_identity_only_row_ready() -> None:
    assert remaining_issues_after_catalogue_selection(
        ["missing_game", "missing_set", "catalogue_not_found"]
    ) == []


def test_import_review_api_uses_version_protection_and_preview_only_guard() -> None:
    source = REVIEW.read_text()
    assert "expected_version" in source
    assert 'batch["status"] != "PREVIEW"' in source
    assert 'candidate["status"] == "COMMITTED"' in source
    assert "version = version + 1" in source


def test_import_review_api_checks_selected_product_type() -> None:
    source = REVIEW.read_text()
    assert "Selected catalogue product has a different product type" in source
    assert "expected_product_type" in source


def test_import_review_router_is_wired_into_app() -> None:
    source = MAIN.read_text()
    assert "from .import_review import router as import_review_router" in source
    assert "app.include_router(import_review_router, dependencies=[Depends(require_platform_admin_request)])" in source
