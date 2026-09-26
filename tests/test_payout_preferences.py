from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.payout_preferences import PayoutPreferenceUpdate, next_scheduled_at


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260926203000_owner_payout_preferences.sql"
LONDON = ZoneInfo("Europe/London")


def test_daily_schedule_uses_next_local_day() -> None:
    now = datetime(2026, 9, 26, 21, 26, tzinfo=LONDON)
    value = next_scheduled_at(
        cadence="DAILY",
        weekday=None,
        monthly_day=None,
        fortnightly_anchor_date=None,
        now=now,
    )
    assert value == datetime(2026, 9, 27, 9, 0, tzinfo=LONDON)


def test_weekly_schedule_uses_selected_weekday() -> None:
    now = datetime(2026, 9, 26, 21, 26, tzinfo=LONDON)  # Saturday
    value = next_scheduled_at(
        cadence="WEEKLY",
        weekday=4,  # Friday
        monthly_day=None,
        fortnightly_anchor_date=None,
        now=now,
    )
    assert value == datetime(2026, 10, 2, 9, 0, tzinfo=LONDON)


def test_fortnightly_schedule_advances_in_14_day_cycles() -> None:
    now = datetime(2026, 10, 3, 12, 0, tzinfo=LONDON)
    value = next_scheduled_at(
        cadence="FORTNIGHTLY",
        weekday=4,
        monthly_day=None,
        fortnightly_anchor_date=date(2026, 10, 2),
        now=now,
    )
    assert value == datetime(2026, 10, 16, 9, 0, tzinfo=LONDON)


def test_monthly_schedule_clamps_day_to_shorter_month() -> None:
    now = datetime(2027, 2, 1, 8, 0, tzinfo=LONDON)
    value = next_scheduled_at(
        cadence="MONTHLY",
        weekday=None,
        monthly_day=31,
        fortnightly_anchor_date=None,
        now=now,
    )
    assert value == datetime(2027, 2, 28, 9, 0, tzinfo=LONDON)


def test_manual_schedule_has_no_automatic_due_date() -> None:
    assert next_scheduled_at(
        cadence="MANUAL",
        weekday=None,
        monthly_day=None,
        fortnightly_anchor_date=None,
    ) is None


def test_schedule_payload_requires_matching_selector() -> None:
    with pytest.raises(ValidationError):
        PayoutPreferenceUpdate(cadence="WEEKLY", weekday=None, version=0)
    with pytest.raises(ValidationError):
        PayoutPreferenceUpdate(cadence="MONTHLY", monthly_day=None, version=0)
    with pytest.raises(ValidationError):
        PayoutPreferenceUpdate(cadence="DAILY", weekday=1, version=0)


def test_payout_preferences_schema_is_owner_scoped_and_least_privilege() -> None:
    sql = MIGRATION.read_text()
    assert "create table if not exists tcg.payout_preferences" in sql
    assert "MANUAL','DAILY','WEEKLY','FORTNIGHTLY','MONTHLY" in sql
    assert "force row level security" in sql
    assert "grant select,insert,update on table tcg.payout_preferences to tcg_api" in sql
    assert "owner_id in (select o.id from tcg.owners o)" in sql
    assert "grant delete" not in sql.lower()
