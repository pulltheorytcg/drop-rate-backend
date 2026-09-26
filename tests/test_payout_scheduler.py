from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.payout_scheduler import cycle_key, latest_due_at, queue_due_payouts


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260926210000_scheduled_payout_worker.sql"
SCRIPT = ROOT / "backend" / "scripts" / "run_payout_scheduler.py"
LONDON = ZoneInfo("Europe/London")


def test_daily_latest_due_before_and_after_nine() -> None:
    before = datetime(2026, 9, 26, 8, 30, tzinfo=LONDON)
    after = datetime(2026, 9, 26, 9, 30, tzinfo=LONDON)

    assert latest_due_at(
        cadence="DAILY",
        weekday=None,
        monthly_day=None,
        fortnightly_anchor_date=None,
        now=before,
    ) == datetime(2026, 9, 25, 9, 0, tzinfo=LONDON)

    assert latest_due_at(
        cadence="DAILY",
        weekday=None,
        monthly_day=None,
        fortnightly_anchor_date=None,
        now=after,
    ) == datetime(2026, 9, 26, 9, 0, tzinfo=LONDON)


def test_weekly_latest_due_catches_up_after_selected_day() -> None:
    now = datetime(2026, 9, 26, 12, 0, tzinfo=LONDON)  # Saturday
    due = latest_due_at(
        cadence="WEEKLY",
        weekday=4,
        monthly_day=None,
        fortnightly_anchor_date=None,
        now=now,
    )
    assert due == datetime(2026, 9, 25, 9, 0, tzinfo=LONDON)


def test_fortnightly_latest_due_uses_anchor_cycle() -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=LONDON)
    due = latest_due_at(
        cadence="FORTNIGHTLY",
        weekday=4,
        monthly_day=None,
        fortnightly_anchor_date=date(2026, 10, 2),
        now=now,
    )
    assert due == datetime(2026, 10, 16, 9, 0, tzinfo=LONDON)


def test_monthly_latest_due_clamps_short_month() -> None:
    now = datetime(2027, 3, 1, 8, 0, tzinfo=LONDON)
    due = latest_due_at(
        cadence="MONTHLY",
        weekday=None,
        monthly_day=31,
        fortnightly_anchor_date=None,
        now=now,
    )
    assert due == datetime(2027, 2, 28, 9, 0, tzinfo=LONDON)


def test_cycle_key_is_stable_and_timezone_explicit() -> None:
    due = datetime(2026, 10, 2, 9, 0, tzinfo=LONDON)
    assert cycle_key(due) == "payout-cycle:2026-10-02T09:00:00+01:00"


class FakeConnection:
    def __init__(self, *, create_reason: str = "CREATED"):
        self.create_reason = create_reason
        self.create_calls = 0

    async def fetch(self, query: str):
        assert "payout_scheduler_candidates" in query
        return [
            {
                "owner_id": UUID("11111111-1111-1111-1111-111111111111"),
                "owner_type": "CONSIGNOR",
                "owner_active": True,
                "cadence": "WEEKLY",
                "weekday": 4,
                "monthly_day": None,
                "fortnightly_anchor_date": None,
                "timezone": "Europe/London",
                "preference_version": 3,
                "stripe_ready": True,
                "available_to_withdraw_minor": 9000,
            }
        ]

    async def fetchrow(self, query: str, *args):
        assert "create_scheduled_payout_request" in query
        self.create_calls += 1
        if self.create_reason == "DUPLICATE_CYCLE":
            return {
                "payout_request_id": UUID("22222222-2222-2222-2222-222222222222"),
                "created": False,
                "amount_minor": 9000,
                "payout_code": "PAY-2026-TEST0001",
                "reason": "DUPLICATE_CYCLE",
            }
        return {
            "payout_request_id": UUID("22222222-2222-2222-2222-222222222222"),
            "created": True,
            "amount_minor": 9000,
            "payout_code": "PAY-2026-TEST0001",
            "reason": "CREATED",
        }


@pytest.mark.asyncio
async def test_worker_creates_one_due_request() -> None:
    connection = FakeConnection()
    result = await queue_due_payouts(
        connection,
        now=datetime(2026, 9, 26, 12, 0, tzinfo=LONDON),
    )
    assert result["ok"] is True
    assert result["checked"] == 1
    assert result["created"] == 1
    assert result["duplicate"] == 0
    assert connection.create_calls == 1
    assert result["payouts"][0]["amount_minor"] == 9000


@pytest.mark.asyncio
async def test_worker_treats_same_cycle_as_idempotent_duplicate() -> None:
    connection = FakeConnection(create_reason="DUPLICATE_CYCLE")
    result = await queue_due_payouts(
        connection,
        now=datetime(2026, 9, 26, 12, 0, tzinfo=LONDON),
    )
    assert result["ok"] is True
    assert result["created"] == 0
    assert result["duplicate"] == 1
    assert connection.create_calls == 1


def test_scheduler_database_boundary_rechecks_invariants() -> None:
    sql = MIGRATION.read_text()
    assert "payout_requests_scheduled_cycle_uidx" in sql
    assert "security definer" in sql.lower()
    assert "OWNER_INACTIVE" in sql
    assert "STRIPE_NOT_READY" in sql
    assert "PREFERENCE_CHANGED" in sql
    assert "NO_AVAILABLE_BALANCE" in sql
    assert "DUPLICATE_CYCLE" in sql
    assert "status in ('REQUESTED','APPROVED')" in sql
    assert "SCHEDULED_PAYOUT_REQUEST_CREATED" in sql


def test_scheduler_never_imports_or_calls_stripe() -> None:
    source = SCRIPT.read_text()
    assert "stripe" not in source.lower()
    assert "TCG_DATABASE_URL" in source
    assert "queue_due_payouts" in source

def test_scheduler_dockerfile_is_minimal_and_runs_worker() -> None:
    dockerfile = (ROOT / "Dockerfile.scheduler").read_text()
    assert "FROM python:3.12-slim" in dockerfile
    assert "PYTHONPATH=/app/backend" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "run_payout_scheduler.py" in dockerfile
    assert "uvicorn" not in dockerfile.lower()

