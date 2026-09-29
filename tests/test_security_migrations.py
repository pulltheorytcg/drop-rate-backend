from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "database" / "migrations"


def test_application_cannot_delete_purchase_lot_history() -> None:
    sql = (MIGRATIONS / "202609230015_revoke_purchase_lot_delete.sql").read_text()
    assert "revoke delete on tcg.purchase_lots from tcg_api" in sql.lower()


def test_shopify_raw_pool_audit_writer_is_security_definer_and_admin_gated() -> None:
    sql = (
        MIGRATIONS / "20260929201000_shopify_raw_pool_audit_function.sql"
    ).read_text().lower()
    assert "security definer" in sql
    assert "if not tcg.is_platform_admin()" in sql
    assert "insert into tcg.audit_events" in sql
    assert "revoke all on function tcg.record_shopify_raw_pool_audit" in sql
    assert "grant execute on function tcg.record_shopify_raw_pool_audit" in sql
    assert "to tcg_api" in sql
