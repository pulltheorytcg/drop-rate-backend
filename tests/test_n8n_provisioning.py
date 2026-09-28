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


def test_n8n_startup_fails_closed_without_dr00_runtime_capabilities() -> None:
    script = (ROOT / "automation" / "n8n" / "start.sh").read_text()
    assert "N8N_BLOCK_ENV_ACCESS_IN_NODE" in script
    assert '!= "false"' in script
    assert "NODE_FUNCTION_ALLOW_BUILTIN" in script
    assert "*,crypto,*" in script
    assert '",*,"' in script
    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in script
    assert '"${#webhook_secret}" -lt 32' in script


def test_dr00_runtime_security_tradeoff_is_documented() -> None:
    readme = (ROOT / "automation" / "n8n" / "README.md").read_text()
    assert "N8N_BLOCK_ENV_ACCESS_IN_NODE=false" in readme
    assert "NODE_FUNCTION_ALLOW_BUILTIN=crypto" in readme
    assert "security boundary" in readme
    assert "trusted, version-controlled Code workflows" in readme
