"""Export reviewed offline book staging as guarded, reviewable SQL batches."""
import argparse
import json
from pathlib import Path

from app.book_bulk_import import open_stage
from app.book_connector_import import export_stage_batches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--selection-report", required=True,
                        help="Complete verified full-dump export receipt, never a prefix-pilot receipt")
    parser.add_argument("--database-bytes", type=int, required=True,
                        help="Current read-only capacity preflight; SQL rechecks it in every transaction")
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-records", type=int, default=1500)
    args = parser.parse_args()
    with open_stage(args.state) as state:
        report = export_stage_batches(state, args.output, expected_snapshot_sha256=args.snapshot_sha256,
                                      selection_receipt=json.loads(Path(args.selection_report).read_text()),
                                      database_bytes=args.database_bytes,
                                      batch_size=args.batch_size, max_records=args.max_records)
    Path(args.output, "manifest.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
