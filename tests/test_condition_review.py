from pathlib import Path

from app.shopify_pipeline import _test_sync_missing


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "backend" / "app" / "condition_review.py"
MAIN = ROOT / "backend" / "app" / "main.py"
UI = ROOT / "backend" / "app" / "static" / "media-condition.js"
HELPER = ROOT / "backend" / "app" / "static" / "shopify-settings.js"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260926003000_media_condition_review.sql"
)


def ready_raw() -> dict:
    return {
        "status": "APPROVED",
        "identity_confirmed": True,
        "acquisition_cost_minor": 187,
        "product_type": "CARD",
        "grading_company": None,
        "grade": None,
        "condition": "Near Mint",
        "condition_review_status": "VERIFIED_NEAR_MINT",
        "seal_status": None,
        "language": "English",
        "catalogue_language": None,
        "store_price_minor": 499,
        "storage_location_id": "location-id",
        "registered_location_id": "location-id",
        "registered_location_active": True,
    }


def test_raw_card_only_requires_photo_backed_review_when_policy_requires_it() -> None:
    assert _test_sync_missing(ready_raw()) == []

    low_value_unreviewed = {**ready_raw(), "condition_review_status": "NOT_REVIEWED"}
    assert _test_sync_missing(low_value_unreviewed) == []

    high_value_unreviewed = {
        **ready_raw(),
        "store_price_minor": 5000,
        "condition_review_status": "NOT_REVIEWED",
    }
    assert _test_sync_missing(high_value_unreviewed) == [
        "photo-backed Near Mint verification"
    ]

    played = {
        **ready_raw(),
        "condition": "Lightly Played",
        "condition_review_status": "REJECTED_BELOW_NEAR_MINT",
    }
    assert _test_sync_missing(played) == [
        "Near Mint condition",
        "photo-backed Near Mint verification",
    ]


def test_graded_card_uses_separate_slab_verification_gate() -> None:
    graded = {
        **ready_raw(),
        "grading_company": "PSA",
        "grade": "10",
        "condition": None,
        "condition_review_status": "VERIFIED_GRADED",
    }
    assert _test_sync_missing(graded) == []

    graded["condition_review_status"] = "NOT_REVIEWED"
    assert _test_sync_missing(graded) == ["graded slab verification"]


def test_condition_review_schema_is_owner_scoped_and_append_only() -> None:
    sql = MIGRATION.read_text().casefold()

    assert "add column capture_context text" in sql
    assert "raw_unsleeved" in sql
    assert "penny_sleeve" in sql
    assert "top_loader" in sql
    assert "graded_slab" in sql
    assert "verified_near_mint" in sql
    assert "verified_graded" in sql
    assert "rejected_below_near_mint" in sql
    assert "create table tcg.condition_review_events" in sql
    assert "front_media_asset_id" in sql
    assert "back_media_asset_id" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "create policy own_condition_review_reads" in sql
    assert "create policy own_condition_review_inserts" in sql
    assert "grant select,insert on tcg.condition_review_events to tcg_api" in sql
    assert "revoke update,delete on tcg.condition_review_events from tcg_api" in sql


def test_condition_review_requires_exact_ready_front_and_back_evidence() -> None:
    source = SOURCE.read_text()

    assert "scope='INVENTORY_ITEM'" in source
    assert "side in ('FRONT','BACK')" in source
    assert "approval_status='APPROVED'" in source
    assert "rights_status='VERIFIED'" in source
    assert "shopify_file_status='READY'" in source
    assert "capture_context is not null" in source
    assert "Ready physical-item FRONT and BACK photos are required" in source
    assert "front_media_asset_id" in source
    assert "back_media_asset_id" in source


def test_condition_decisions_fail_closed_and_reshoot_reopens_media_capture() -> None:
    source = SOURCE.read_text()

    assert 'payload.decision == "APPROVE_NEAR_MINT"' in source
    assert '"Near Mint"' in source
    assert '"VERIFIED_NEAR_MINT"' in source
    assert 'payload.decision == "VERIFY_GRADED"' in source
    assert '"VERIFIED_GRADED"' in source
    assert 'payload.decision == "REJECT_BELOW_NEAR_MINT"' in source
    assert '"REJECTED_BELOW_NEAR_MINT"' in source
    assert "approval_status='REJECTED'" in source
    assert '"NEEDS_RESHOOT"' in source
    assert "condition_review_events" in source
    assert "where i.id=$1 and i.owner_id=$2" in source
    assert "for update of i" in source


def test_condition_review_router_is_wired_and_never_publishes() -> None:
    source = SOURCE.read_text()
    main = MAIN.read_text()

    assert "from .condition_review import router as condition_review_router" in main
    assert "app.include_router(condition_review_router, dependencies=[Depends(require_platform_admin_request)])" in main
    assert '@router.get("/queue")' in source
    assert '@router.post("/{inventory_id}")' in source
    assert "publish_product" not in source
    assert "create_product" not in source
    assert "ShopifyAdminClient" not in source


def test_media_condition_ui_exposes_physical_capture_and_human_review() -> None:
    ui = UI.read_text()
    helper = HELPER.read_text()

    assert "Media & Condition" in ui
    assert "This queue contains only Inventory IDs that require physical proof" in ui
    assert 'id="shopify-media-context"' in ui
    assert "RAW_UNSLEEVED" in ui
    assert "PENNY_SLEEVE" in ui
    assert "TOP_LOADER" in ui
    assert "GRADED_SLAB" in ui
    assert 'capture="environment"' in ui
    assert "Approve Near Mint" in ui
    assert "Block from sale" in ui
    assert "Request reshoot" in ui
    assert "Verify graded slab" in ui
    assert "/api/v1/condition-review/queue" in ui
    assert "/api/v1/condition-review/" in ui
    assert "does not publish" in ui
    assert "capture_context: captureContext || null" in helper


def test_ai_is_assistive_not_an_approval_path() -> None:
    ui = UI.read_text()
    source = SOURCE.read_text()

    assert "AI condition assistance can be added to suggest defects and confidence" in ui
    assert "Human verification remains the listing gate" in ui
    assert '"ai_can_suggest_but_not_override": True' in source
    assert "physical_photo_policy" in source
    assert "OpenAI" not in source
    assert "Anthropic" not in source
    assert "auto_approve" not in source.casefold()
