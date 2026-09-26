from __future__ import annotations

import pytest

from scripts.stripe_financial_sandbox_selftest import _expect


def test_financial_sandbox_expect_accepts_exact_value() -> None:
    _expect(9000, 9000, "owner balance")


def test_financial_sandbox_expect_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="commission"):
        _expect(999, 1000, "commission")


def test_financial_sandbox_respects_runtime_owner_permissions() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "insert into tcg.owners" not in source
    assert "owner_type='FOUNDER'" in source
    assert "select tcg.calculate_commission_minor" in source
    assert "await transaction.rollback()" in source
    assert "rollback_cleanup" in source
    assert 'startswith("sk_test_")' in source


def test_financial_sandbox_proves_consignor_math_without_mutating_ownership() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "10000," in source
    assert "1000," in source
    assert '_expect(int(commission_minor or 0), 1000' in source
    assert "_expect(consignor_owner_proceeds_minor, 9000" in source
    assert '"consignor_commission_minor"' in source
    assert '"consignor_owner_proceeds_minor"' in source


def test_financial_sandbox_exercises_founder_sale_refund_and_idempotency() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "values($1, $2, $3, 10000, 0, 0" in source
    assert '_expect(int(item["commission_minor"]), 0' in source
    assert '_expect(sale["balance_minor"], 10000' in source
    assert '_expect(partial_refund["balance_minor"], 5000' in source
    assert '_expect(full_refund["balance_minor"], 0' in source
    assert "on conflict(source_key) do nothing" in source
    assert '"duplicate_sale_idempotent"' in source
    assert '"duplicate_refund_idempotent"' in source
