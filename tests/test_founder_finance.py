from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.finance import (
    ManualSaleCreate,
    PayoutRequestCreate,
    ShopifyPostageReconcile,
    _settlement_amounts,
    _settlement_reconciliation_state,
    allocate_minor,
)


ROOT = Path(__file__).parents[1]


def test_allocate_minor_preserves_every_penny() -> None:
    allocation = allocate_minor(1001, [700, 200, 100])
    assert allocation == [701, 200, 100]
    assert sum(allocation) == 1001


def test_allocate_minor_uses_equal_split_when_all_weights_are_zero() -> None:
    allocation = allocate_minor(100, [0, 0, 0])
    assert allocation == [34, 33, 33]
    assert sum(allocation) == 100


def test_manual_sale_rejects_duplicate_physical_inventory() -> None:
    inventory_id = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        ManualSaleCreate(
            reference="manual-test",
            items=[
                {"inventory_id": inventory_id, "sale_price_minor": 1000},
                {"inventory_id": inventory_id, "sale_price_minor": 2000},
            ],
        )


def test_manual_sale_rejects_discount_above_sale_price() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        ManualSaleCreate(
            reference="manual-test",
            items=[
                {
                    "inventory_id": uuid4(),
                    "sale_price_minor": 1000,
                    "discount_minor": 1001,
                }
            ],
        )


def test_payout_request_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PayoutRequestCreate(amount_minor=0)


def test_finance_migration_has_immutable_ledger_and_sold_state() -> None:
    sql = (ROOT / "database" / "migrations" / "202609230008_founder_finance_foundation.sql").read_text()
    assert "'SOLD'" in sql
    assert "financial_ledger_immutable" in sql
    assert "order_items_immutable" in sql
    assert "inventory_sold_immutable" in sql
    assert "enable row level security" in sql
    assert "revoke delete" in sql


def test_finance_summary_accounts_for_shipping_refunds_separately() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    migration = (
        ROOT
        / "database"
        / "migrations"
        / "20260924235450_shopify_shipping_refunds.sql"
    ).read_text()
    assert "SHIPPING_REFUND" in migration
    assert "shipping_refunds_minor" in source
    assert "entry_type = 'SHIPPING_REFUND'" in source
    assert '- shipping_refunds' in source
    assert 'int(item["shipping_refund_minor"])' in source


def test_shopify_sales_do_not_present_unknown_settlement_costs_as_final_profit() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    assert "missing_fee_sales" in source
    assert "missing_shipping_cost_sales" in source
    assert '"fees_complete": missing_fee_sales == 0' in source
    assert '"shipping_cost_complete": missing_shipping_cost_sales == 0' in source
    assert '"net_profit_complete": unreconciled_shopify_sales == 0' in source
    assert 'item["fees_complete"]' in source
    assert 'item["shipping_cost_complete"]' in source
    assert 'item["profit_complete"]' in source


def test_reconciliation_audit_trigger_uses_order_item_id() -> None:
    sql = (
        ROOT
        / "database"
        / "migrations"
        / "20260925144808_fix_order_item_reconciliation_audit_trigger.sql"
    ).read_text()
    assert "audit_order_item_reconciliation_change" in sql
    assert "new.order_item_id" in sql
    assert "old.order_item_id" in sql
    assert "new.id" not in sql
    assert "old.id" not in sql
    assert "revoke all on function tcg.audit_order_item_reconciliation_change() from public" in sql.casefold()


def test_order_item_reconciliation_metadata_is_rls_protected_and_audited() -> None:
    sql = (
        ROOT
        / "database"
        / "migrations"
        / "20260925141327_order_item_reconciliation.sql"
    ).read_text().casefold()
    assert "create table tcg.order_item_reconciliations" in sql
    assert "fees_reconciled_at" in sql
    assert "shipping_cost_reconciled_at" in sql
    assert "enable row level security" in sql
    assert "create policy own_records" in sql
    assert "grant select, insert, update" in sql
    assert "revoke delete" in sql
    assert "order_item_reconciliations_audit" in sql


def test_zero_postage_can_be_explicitly_reconciled() -> None:
    payload = ShopifyPostageReconcile(
        amount_minor=0,
        reference="not-shipped-test-order",
    )
    assert payload.amount_minor == 0
    assert payload.reference == "not-shipped-test-order"


def test_shopify_fee_reconciliation_is_fail_closed_and_idempotent() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    assert "get_order_transactions(" in source
    assert '"processing_fee": "PAYMENT_FEE"' in source
    assert "unmapped fee type" in source
    assert "AWAITING_RESPONSE" in source
    assert "UNKNOWN" in source
    assert "on conflict(source_key) do nothing" in source
    assert "SHOPIFY_ORDER_TRANSACTIONS" in source
    assert "exactly one visible order item" in source


