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

DENY_MIGRATION = ROOT / "database" / "migrations" / "20260926215000_schema_migrations_explicit_deny.sql"


def test_schema_migrations_has_explicit_deny_policy_for_application_role() -> None:
    sql = DENY_MIGRATION.read_text().lower()

    assert "create policy schema_migrations_deny_application" in sql
    assert "for all" in sql
    assert "to tcg_api" in sql
    assert "using (false)" in sql
    assert "with check (false)" in sql
    assert "grant " not in sql

