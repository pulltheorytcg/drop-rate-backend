"""Show source routes for an exact Drop Rate printing without network or writes.

Input: a JSON object representing the existing canonical reference identity.
Only for operator review; this never fetches eBay/Cardmarket or publishes art.

PYTHONPATH=backend python backend/scripts/market_intelligence_plan.py \
  --target /private/confirmed-printing.json --read-only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.market_intelligence_sources import ExactReference, plan_collection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    if not args.target.is_file() or args.target.stat().st_size > 20_000:
        parser.error("Exact reference input must be a local JSON file under 20 KB")
    try:
        payload = json.loads(args.target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected canonical reference object")
        allowed = set(ExactReference.__dataclass_fields__)
        if set(payload) - allowed:
            raise ValueError("Unknown/unsafe identity fields")
        plan = plan_collection(ExactReference(**payload))
    except (TypeError, ValueError, KeyError, UnicodeError):
        parser.error("Invalid exact reference identity")
    print(json.dumps(plan, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
