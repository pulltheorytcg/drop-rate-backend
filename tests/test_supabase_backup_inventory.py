"""Offline tests for read-only Supabase backup receipts (no access token/network)."""
from datetime import datetime, timezone

import pytest

from tools.supabase_backup_inventory import backup_receipt, completed_backups, _timestamp


def test_accepts_only_completed_backups():
    payload = {"backups": [
        {"id": 1, "status": "FAILED", "inserted_at": "2026-11-10T00:00:00Z"},
        {"id": 2, "status": "COMPLETED", "inserted_at": "2026-11-09T01:00:00Z"},
        {"id": 3, "status": "COMPLETED", "inserted_at": "2026-11-08T00:00:00Z"},
        {"id": 4, "status": "PENDING", "inserted_at": "2026-11-10T01:00:00Z"},
    ]}
    result = backup_receipt(payload, now=datetime(2026, 11, 10, 2, tzinfo=timezone.utc))
    assert result["completed_backup_count"] == 2
    assert result["latest_completed_backup_at"] == "2026-11-09T01:00:00+00:00"
    assert result["backup_within_48_hours"]
    assert not result["restoration_tested"]
    assert not result["r2_objects_backed_up"]


def test_empty_or_only_pending_backups_do_not_pass():
    for payload in ({"backups": []}, {"backups": [{"status": "PENDING"}]}):
        assert not backup_receipt(payload)["backup_within_48_hours"]


def test_stale_and_future_backups_do_not_pass():
    now = datetime(2026, 11, 10, 2, tzinfo=timezone.utc)
    old = {"backups": [{"status": "COMPLETED", "inserted_at": "2026-11-08T01:59:59Z"}]}
    future = {"backups": [{"status": "COMPLETED", "inserted_at": "2026-11-10T02:00:01Z"}]}
    assert not backup_receipt(old, now=now)["backup_within_48_hours"]
    assert not backup_receipt(future, now=now)["backup_within_48_hours"]


def test_invalid_backup_response_fails_closed():
    for payload in (None, [], {}, {"backups": "not a list"}, {"backups": [1]}):
        with pytest.raises(ValueError):
            completed_backups(payload)


def test_timezone_required():
    with pytest.raises(ValueError, match="timezone aware"):
        _timestamp("2026-11-10T02:00:00")
