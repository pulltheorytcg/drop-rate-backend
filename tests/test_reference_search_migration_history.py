from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20261001140820_reference_search_corrections.sql"


def test_reference_selection_is_owner_scoped_and_review_gated() -> None:
    sql = MIGRATION.read_text().lower()
    assert "security definer" in sql
    assert "set search_path=pg_catalog" in sql
    assert "platform_admin','owner" in sql
    assert "m.user_id=v_user and m.active" in sql
    assert "'needs_review'" in sql
    assert "'requires_canonical_review',true" in sql


def test_reference_selection_has_no_browser_or_service_role_execute_grant() -> None:
    sql = MIGRATION.read_text().lower()
    assert "revoke all on function tcg.select_recognition_reference" in sql
    assert "from public,anon,authenticated,service_role" in sql
    assert "grant execute on function tcg.select_recognition_reference" in sql
    assert "to tcg_api" in sql
