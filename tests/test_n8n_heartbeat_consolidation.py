from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "automation" / "n8n" / "workflows"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"


def test_dr92_runtime_heartbeat_is_the_only_dr92_heartbeat() -> None:
    dr92_files = sorted(WORKFLOWS.glob("dr-92-*.json"))
    assert [path.name for path in dr92_files] == ["dr-92-runtime-heartbeat.json"]

    workflow = json.loads(dr92_files[0].read_text())
    assert workflow["id"] == "DR92RuntimeHeartbeatV1"
    assert workflow["meta"]["dropRate"]["contract"] == "DR-92"


def test_operations_monitor_has_one_n8n_heartbeat_check_and_one_result_key() -> None:
    source = MONITOR.read_text()

    assert source.count('n8n_heartbeat_code = _run_script(') == 1
    assert 'check_n8n_runtime_heartbeat.py' in source
    assert 'check_n8n_workflow_heartbeat.py' not in source
    assert source.count('"n8n_heartbeat_code":') == 2
