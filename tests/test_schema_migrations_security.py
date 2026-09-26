from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260926214500_harden_schema_migrations_rls.sql"


def test_schema_migrations_is_infrastructure_only() -> None:
    sql = MIGRATION.read_text().lower()

    assert "alter table tcg.schema_migrations enable row level security" in sql
    assert "alter table tcg.schema_migrations force row level security" in sql
    for role in ("public", "anon", "authenticated", "service_role", "tcg_api", "tcg_auditor"):
        assert f"revoke all on table tcg.schema_migrations from {role}" in sql

    assert "create policy" not in sql
