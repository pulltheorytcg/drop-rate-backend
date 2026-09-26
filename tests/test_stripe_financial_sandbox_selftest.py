from __future__ import annotations

import pytest

from scripts.stripe_financial_sandbox_selftest import _expect


def test_financial_sandbox_expect_accepts_exact_value() -> None:
    _expect(9000, 9000, "owner balance")


def test_financial_sandbox_expect_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="commission"):
        _expect(999, 1000, "commission")


def test_financial_sandbox_script_has_rollback_and_core_money_assertions() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "await transaction.rollback()" in source
    assert "sale_price_minor, discount_minor" in source
    assert "net_sale_minor, cost_basis_minor" not in source
    assert "values($1, $2, $3, 10000, 0, 0" in source
    assert '_expect(int(item["commission_minor"]), 1000' in source
    assert '_expect(sale["balance_minor"], 9000' in source
    assert '_expect(partial_refund["balance_minor"], 4500' in source
    assert '_expect(full_refund["balance_minor"], 0' in source
    assert "on conflict(source_key) do nothing" in source
    assert "rollback_cleanup" in source
    assert 'startswith("sk_test_")' in source
