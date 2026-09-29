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
    assert "stripe_connect" not in source
    assert "StripeConnect" not in source
    assert "httpx" not in source
    assert "requests" not in source
    assert "TCG_DATABASE_URL" in source
    assert "queue_due_payouts" in source

def test_scheduler_dockerfile_is_minimal_and_runs_worker() -> None:
    dockerfile = (ROOT / "Dockerfile.scheduler").read_text()
    assert "FROM python:3.12-slim" in dockerfile
    assert "PYTHONPATH=/app/backend" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "run_payout_scheduler.py" in dockerfile
    assert "uvicorn" not in dockerfile.lower()

OBSERVABILITY_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260926223000_payout_scheduler_run_observability.sql"
)


def test_scheduler_run_observability_is_append_only_to_application_roles() -> None:
    sql = OBSERVABILITY_MIGRATION.read_text().lower()

    assert "create table if not exists tcg.payout_scheduler_runs" in sql
    assert "force row level security" in sql
    for role in ("public", "anon", "authenticated", "service_role", "tcg_api", "tcg_auditor"):
        assert f"revoke all on tcg.payout_scheduler_runs from {role}" in sql
    assert "security definer" in sql
    assert "start_payout_scheduler_run" in sql
    assert "finish_payout_scheduler_run" in sql
    assert "fail_stale_payout_scheduler_runs" in sql


def test_scheduler_runner_persists_success_and_failure_outcomes() -> None:
    source = SCRIPT.read_text()

    assert "tcg.start_payout_scheduler_run()" in source
    assert "tcg.finish_payout_scheduler_run(" in source
    assert "tcg.fail_stale_payout_scheduler_runs" in source
    assert 'status = "SUCCESS" if summary["ok"] else "FAILED"' in source
    assert 'status="FAILED"' in source
    assert '"scheduler_run_id": str(run_id)' in source


def test_scheduler_startup_diagnostics_are_safe_and_stage_specific() -> None:
    source = SCRIPT.read_text()

    assert "PAYOUT_SCHEDULER_PROCESS_START" in source
    assert "PAYOUT_SCHEDULER_IMPORT_FAILED" in source
    assert "PAYOUT_SCHEDULER_DB_CONNECT_START" in source
    assert "PAYOUT_SCHEDULER_DB_CONNECT_FAILED" in source
    assert "PAYOUT_SCHEDULER_DB_CONNECTED" in source
    assert "PAYOUT_SCHEDULER_RUN_STARTING" in source
    assert "PAYOUT_SCHEDULER_RUN_STARTED" in source
    assert "database_url_configured" in source
    assert "timeout=15" in source
    assert '"detail": str(exc)' not in source
    assert "print(database_url)" not in source



HEARTBEAT_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260929013000_payout_scheduler_heartbeat.sql"
)
HEARTBEAT_SCRIPT = ROOT / "backend" / "scripts" / "check_payout_scheduler_heartbeat.py"


class FakeHeartbeatConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, query: str, *args):
        self.calls.append((query, args))
        return self.row


@pytest.mark.asyncio
async def test_scheduler_heartbeat_surfaces_unhealthy_state() -> None:
    from app.payout_scheduler import check_scheduler_heartbeat

    connection = FakeHeartbeatConnection(
        {
            "healthy": False,
            "last_completed_at": datetime(2026, 9, 28, 20, 0, tzinfo=LONDON),
            "last_status": "SUCCESS",
            "alerted_founders": 2,
            "resolved_founders": 0,
        }
    )
    result = await check_scheduler_heartbeat(connection)

    assert result["healthy"] is False
    assert result["alerted_founders"] == 2
    assert "check_payout_scheduler_heartbeat" in connection.calls[0][0]


@pytest.mark.asyncio
async def test_scheduler_heartbeat_rejects_unsafe_short_threshold() -> None:
    from datetime import timedelta
    from app.payout_scheduler import check_scheduler_heartbeat

    connection = FakeHeartbeatConnection(None)
    with pytest.raises(ValueError, match="at least 30 minutes"):
        await check_scheduler_heartbeat(
            connection,
            threshold=timedelta(minutes=5),
        )
    assert connection.calls == []


def test_scheduler_heartbeat_migration_is_founder_scoped_and_fail_closed() -> None:
    sql = HEARTBEAT_MIGRATION.read_text().lower()

    assert "default interval '90 minutes'" in sql
    assert "payout_scheduler_unhealthy" in sql
    assert "owner_type='founder'" in sql.replace(" ", "")
    assert "security definer" in sql
    assert "revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from public" in sql
    assert "grant execute on function tcg.check_payout_scheduler_heartbeat(interval) to tcg_api" in sql
    assert "on conflict(owner_id,dedupe_key)" in sql.replace(" ", "")
    assert "status='resolved'" in sql.replace(" ", "")


def test_scheduler_heartbeat_runner_never_logs_database_url() -> None:
    source = HEARTBEAT_SCRIPT.read_text()

    assert "PAYOUT_SCHEDULER_HEARTBEAT_PROCESS_START" in source
    assert "PAYOUT_SCHEDULER_HEARTBEAT_UNHEALTHY" in source
    assert "PAYOUT_SCHEDULER_HEARTBEAT_HEALTHY" in source
    assert "database_url_configured" in source
    assert "print(database_url)" not in source
    assert '"detail": str(exc)' not in source
