from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "database" / "migrations"


def test_application_cannot_delete_purchase_lot_history() -> None:
    sql = (MIGRATIONS / "202609230015_revoke_purchase_lot_delete.sql").read_text()
    assert "revoke delete on tcg.purchase_lots from tcg_api" in sql.lower()
