"""Regression checks for the governed out-of-order migration release."""

from pathlib import Path
from runpy import run_path

import pytest


ROOT = Path(__file__).parents[1]
stage = run_path(str(ROOT / "scripts/stage_supabase_migrations.py"))["stage"]
history_gate = run_path(str(ROOT / "scripts/verify_supabase_history_gate.py"))
verify_history = history_gate["verify_history"]
HistoryGateError = history_gate["HistoryGateError"]


HISTORICAL_PENDING = {
    "20260925233000", "20260926001000", "20260926002000",
    "20260930051500", "20261013105000",
}


def _history_fixture(staged: Path, pending: set[str]) -> str:
    lines = ["Local | Remote | Time (UTC)", "------|--------|---------"]
    for path in sorted(staged.glob("*.sql")):
        version = path.name[:14]
        remote = " " if version in pending else version
        lines.append(f"`{version}` | `{remote}` | `2026-11-02 00:00:00`")
    return "\n".join(lines)


def test_production_history_gate_allows_only_audited_out_of_order_migrations(tmp_path):
    stage(tmp_path)
    pending = HISTORICAL_PENDING | {"20261101205040"}
    result = verify_history(_history_fixture(tmp_path, pending), tmp_path)
    assert result["pending_count"] == 6
    assert set(result["approved_historical_pending"]) == HISTORICAL_PENDING
    assert result["new_pending"] == ["20261101205040"]


def test_production_history_gate_rejects_an_unreviewed_old_sql(tmp_path):
    stage(tmp_path)
    pending = HISTORICAL_PENDING | {"20261008183306", "20261101205040"}
    with pytest.raises(HistoryGateError, match="Unreviewed historical migrations"):
        verify_history(_history_fixture(tmp_path, pending), tmp_path)


def test_production_history_gate_rejects_modified_reviewed_sql(tmp_path):
    stage(tmp_path)
    old_sql = tmp_path / "20260930051500_automation_dispatcher_heartbeat.sql"
    old_sql.write_text(old_sql.read_text() + "\n-- unreviewed modification\n")
    with pytest.raises(HistoryGateError, match="Reviewed historical migration changed"):
        verify_history(_history_fixture(tmp_path, HISTORICAL_PENDING), tmp_path)


def test_production_history_gate_rejects_executable_baseline(tmp_path):
    stage(tmp_path)
    baseline = tmp_path / "20260925233000_store_price_floor.sql"
    baseline.write_text(baseline.read_text() + "\nselect 1;\n")
    with pytest.raises(HistoryGateError, match="Baseline is not comment-only"):
        verify_history(_history_fixture(tmp_path, HISTORICAL_PENDING), tmp_path)


def test_production_history_gate_rejects_remote_only_migrations(tmp_path):
    stage(tmp_path)
    fixture = _history_fixture(tmp_path, HISTORICAL_PENDING)
    fixture += "\n` ` | `20261102235959` | `2026-11-02 23:59:59`\n"
    with pytest.raises(HistoryGateError, match="Remote migrations missing locally"):
        verify_history(fixture, tmp_path)
