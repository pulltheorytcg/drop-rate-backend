from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "202609230017_grant_inventory_workflow_columns.sql"


def test_newer_inventory_workflows_have_explicit_update_grants() -> None:
    sql = MIGRATION.read_text().lower()
    for column in (
        "seal_status",
        "storage_location_id",
        "purchase_lot_id",
        "market_value_minor",
        "recommended_retail_minor",
        "pricing_updated_at",
        "latest_pricing_snapshot_id",
    ):
        assert column in sql
    assert "on tcg.inventory_items to tcg_api" in sql


def test_grant_does_not_expand_ownership_or_identity_columns() -> None:
    sql = MIGRATION.read_text().lower()
    grant_block = sql.split("grant update (", 1)[1].split(") on tcg.inventory_items", 1)[0]
    assert "owner_id" not in grant_block
    assert "catalogue_id" not in grant_block
    assert "inventory_code" not in grant_block
    assert "source_record" not in grant_block
