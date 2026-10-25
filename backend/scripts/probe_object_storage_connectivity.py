"""Read-only, fail-closed R2/S3 connectivity check for controlled operations.

Run with PYTHONPATH=backend python -u backend/scripts/probe_object_storage_connectivity.py.
Never prints endpoints, bucket names, credential values, or provider exceptions.
"""
from __future__ import annotations

import sys

from app.object_storage import ObjectStorageConfig, S3ObjectStorage


def main() -> int:
    print("DROP_RATE_R2_PROBE_START", flush=True)
    try:
        config = ObjectStorageConfig.from_env()
        if config is None:
            print("DROP_RATE_R2_PROBE_FAILED:DISABLED", file=sys.stderr, flush=True)
            return 2
        S3ObjectStorage(config).connectivity()
    except Exception as exc:
        print(f"DROP_RATE_R2_PROBE_FAILED:{type(exc).__name__}", file=sys.stderr, flush=True)
        return 1
    print("DROP_RATE_R2_PROBE_PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
