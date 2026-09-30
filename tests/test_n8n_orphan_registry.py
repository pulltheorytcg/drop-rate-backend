from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORPHAN = (
    ROOT
    / "automation"
    / "n8n"
    / "orphans"
    / "dr-92-workflow-heartbeat.json"
)
WORKFLOW_DIR = ROOT / "automation" / "n8n" / "workflows"
DOCKERFILE = ROOT / "Dockerfile.n8n"
START = ROOT / "automation" / "n8n" / "start.sh"


def test_duplicate_dr92_is_tracked_only_as_inactive_orphan() -> None:
    workflow = json.loads(ORPHAN.read_text())

    assert workflow["id"] == "DR92WorkflowHeartbeatV1"
    assert workflow["active"] is False
    assert not (WORKFLOW_DIR / ORPHAN.name).exists()


def test_orphan_directory_is_not_provisioned_into_n8n() -> None:
    dockerfile = DOCKERFILE.read_text()
    start = START.read_text()

    assert "COPY automation/n8n/workflows /opt/drop-rate/workflows" in dockerfile
    assert "COPY automation/n8n/orphans" not in dockerfile
    assert 'WORKFLOW_DIR="/opt/drop-rate/workflows"' in start
    assert "/opt/drop-rate/orphans" not in start
