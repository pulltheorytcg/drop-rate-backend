"""Offline execution of the exact disabled DR95 Code nodes and contract guards."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_n8n_drive_archive_workflow_contract() -> None:
    result = subprocess.run(
        ["node", "--no-warnings", "--test", "tests/n8n_drive_archive_workflow.test.cjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