def test_finance_completeness_uses_reconciliation_metadata_not_nonzero_ledger_rows() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    assert "tcg.order_item_reconciliations" in source
    assert "fees_reconciled_at is not null" in source
    assert "shipping_cost_reconciled_at is not null" in source
    assert 'item["fees_complete"]' in source
    assert 'item["shipping_cost_complete"]' in source


def test_owner_settlement_separates_proceeds_from_profit() -> None:
    result = _settlement_amounts(
        item_revenue_minor=1000,
        shipping_revenue_minor=200,
        item_refunds_minor=0,
        shipping_refunds_minor=0,
        platform_fees_minor=50,
        payment_fees_minor=30,
        shipping_cost_minor=100,
        adjustments_minor=0,
        effective_cogs_minor=400,
    )
    assert result == {
        "gross_proceeds_minor": 1200,
        "external_deductions_minor": 180,
        "net_owner_proceeds_minor": 1020,
        "owner_profit_minor": 620,
    }


def test_settlement_adjustments_change_proceeds_and_profit_explicitly() -> None:
    result = _settlement_amounts(
        item_revenue_minor=1000,
        shipping_revenue_minor=0,
        item_refunds_minor=0,
        shipping_refunds_minor=0,
        platform_fees_minor=0,
        payment_fees_minor=0,
        shipping_cost_minor=0,
        adjustments_minor=-125,
        effective_cogs_minor=400,
    )
    assert result["gross_proceeds_minor"] == 1000
    assert result["net_owner_proceeds_minor"] == 875
    assert result["owner_profit_minor"] == 475


def test_returned_refunded_order_restores_cost_basis_but_keeps_processing_loss() -> None:
    result = _settlement_amounts(
        item_revenue_minor=49,
        shipping_revenue_minor=499,
        item_refunds_minor=49,
        shipping_refunds_minor=499,
        platform_fees_minor=0,
        payment_fees_minor=36,
        shipping_cost_minor=0,
        adjustments_minor=0,
        effective_cogs_minor=0,
    )
    assert result["gross_proceeds_minor"] == 0
    assert result["net_owner_proceeds_minor"] == -36
    assert result["owner_profit_minor"] == -36


def test_settlement_reconciliation_state_is_fail_closed_for_shopify() -> None:
    assert _settlement_reconciliation_state(
        source="MANUAL",
        fees_reconciled=False,
        shipping_cost_reconciled=False,
    ) == ("VERIFIED", [])
    assert _settlement_reconciliation_state(
        source="SHOPIFY",
        fees_reconciled=False,
        shipping_cost_reconciled=False,
    ) == (
        "WAITING_FEES_AND_POSTAGE",
        ["Shopify/payment fees", "postage/fulfilment cost"],
    )
    assert _settlement_reconciliation_state(
        source="SHOPIFY",
        fees_reconciled=True,
        shipping_cost_reconciled=False,
    ) == ("WAITING_POSTAGE", ["postage/fulfilment cost"])
    assert _settlement_reconciliation_state(
        source="SHOPIFY",
        fees_reconciled=True,
        shipping_cost_reconciled=True,
    ) == ("VERIFIED", [])


def test_settlement_endpoint_is_owner_scoped_and_uses_append_only_ledger() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    start = source.index('@router.get("/finance/settlements")')
    end = source.index('@router.post("/finance/shopify/orders/{order_id}/reconcile-fees")', start)
    settlement = source[start:end]
    assert "where oi.owner_id=$1" in settlement
    assert "where le.owner_id=$1 and le.order_id is not null" in settlement
    assert "tcg.financial_ledger_entries" in settlement
    assert "tcg.order_item_reconciliations" in settlement
    assert "return_to_stock" in settlement
    assert "_settlement_amounts(" in settlement
    assert "_settlement_reconciliation_state(" in settlement


def test_finance_dashboard_exposes_required_sections() -> None:
    js = (ROOT / "backend" / "app" / "static" / "founder-finance.js").read_text()
    for text in (
        "Available balance",
        "Pending balance",
        "Net profit",
        "Sales revenue",
        "Cost of goods",
        "Postage cost",
        "Refunds",
        "Item + shipping refunds",
        "Payout requests",
        "Request payout",
    ):
        assert text in js
    assert "/api/v1/finance/summary" in js
    assert "/api/v1/finance/payouts" in js
