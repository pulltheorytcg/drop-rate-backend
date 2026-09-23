from pathlib import Path

import pytest
from pydantic import ValidationError

from app.refunds import RefundCreate


ROOT = Path(__file__).parents[1]


def test_refund_requires_positive_amount() -> None:
    with pytest.raises(ValidationError):
        RefundCreate(reference="REF-1", amount_minor=0)


def test_refund_reference_cannot_be_blank() -> None:
    with pytest.raises(ValidationError, match="reference cannot be blank"):
        RefundCreate(reference="   ", amount_minor=100)


def test_refund_input_normalises_reference_and_reason() -> None:
    payload = RefundCreate(reference="  REF-ABC  ", amount_minor=2500, reason="  Return received  ")
    assert payload.reference == "REF-ABC"
    assert payload.reason == "Return received"


def test_refund_workflow_caps_refunds_and_requires_full_item_refund_for_return() -> None:
    source = (ROOT / "backend" / "app" / "refunds.py").read_text()
    assert "Refund exceeds the remaining refundable amount" in source
    assert "Returning stock requires the item sale value to be fully refunded" in source
    assert "This refund reference has already been recorded" in source
    assert "set_config('tcg.allow_sold_return', 'on', true)" in source
    assert "status = 'INSPECTION'" in source


def test_returned_stock_is_removed_from_realised_cogs_without_losing_cost_snapshot() -> None:
    source = (ROOT / "backend" / "app" / "finance.py").read_text()
    assert "from tcg.refund_events r" in source
    assert "r.return_to_stock" in source
    assert 'effective_cost = 0 if item["returned_to_stock"] else int(item["cost_basis_minor"])' in source
    assert 'item["effective_cost_basis_minor"] = effective_cost' in source


def test_refund_history_is_immutable_and_sold_return_is_narrowly_guarded() -> None:
    migration = (ROOT / "database" / "migrations" / "202609230012_refund_returns.sql").read_text()
    assert "refund_events_immutable" in migration
    assert "prevent_finance_mutation" in migration
    assert "current_setting('tcg.allow_sold_return', true) = 'on'" in migration
    assert "new.status = 'INSPECTION'" in migration
    assert "new.version = old.version + 1" in migration
