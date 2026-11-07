"""Offline only: 25 published R2 reference rows + approved-source payload -> review manifest.

Run with PYTHONPATH=backend python -m app.expanded_artwork_review_cli ...
Does not call APIs or store objects. Never emits approved/publishable artwork.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .expanded_artwork_pilot import preview_yugioh, preview_lorcana

SOURCE_MAX_BYTES = 40_000_000
REFERENCE_MAX_BYTES = 200_000


def _json_file(path: str, max_bytes: int):
    file = Path(path)
    if not file.is_file() or not file.stat().st_size or file.stat().st_size > max_bytes:
        raise ValueError("Missing or oversized preview input")
    raw = file.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("Oversized preview input")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Review unapproved exact-ID artwork leads offline; no writes")
    parser.add_argument("--game", required=True, choices=("yugioh", "lorcana"))
    parser.add_argument("--source", required=True, help="Existing original provider source JSON (local only)")
    parser.add_argument("--references", required=True, help="Exact published R2 reference rows JSON (max 25)")
    args = parser.parse_args(argv)
    source, source_sha = _json_file(args.source, SOURCE_MAX_BYTES)
    references, refs_sha = _json_file(args.references, REFERENCE_MAX_BYTES)
    decisions = (preview_yugioh if args.game == "yugioh" else preview_lorcana)(source, references)
    report = {
        "schema": "expanded-artwork-preview-v1",
        "game": args.game,
        "source_sha256": source_sha,
        "references_sha256": refs_sha,
        "reference_count": len(decisions),
        "status_counts": dict(sorted(Counter(row["status"] for row in decisions).items())),
        "all_artwork_unapproved": all(not row["can_mirror"] and not row["can_publish"] for row in decisions),
        "records": decisions,
    }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
