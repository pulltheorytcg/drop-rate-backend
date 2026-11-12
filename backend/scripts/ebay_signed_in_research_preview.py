"""Offline assisted eBay UK research preview. Never accesses the browser or DB.

Run from the repository root:
 PYTHONPATH=backend python backend/scripts/ebay_signed_in_research_preview.py \
   --manifest /private/reviewed-sales.json --read-only

Input JSON: {"target": {canonical identity ...}, "sales": [reviewed rows ...]}.
Do not put credentials, cookies, raw HTML, seller data or private buyer details
in the manifest. Keep private manifests outside Git and upload them nowhere.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ebay_signed_in_research import preview_product_research


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    if not args.manifest.is_file() or args.manifest.stat().st_size > 200_000:
        parser.error("Manifest must be a local JSON file under 200 KB")
    try:
        document = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("JSON object required")
        result = preview_product_research(document["target"], document["sales"])
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        # Deliberately do not echo raw row contents or external URLs on error.
        parser.error(f"Invalid reviewed input: {type(error).__name__}")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
