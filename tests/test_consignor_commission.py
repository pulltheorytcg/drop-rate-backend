from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260926182559_consignor_commission_10pct.sql"
)


def test_consignor_default_is_ten_percent_and_founder_is_zero() -> None:
    sql = MIGRATION.read_text()
    assert "when owner_type = 'CONSIGNOR' then 1000" in sql
    assert "when new.owner_type = 'CONSIGNOR' then 1000" in sql
    assert "owner_type = 'FOUNDER' and new.commission_bps <> 0" in sql
    assert "commission_bps between 0 and 10000" in sql


def test_commission_is_snapshotted_per_physical_sale() -> None:
    sql = MIGRATION.read_text()
    assert "commission_bps_snapshot" in sql
    assert "commission_minor" in sql
    assert "snapshot_order_item_commission" in sql
    assert "before insert on tcg.order_items" in sql
    assert "calculate_commission_minor" in sql


def test_commission_is_append_only_ledger_deduction() -> None:
    sql = MIGRATION.read_text()
    assert "'COMMISSION'" in sql
    assert "'COMMISSION_REVERSAL'" in sql
    assert "financial_ledger_commission" in sql
    assert "'commission:' || new.order_item_id::text" in sql
    assert "on conflict(source_key) do nothing" in sql


def test_item_refund_reverses_commission_proportionally() -> None:
    sql = MIGRATION.read_text()
    assert "cumulative_refund" in sql
    assert "target_retained_commission" in sql
    assert "target_reversal" in sql
    assert "reversal_delta" in sql
    assert "Item refunds exceed original net sale" in sql
    assert "commission-reversal:" in sql


def test_shipping_is_not_in_commission_basis() -> None:
    sql = MIGRATION.read_text()
    assert "new.sale_price_minor - new.discount_minor" in sql
    # Commission is snapshotted from the order item, not SHIPPING_REVENUE.
    snapshot_start = sql.index("create or replace function tcg.snapshot_order_item_commission")
    snapshot_end = sql.index("alter table tcg.financial_ledger_entries", snapshot_start)
    snapshot = sql[snapshot_start:snapshot_end]
    assert "SHIPPING_REVENUE" not in snapshot


def test_owner_commission_changes_are_audited() -> None:
    sql = MIGRATION.read_text()
    assert "audit_owner_commission_change" in sql
    assert "OWNER_COMMISSION_CHANGED" in sql
    assert "old.commission_bps" in sql
    assert "new.commission_bps" in sql


def test_all_sale_channels_emit_sale_revenue_for_database_commission_trigger() -> None:
    for path in (
        ROOT / "backend" / "app" / "finance.py",
        ROOT / "backend" / "app" / "shopify_pipeline.py",
        ROOT / "backend" / "app" / "ebay_sales.py",
    ):
        source = path.read_text()
        assert "insert into tcg.order_items" in source
        assert "SALE_REVENUE" in source


def test_stripe_payout_balance_uses_net_ledger_including_commission() -> None:
    source = (ROOT / "backend" / "app" / "stripe_connect.py").read_text()
    start = source.index("async def _owner_payout_balance")
    end = source.index('@router.get("/payouts/queue")', start)
    block = source[start:end]
    assert "sum(amount_minor)" in block
    assert "funds_status='AVAILABLE'" in block
    assert "entry_type" not in block
