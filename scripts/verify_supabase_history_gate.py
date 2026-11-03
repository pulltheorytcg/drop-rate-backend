#!/usr/bin/env python3
"""Fail closed before allowing Supabase's out-of-order `db push --include-all`.

The production project predates the canonical migration filenames. Three
schema-verified legacy files are staged as no-op baselines; two genuine old SQL
files were reviewed for this release. This gate forbids any other historical
migration from being replayed by the permissive `--include-all` flag.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


VERSION = re.compile(r"(?<!\d)\d{14}(?!\d)")

# The first three are deliberately comment-only, not executable DDL.
VERIFIED_BASELINES = {
    "20260925233000": "store_price_floor",
    "20260926001000": "identity_import_exact_method",
    "20260926002000": "media_live_side_uniqueness",
}

# Reviewed against production on 2026-11-02. Changing either canonical SQL
# file requires a new review and an explicit digest update here.
REVIEWED_HISTORICAL_SQL = {
    "20260930051500": (
        "automation_dispatcher_heartbeat",
        "52092e3fa659ddd18354cc7b288b326e025abb4ae8a5f62c13c948428e852845",
    ),
    "20261013105000": (
        "reference_japanese_source_guard",
        "40ae244b777a4ec4a80e4cda94fc849d368dc28be7c12d7eb9e928fb1f91c8f3",
    ),
}


class HistoryGateError(ValueError):
    """Unsafe, unexpected, or unreadable migration history."""


def read_history(output: str) -> tuple[set[str], set[str]]:
    """Parse `supabase migration list`'s three-column human-readable table."""
    local: set[str] = set()
    remote: set[str] = set()

    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        lhs = VERSION.search(parts[0])
        rhs = VERSION.search(parts[1])
        if lhs is None and rhs is None:
            continue
        left = lhs.group(0) if lhs else None
        right = rhs.group(0) if rhs else None
        if left is not None and right is not None and left != right:
            raise HistoryGateError(f"Mismatched local/remote migration row: {left} != {right}")
        if left in local or right in remote:
            raise HistoryGateError("Duplicate migration history row")
        if left is not None:
            local.add(left)
        if right is not None:
            remote.add(right)

    if not local or not remote:
        raise HistoryGateError("Unable to read both local and remote migration versions")
    return local, remote


def verify_staged_files(staged: Path) -> None:
    """Check no-op baselines and pin the exact two old SQL files reviewed."""
    for version, name in VERIFIED_BASELINES.items():
        path = staged / f"{version}_{name}.sql"
        if not path.is_file():
            raise HistoryGateError(f"Verified baseline missing: {path.name}")
        body = path.read_text(encoding="utf-8")
        if "Intentionally no SQL" not in body or any(
            line.strip() and not line.lstrip().startswith("--")
            for line in body.splitlines()
        ):
            raise HistoryGateError(f"Baseline is not comment-only: {path.name}")

    for version, (name, expected_digest) in REVIEWED_HISTORICAL_SQL.items():
        path = staged / f"{version}_{name}.sql"
        if not path.is_file():
            raise HistoryGateError(f"Reviewed historical migration missing: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_digest:
            raise HistoryGateError(f"Reviewed historical migration changed: {path.name}")


def verify_history(history: str, staged: Path) -> dict[str, object]:
    local, remote = read_history(history)
    actual_files = {path.name[:14] for path in staged.glob("*.sql")}
    if local != actual_files:
        raise HistoryGateError("Migration list does not match staged SQL files")
    remote_only = remote - local
    if remote_only:
        raise HistoryGateError("Remote migrations missing locally: " + ", ".join(sorted(remote_only)))

    verify_staged_files(staged)
    pending = local - remote
    last_applied = max(remote)
    out_of_order = {version for version in pending if version < last_applied}
    allowlist = set(VERIFIED_BASELINES) | set(REVIEWED_HISTORICAL_SQL)
    unexpected = out_of_order - allowlist
    if unexpected:
        raise HistoryGateError("Unreviewed historical migrations: " + ", ".join(sorted(unexpected)))

    return {
        "remote_count": len(remote),
        "pending_count": len(pending),
        "approved_historical_pending": sorted(out_of_order),
        "new_pending": sorted(pending - out_of_order),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_supabase_history_gate.py <history-log> <staged-dir>", file=sys.stderr)
        return 2
    try:
        result = verify_history(Path(sys.argv[1]).read_text(), Path(sys.argv[2]))
    except (HistoryGateError, OSError) as exc:
        print(f"Supabase history gate blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
