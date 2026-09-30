from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run_script(filename: str) -> int:
    completed = subprocess.run(
        [sys.executable, str(ROOT / filename)],
        check=False,
    )
    return int(completed.returncode)


def main() -> None:
    heartbeat_code = _run_script("check_payout_scheduler_heartbeat.py")
    reconciliation_code = _run_script("reconcile_shopify_orders.py")
    automation_code = _run_script("check_automation_outbox_health.py")
    dispatcher_code = _run_script("check_automation_dispatcher_heartbeat.py")

    if (
        heartbeat_code == 0
        and reconciliation_code == 0
        and automation_code == 0
        and dispatcher_code == 0
    ):
        print(
            json.dumps(
                {
                    "event": "DROP_RATE_OPERATIONS_MONITOR_COMPLETE",
                    "heartbeat_code": 0,
                    "reconciliation_code": 0,
                    "automation_code": 0,
                    "dispatcher_code": 0,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(0)

    print(
        json.dumps(
            {
                "event": "DROP_RATE_OPERATIONS_MONITOR_FAILED",
                "heartbeat_code": heartbeat_code,
                "reconciliation_code": reconciliation_code,
                "automation_code": automation_code,
                "dispatcher_code": dispatcher_code,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
