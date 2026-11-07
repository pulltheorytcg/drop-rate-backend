"""Replay a bounded local, normalized evidence export; never contacts providers."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.pricing_accuracy import EvidenceRecord, evaluate_accuracy
from app.pricing_engine import MarketObservation

MAX_ROWS = 10000
MAX_BYTES = 20 * 1024 * 1024


def read_records(path: Path) -> list[EvidenceRecord]:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Evidence export exceeds 20 MiB")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("Expected an array of at most 10000 normalized observations")
    records = []
    fields = ("source", "observation_type", "price_gbp_minor", "sample_size",
              "condition", "grading_company", "grade",
              "language", "seal_status", "source_country")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each observation must be an object")
        records.append(EvidenceRecord(
            catalogue_id=row["catalogue_id"], category=row["category"],
            available_at=datetime.fromisoformat(row["ingested_at"]),
            shipping_gbp_minor=row.get("shipping_gbp_minor"),
            observation=MarketObservation(
                **{field: row[field] for field in fields},
                # PostgreSQL numeric exports are JSON strings; normalize the
                # quality field without rounding integer prices or counts.
                evidence_quality=float(row["evidence_quality"]),
                observed_at=datetime.fromisoformat(row["observed_at"]),
                source_record_key=row.get("external_id") or row["source_record_key"],
            ),
        ))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--category", action="append", default=[],
                        help="Include a category even when it has no evidence (repeatable)")
    parser.add_argument("--price-basis", choices=("item", "delivered"), default="item")
    args = parser.parse_args()
    result = evaluate_accuracy(read_records(args.input), expected_categories=args.category,
                               price_basis=args.price_basis)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

