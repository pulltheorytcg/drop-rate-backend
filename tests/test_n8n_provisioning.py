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
        "delete:workflow",
        "reset",
        "import:credentials",
        "truncate",
        "drop table",
    )
    for token in forbidden:
        assert token not in script

    assert 'rm "$N8N_DB"' not in script
    assert 'mv "$N8N_DB"' not in script
    assert 'cp "$N8N_DB" "$N8N_PREPROVISION_BACKUP"' in script


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


def test_n8n_startup_requires_control_plane_runtime_capabilities() -> None:
    script = (ROOT / "automation" / "n8n" / "start.sh").read_text()

    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in script
    assert '"${#command_secret}" -lt 32' in script
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in script
    assert "/api/v1/automation/control/receipt" in script
    assert "railway.internal" in script


def test_n8n_cutover_creates_one_time_database_backup_before_import() -> None:
    script = (ROOT / "automation" / "n8n" / "start.sh").read_text()

    backup = "database.sqlite.pre-drop-rate-provision-v1.bak"
    assert backup in script
    assert 'cp "$N8N_DB" "$N8N_PREPROVISION_BACKUP"' in script
    assert 'chmod 0600 "$N8N_PREPROVISION_BACKUP"' in script
    assert '[ ! -s "$N8N_PREPROVISION_BACKUP" ]' in script

    backup_index = script.index('cp "$N8N_DB" "$N8N_PREPROVISION_BACKUP"')
    import_index = script.index('n8n import:workflow')
    assert backup_index < import_index


def test_n8n_provisioner_imports_only_explicitly_inactive_workflows() -> None:
    script = (ROOT / "automation" / "n8n" / "start.sh").read_text()

    assert "if(w.active!==false)process.exit(3)" in script
    assert "importing inactive workflow" in script
    assert "installed_ids=" in script
    assert "workflow verification failed" in script
