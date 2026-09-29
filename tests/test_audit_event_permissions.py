from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260929190500_allow_tcg_api_append_audit_events.sql"
)


def test_tcg_api_audit_access_is_append_only_and_admin_scoped() -> None:
    sql = MIGRATION.read_text().lower()

    assert "grant insert on table tcg.audit_events to tcg_api" in sql
    assert "grant usage on sequence tcg.audit_events_id_seq to tcg_api" in sql
    assert "revoke select, update, delete on table tcg.audit_events from tcg_api" in sql
    assert "revoke select, update on sequence tcg.audit_events_id_seq from tcg_api" in sql
    assert "create policy audit_api_insert" in sql
    assert "for insert" in sql
    assert "to tcg_api" in sql
    assert "tcg.is_platform_admin()" in sql
    assert "tcg.current_user_id() is not null" in sql
    assert "actor = tcg.current_user_id()::text" in sql
    assert "grant select" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
