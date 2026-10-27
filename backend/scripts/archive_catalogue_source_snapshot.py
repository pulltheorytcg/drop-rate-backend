"""Verify the fixed recovered Open Library checkpoint; optionally archive it privately.

Default is offline dry run. Run from the repository root with PYTHONPATH=backend.
This command does not import records or authorize deferred editions or artwork.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.catalogue_source_archives import archive_reviewed_openlibrary_sources
from app.object_storage import ObjectStorageError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload fixed evidence privately and verify remote bytes")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(archive_reviewed_openlibrary_sources(apply=args.apply))
    except ObjectStorageError as exc:
        # Earlier content-addressed objects may exist after an interrupted run;
        # no completed manifest receipt is claimed and a retry verifies/reuses them.
        print(json.dumps({"status": "FAILED", "archive_completed": False, "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
