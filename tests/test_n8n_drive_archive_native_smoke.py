"""Offline harness safeguards; the real pinned runtime is a separate Docker gate."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_native_drive_smoke_harness_guards():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", str(root / "tests/n8n_drive_archive_native_smoke.test.cjs")],
        cwd=root, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
