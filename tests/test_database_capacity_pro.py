"""Regression tests for explicit Supabase Pro capacity preflight.

No database, billing API, or production writes are required.
"""
import pytest

from app import database_capacity as capacity


def test_no_plan_override_preserves_free_guard(monkeypatch):
    monkeypatch.delenv(capacity.PLAN_ENV, raising=False)
    state = capacity.assess_capacity(428_000_000, "off")
    assert state.plan == "free"
    assert state.database_limit_bytes == 500_000_000
    assert not state.refresh_allowed
    assert state.reason == "BULK_REFRESH_DEFERRED_CAPACITY"


def test_explicit_pro_allows_current_database_size():
    state = capacity.assess_capacity(428_000_000, "off", plan="pro")
    assert state.plan == "pro"
    assert state.database_limit_bytes == 8_000_000_000
    assert state.remaining_bytes == 7_572_000_000
    assert state.refresh_allowed
    assert state.reason == "WITHIN_SAFE_BULK_REFRESH_CAPACITY"
    assert state.report()["database_plan"] == "pro"


def test_pro_bounds_avoid_automatic_billable_database_growth():
    assert capacity.assess_capacity(6_999_999_999, "off", plan="pro").refresh_allowed
    warning = capacity.assess_capacity(7_000_000_000, "off", plan="pro")
    assert not warning.refresh_allowed
    assert warning.severity == "WARNING"
    critical = capacity.assess_capacity(7_500_000_000, "off", plan="pro")
    assert not critical.refresh_allowed
    assert critical.severity == "CRITICAL"
    assert critical.reason == "DATABASE_CAPACITY_URGENT"


def test_plan_cannot_override_postgres_read_only():
    state = capacity.assess_capacity(1, "on", plan="pro")
    assert not state.refresh_allowed
    assert state.reason == "DATABASE_READ_ONLY"


def test_plan_name_must_be_explicit_and_valid():
    with pytest.raises(ValueError, match="Unknown Supabase capacity plan"):
        capacity.assess_capacity(1, "off", plan="team")
    with pytest.raises(ValueError, match="Unknown Supabase capacity plan"):
        capacity.assess_capacity(1, "off", plan="")


def test_reject_non_integer_size_and_missing_write_mode():
    with pytest.raises(ValueError):
        capacity.assess_capacity(1.5, "off", plan="pro")
    with pytest.raises(ValueError):
        capacity.assess_capacity(1, "unknown", plan="pro")


@pytest.mark.parametrize("size,allowed", [
    (399_999_999, True), (400_000_000, False),
    (450_000_000, False), (500_000_000, False),
])
def test_original_free_thresholds_unchanged(size, allowed):
    assert capacity.assess_capacity(size, "off", plan="free").refresh_allowed is allowed
