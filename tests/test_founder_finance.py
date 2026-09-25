from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.finance import ManualSaleCreate, PayoutRequestCreate, allocate_minor


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


def test_finance_dashboard_exposes_required_sections() -> None:
    js = (ROOT / "backend" / "app" / "static" / "founder-finance.js").read_text()
    for text in (
        "Available balance",
        "Pending balance",
        "Net profit",
        "Sales revenue",
        "Cost of goods",
        "Shipping cost",
        "Refunds",
        "Item + shipping refunds",
        "Payout requests",
        "Request payout",
    ):
        assert text in js
    assert "/api/v1/finance/summary" in js
    assert "/api/v1/finance/payouts" in js
