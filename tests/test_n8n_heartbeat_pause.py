from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_guarded_n8n_heartbeat_pause() -> None:
    result = subprocess.run(
        ["node", "--no-warnings", "--test", "tests/n8n_heartbeat_pause.test.cjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=40, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
