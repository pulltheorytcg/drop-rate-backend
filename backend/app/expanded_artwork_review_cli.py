"""Offline only: 25 published R2 reference rows + approved-source payload -> review manifest.

Run with PYTHONPATH=backend python -m app.expanded_artwork_review_cli ...
Does not call APIs or store objects. Never emits approved/publishable artwork.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path

from .expanded_artwork_pilot import preview_yugioh, preview_lorcana
from .expanded_artwork_mtg import preview_mtgjson

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
    parser.add_argument("--game", required=True, choices=("yugioh", "lorcana", "magic"))
    parser.add_argument("--source", required=True, help="Existing original provider source JSON (local only)")
    parser.add_argument("--references", required=True, help="Exact published R2 reference rows JSON (max 25)")
    args = parser.parse_args(argv)
    source, source_sha = _json_file(args.source, SOURCE_MAX_BYTES)
    references, refs_sha = _json_file(args.references, REFERENCE_MAX_BYTES)
    publication_digest = None
    if isinstance(references, dict):
        expected = {
            "yugioh": ("ygoprodeck", "YUGIOH"),
            "lorcana": ("lorcast", "DISNEY_LORCANA"),
            "magic": ("mtgjson", "MAGIC_THE_GATHERING"),
        }[args.game]
        publication_digest = references.get("source_manifest_sha256")
        rows = references.get("references")
        if (references.get("schema") != "drop-rate-r2-artwork-sample-v1"
                or (references.get("provider"), references.get("system_code")) != expected
                or not isinstance(publication_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", publication_digest)
                or not isinstance(rows, list) or references.get("sample_count") != len(rows)):
            raise ValueError("The R2 artwork sample is invalid or belongs to another game")
        references = rows
    decisions = {"yugioh": preview_yugioh, "lorcana": preview_lorcana,
                 "magic": preview_mtgjson}[args.game](source, references)
    report = {
        "schema": "expanded-artwork-preview-v1",
        "game": args.game,
        "source_sha256": source_sha,
        "references_sha256": refs_sha,
        "source_manifest_sha256": publication_digest,
        "reference_count": len(decisions),
        "status_counts": dict(sorted(Counter(row["status"] for row in decisions).items())),
        "all_artwork_unapproved": all(not row["can_mirror"] and not row["can_publish"] for row in decisions),
        "records": decisions,
    }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
