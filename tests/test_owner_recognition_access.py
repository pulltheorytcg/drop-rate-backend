from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
API = ROOT / "backend" / "app" / "recognition.py"
REFERENCE = ROOT / "backend" / "app" / "recognition_reference_index.py"
LEARNING = ROOT / "backend" / "app" / "recognition_learning.py"
MIGRATION = ROOT / "database" / "migrations" / "20260928195000_owner_recognition_access.sql"


def test_recognition_router_is_not_globally_platform_admin_only() -> None:
    main = MAIN.read_text()

    assert "app.include_router(recognition_router)" in main
    assert "app.include_router(recognition_router, dependencies=[Depends(require_platform_admin_request)])" not in main


def test_recognition_global_maintenance_routes_stay_platform_admin_only() -> None:
    source = API.read_text()

    for route in (
        '@router.get("/reference-index/status")',
        '@router.post("/reference-index/rebuild")',
        '@router.get("/learning/status")',
    ):
        start = source.index(route)
        block = source[start : source.find("\n\n@router.", start + 1) if source.find("\n\n@router.", start + 1) != -1 else len(source)]
        assert "Depends(require_platform_admin_request)" in block

    for route in (
        '@router.get("/status")',
        '@router.post("/resolve")',
        '@router.get("/runs")',
        '@router.post("/runs/{run_id}/feedback")',
    ):
        start = source.index(route)
        block = source[start : source.find("\n\n@router.", start + 1) if source.find("\n\n@router.", start + 1) != -1 else len(source)]
        assert "Depends(require_platform_admin_request)" not in block


def test_owner_feedback_is_recorded_but_not_trusted_for_learning_until_verified() -> None:
    source = API.read_text()

    assert 'if owner["role"] == "PLATFORM_ADMIN":' in source
    assert '"reason": "PENDING_DROP_RATE_VERIFICATION"' in source
    assert "materialize_learning_example(" in source


def test_owner_scan_does_not_mutate_global_model_registry() -> None:
    source = API.read_text()
    marker = "await register_runtime_model("
    assert marker in source
    before = source[max(0, source.index(marker) - 180) : source.index(marker)]
    assert 'if owner["role"] == "PLATFORM_ADMIN":' in before


def test_owner_recognition_rls_is_owner_scoped_and_cross_owner_fail_closed() -> None:
    sql = MIGRATION.read_text()

    for table in (
        "tcg.recognition_runs",
        "tcg.recognition_candidates",
        "tcg.recognition_feedback",
    ):
        assert table in sql

    assert "tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')" in sql
    assert "m.user_id=tcg.current_user_id()" in sql
    assert "m.active" in sql
    assert "created_by_user_id=tcg.current_user_id()" in sql
    assert "actor_user_id=tcg.current_user_id()" in sql


def test_shared_learning_and_reference_evidence_is_exposed_only_via_narrow_functions() -> None:
    sql = MIGRATION.read_text()
    reference = REFERENCE.read_text()
    learning = LEARNING.read_text()

    for fn in (
        "tcg.recognition_reference_hint_rows",
        "tcg.recognition_learning_hint_rows",
        "tcg.recognition_learning_visual_rows",
    ):
        assert fn in sql
        assert "security definer" in sql
        assert f"grant execute on function {fn}" in sql

    assert "from public,anon,authenticated,service_role" in sql
    assert "tcg.recognition_reference_hint_rows($1,$2)" in reference
    assert "tcg.recognition_learning_hint_rows($1,$2)" in learning
    assert "tcg.recognition_learning_visual_rows($1::uuid[],$2)" in learning


def test_owner_access_migration_does_not_open_global_learning_or_model_tables() -> None:
    sql = MIGRATION.read_text()

    assert "drop policy if exists api_insert on tcg.recognition_learning_examples" not in sql
    assert "drop policy if exists api_insert on tcg.recognition_hard_negatives" not in sql
    assert "drop policy if exists api_insert on tcg.recognition_model_versions" not in sql
    assert "drop policy if exists api_insert on tcg.recognition_reference_fingerprints" not in sql
