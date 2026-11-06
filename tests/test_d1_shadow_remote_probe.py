"""The Cloudflare pilot's full sequence under a local SQLite API double only."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import d1_shadow_remote_probe as probe  # noqa: E402
from d1_remote_catalogue_pilot import PilotError  # noqa: E402

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
DBID = "12345678-1234-1234-1234-1234567890ab"


class SQLiteD1Double:
    created = 0
    contents = []
    existing = []

    def __init__(self, account, token):
        assert account == ACCOUNT
        assert token == "synthetic-test-token"
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys=on")

    def list_databases(self):
        return self.existing

    def create_synthetic_database(self, name):
        assert name.startswith("drop-rate-d1-synthetic-")
        type(self).created += 1
        return DBID

    def query(self, database_id, sql, params=()):
        assert database_id == DBID
        assert "drop table" not in sql.lower()
        assert "delete from" not in sql.lower()
        assert "market_value_minor" not in sql.lower()
        type(self).contents.append(sql[:90])
        cursor = self.conn.execute(sql, params)
        return ({"success":True, "results": [dict(row) for row in cursor.fetchall()]
                 if cursor.description else []}, 0.0)


def test_synthetic_d1_remote_sequence_publication_and_rollback(monkeypatch):
    SQLiteD1Double.created = 0
    SQLiteD1Double.contents = []
    SQLiteD1Double.existing = []
    monkeypatch.setattr(probe, "D1Client", SQLiteD1Double)
    result = probe.execute(ACCOUNT,"synthetic-test-token","654321","1")
    assert result["status"] == "SYNTHETIC_REMOTE_D1_SHADOW_VERIFIED"
    assert result["synthetic_catalogue_rows"] == 18
    assert result["source_manifests_tested"] == 2
    assert result["partial_publication_blocked"]
    assert result["rollback_verified"]
    assert result["production_writes"] == 0
    assert SQLiteD1Double.created == 1


def test_remote_pilot_refuses_unverified_run_identity(monkeypatch):
    monkeypatch.setattr(probe, "D1Client", SQLiteD1Double)
    with pytest.raises(PilotError, match="GitHub Actions"):
        probe.execute(ACCOUNT,"synthetic-test-token","","1")
    with pytest.raises(PilotError, match="GitHub Actions"):
        probe.execute(ACCOUNT,"synthetic-test-token","123","../1")


def test_existing_d1_capacity_blocks_creation(monkeypatch):
    SQLiteD1Double.created = 0
    SQLiteD1Double.existing = [{"name":f"other-database-{i}"} for i in range(8)]
    monkeypatch.setattr(probe, "D1Client", SQLiteD1Double)
    result = probe.execute(ACCOUNT,"synthetic-test-token","123","2")
    assert result["status"] == "INSPECT_OK_DATABASE_LIMIT_GUARD_BLOCKED_PILOT"
    assert SQLiteD1Double.created == 0
    SQLiteD1Double.existing = []
