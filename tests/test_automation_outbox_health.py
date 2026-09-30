from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.automation_health import check_automation_outbox_health


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930040000_automation_outbox_health.sql"
)
SCRIPT = ROOT / "backend" / "scripts" / "check_automation_outbox_health.py"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"
ACTION_CATEGORY_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930163000_action_required_automation_category.sql"
)


class _Connection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.row


@pytest.mark.asyncio
async def test_health_helper_uses_narrow_database_function() -> None:
    oldest = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)
    connection = _Connection(
        {
            "healthy": False,
            "alert_enabled": False,
            "pending_count": 396,
            "due_count": 396,
            "dispatching_count": 0,
            "dead_letter_count": 0,
            "oldest_pending_at": oldest,
            "oldest_pending_age_seconds": 3600,
            "stale_dispatching_count": 0,
            "alerted_founders": 0,
            "resolved_founders": 0,
        }
    )

    result = await check_automation_outbox_health(
        connection,
        alert_enabled=False,
        pending_age_threshold=timedelta(minutes=30),
    )

    assert result["healthy"] is False
    assert result["pending_count"] == 396
    assert result["oldest_pending_at"] == oldest
    assert len(connection.calls) == 1
    query, args = connection.calls[0]
    assert "tcg.check_automation_outbox_health" in query
    assert args == (False, timedelta(minutes=30))


@pytest.mark.asyncio
async def test_health_helper_rejects_unsafe_thresholds() -> None:
    connection = _Connection(None)
    with pytest.raises(ValueError, match="at least 5 minutes"):
        await check_automation_outbox_health(
            connection,
            pending_age_threshold=timedelta(minutes=4),
        )
    with pytest.raises(ValueError, match="at most 24 hours"):
        await check_automation_outbox_health(
            connection,
            pending_age_threshold=timedelta(hours=25),
        )
    assert connection.calls == []


def test_migration_is_narrow_and_founder_alerts_are_gated() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "security definer" in lower
    assert "check_automation_outbox_health" in lower
    assert "automation_outbox_unhealthy" in lower
    assert "p_alert_enabled" in lower
    assert "owner_type='founder'" in lower
    assert "dead_letter" in lower
    assert "lease_until <= clock_timestamp()" in lower
    assert "grant execute on function tcg.check_automation_outbox_health" in lower
    assert "grant select on tcg.automation_events" not in lower
    assert "delete from tcg.automation_events" not in lower


def test_dormant_mode_does_not_fail_operations_monitor() -> None:
    source = SCRIPT.read_text()
    monitor = MONITOR.read_text()

    assert 'TCG_AUTOMATION_OUTBOX_ALERTS_ENABLED' in source
    assert '"AUTOMATION_OUTBOX_HEALTH_OBSERVED_DORMANT"' in source
    assert "if not alert_enabled:" in source
    assert "return 0" in source

    assert 'check_automation_outbox_health.py' in monitor
    assert "automation_code == 0" in monitor
    assert '"automation_code": automation_code' in monitor


def test_active_unhealthy_mode_fails_and_surfaces_alert() -> None:
    source = SCRIPT.read_text()
    assert '"AUTOMATION_OUTBOX_UNHEALTHY"' in source
    assert "return 2" in source
    assert "alert_enabled=alert_enabled" in source


def test_action_required_category_allows_automation_alerts() -> None:
    sql = ACTION_CATEGORY_MIGRATION.read_text().casefold()

    assert "drop constraint action_required_items_category_check" in sql
    assert "add constraint action_required_items_category_check" in sql
    assert "'automation'::text" in sql
    for existing in (
        "identity",
        "media",
        "pricing",
        "import",
        "shopify",
        "channel",
        "settlement",
        "ownership",
        "duplicate",
        "customer_dispute",
    ):
        assert f"'{existing}'::text" in sql
