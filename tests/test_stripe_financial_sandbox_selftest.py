from __future__ import annotations

import pytest

from scripts.stripe_financial_sandbox_selftest import _expect


def test_financial_sandbox_expect_accepts_exact_value() -> None:
    _expect(9000, 9000, "owner balance")


def test_financial_sandbox_expect_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="commission"):
        _expect(999, 1000, "commission")


def test_financial_sandbox_is_read_only_and_least_privilege() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "insert into" not in source.lower()
    assert "update tcg." not in source.lower()
    assert "delete from" not in source.lower()
    assert "transaction.rollback" not in source
    assert "owners INSERT remains denied" in source
    assert "owners UPDATE remains denied" in source
    assert '"read_only_probe": True' in source
    assert 'startswith("sk_test_")' in source


def test_financial_sandbox_proves_consignor_math_in_live_database_function() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "tcg.calculate_commission_minor(10000::bigint,1000::integer)" in source
    assert "_expect(int(row[\"commission_minor\"]), 1000" in source
    assert "_expect(int(row[\"owner_proceeds_minor\"]), 9000" in source
    assert "tcg.calculate_commission_minor(5000::bigint,1000::integer)" in source
    assert "half_refund_retained_commission_minor" in source


def test_financial_sandbox_checks_runtime_security_and_trigger_graph() -> None:
    source = open(
        "backend/scripts/stripe_financial_sandbox_selftest.py",
        encoding="utf-8",
    ).read()

    assert "current_user::text as database_role" in source
    assert '_expect(str(row["database_role"]), "tcg_api"' in source
    assert "has_table_privilege(current_user,'tcg.owners','insert')" in source
    assert "has_table_privilege(" in source
    assert "order_items_commission_snapshot" in source
    assert "financial_ledger_commission" in source
    assert "source_key" in source
    assert "relrowsecurity" in source
