"""Offline canary guards; actual n8n routing belongs to the pinned-image smoke."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_n8n_isolated_error_canary_guards() -> None:
    result = subprocess.run(
        ["node", "--no-warnings", "--test", "tests/n8n_error_canary.test.cjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
