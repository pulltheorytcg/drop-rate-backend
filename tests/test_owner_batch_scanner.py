from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECOGNITION = ROOT / "backend" / "app" / "recognition.py"
OWNER_API = ROOT / "backend" / "app" / "owner_portal_api.py"
MIGRATION = ROOT / "database" / "migrations" / "20260928200500_owner_batch_scanner.sql"


def test_search_correction_is_a_first_class_audited_feedback_outcome() -> None:
    api = RECOGNITION.read_text()
    sql = MIGRATION.read_text()

    assert '"CORRECTED_BY_SEARCH"' in api
    assert "'CORRECTED_BY_SEARCH'" in sql
    assert "Search correction must select a recognised catalogue card" in api
    assert "Search correction must select a recognised catalogue card" in sql
    assert "selected_catalogue_id is not null" in sql


def test_search_correction_does_not_need_to_be_an_ai_candidate() -> None:
    api = RECOGNITION.read_text()

    search_start = api.index('if payload.outcome == "CORRECTED_BY_SEARCH"')
    search_block = api[search_start : search_start + 1500]
    assert "tcg.catalogue_products" in search_block
    assert "tcg.recognition_candidates" not in search_block

    candidate_start = api.index('if payload.outcome == "CORRECTED_TO_CANDIDATE"')
    candidate_block = api[candidate_start : candidate_start + 1200]
    assert "tcg.recognition_candidates" in candidate_block


def test_candidate_reference_value_is_global_safe_projection_not_owner_inventory_lookup() -> None:
    api = RECOGNITION.read_text()
    sql = MIGRATION.read_text()

    run_payload = api[api.index("async def _run_payload") : api.index('@router.get("/status")')]
    assert "tcg.recognition_catalogue_reference_value(" in run_payload
    assert "where i.owner_id=$2" not in run_payload
    assert "REFERENCE_SNAPSHOT" in run_payload

    assert "security definer" in sql
    assert "set search_path=pg_catalog" in sql
    assert "grant execute on function tcg.recognition_catalogue_reference_value(uuid,text) to tcg_api" in sql
    assert "from public,anon,authenticated,service_role" in sql


def test_owner_catalogue_search_returns_only_safe_card_identity_and_approved_media() -> None:
    source = OWNER_API.read_text()
    start = source.index('@router.get("/catalogue-search")')
    end = source.index('@router.get("/inventory")', start)
    block = source[start:end]

    assert "Depends(require_owner_portal_request)" in block
    assert "p.product_type='CARD'" in block
    assert "p.card_number" in block
    assert "p.name" in block
    assert "p.set_name" in block
    assert "tcg.recognition_catalogue_reference_value" in block
    assert "m.approval_status='APPROVED'" in block
    assert "m.rights_status='VERIFIED'" in block
    assert "m.rights_tier='STOREFRONT_ALLOWED'" in block
    assert "m.source_status='ACTIVE'" in block
    assert "m.revoked_at is null" in block

    for forbidden in (
        "acquisition_cost_minor",
        "storage_location_id",
        "purchase_lot_id",
        "notes",
        "created_by_user_id",
    ):
        assert forbidden not in block


def test_owner_intake_accepts_audited_search_correction_but_not_unconfirmed_catalogue_choice() -> None:
    source = OWNER_API.read_text()
    start = source.index('@router.post("/recognition-intake"')
    block = source[start:]

    assert '"CORRECTED_BY_SEARCH"' in block
    assert "Confirm or correct the recognition result before adding it to inventory" in block
    assert '"confirmation_source": feedback["outcome"]' in block
    assert 'feedback["selected_catalogue_id"] != payload.selected_catalogue_id' in block
    assert "false,'DRAFT'" in block


def test_verified_learning_can_include_search_corrections_only_after_materialisation() -> None:
    sql = MIGRATION.read_text()

    assert "recognition_learning_examples_label_outcome_check" in sql
    assert "'CORRECTED_BY_SEARCH'" in sql
    assert "create or replace function tcg.recognition_learning_hint_rows" in sql
    assert "create or replace function tcg.recognition_learning_visual_rows" in sql
    assert "e.dataset_split='TRAIN'" in sql
