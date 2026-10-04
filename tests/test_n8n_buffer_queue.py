from pathlib import Path
import subprocess


def test_buffer_queue_contract_in_node_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", "tests/n8n_buffer_queue.test.mjs"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
