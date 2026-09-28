from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_n8n_image_is_pinned_and_runs_unprivileged() -> None:
    dockerfile = (ROOT / "Dockerfile.n8n").read_text()
    assert "FROM ghcr.io/n8n-io/n8n:2.32.6" in dockerfile
    assert dockerfile.rstrip().endswith('ENTRYPOINT ["/opt/drop-rate/start.sh"]')
    assert "USER node" in dockerfile


def test_n8n_startup_provisioner_is_additive() -> None:
    script = (ROOT / "automation" / "n8n" / "start.sh").read_text()
    assert "set -eu" in script
    assert "n8n list:workflow --onlyId" in script
    assert "grep -Fxq" in script
    assert "n8n import:workflow" in script
    assert "exec n8n start" in script

    forbidden = (
        "rm -f",
        "database.sqlite",
        "delete:workflow",
        "reset",
        "import:credentials",
    )
    for token in forbidden:
        assert token not in script


def test_n8n_provisioning_never_commits_secret_values() -> None:
    paths = [
        ROOT / "Dockerfile.n8n",
        ROOT / "automation" / "n8n" / "start.sh",
        ROOT / "automation" / "n8n" / "README.md",
    ]
    secret_assignment = re.compile(
        r"(?i)(?:secret|token|password|encryption[_-]?key)\s*=\s*['\"][^$][^'\"]+['\"]"
    )
    for path in paths:
        assert not secret_assignment.search(path.read_text()), path
