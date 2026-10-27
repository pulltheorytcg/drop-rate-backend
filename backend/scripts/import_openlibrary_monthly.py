"""Fetch, resume, select and export one complete monthly edition metadata dump.

This offline operator writes local source/cache/checkpoints only. Production
application remains the separate capacity-guarded reviewed book importer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.book_openlibrary_bulk import (BulkPaused, download_dump, export_selection,
    fetch_manifest, open_selection, scan_dump, selection_report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("manifest", "download", "select", "report", "export"))
    parser.add_argument("--source")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dump")
    parser.add_argument("--state")
    parser.add_argument("--output")
    parser.add_argument("--exclude-isbns", help="JSON list of already imported ISBN13 values")
    parser.add_argument("--max-export-records", type=int)
    parser.add_argument("--max-download-bytes", type=int, default=1024**3)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--max-scan-records", type=int, default=10_000_000)
    args = parser.parse_args()
    try:
        if args.action == "manifest":
            if not args.source:
                parser.error("manifest requires --source")
            import httpx
            with httpx.Client(timeout=60) as client:
                report = fetch_manifest(args.source, client)
            Path(args.manifest).write_text(json.dumps(report, indent=2) + "\n")
        else:
            spec = json.loads(Path(args.manifest).read_text())
            if args.action == "download":
                if not args.dump:
                    parser.error("download requires --dump")
                import httpx
                with httpx.Client(timeout=60) as client:
                    report = download_dump(args.dump, spec, client,
                        max_bytes=args.max_download_bytes, max_seconds=args.max_seconds)
            else:
                if not args.state:
                    parser.error("selection actions require --state")
                with open_selection(args.state) as state:
                    if args.action == "select":
                        if not args.dump:
                            parser.error("select requires --dump")
                        report = scan_dump(args.dump, spec, state,
                            max_seconds=args.max_seconds, max_records=args.max_scan_records,
                            progress_callback=lambda value: print(json.dumps(value, sort_keys=True), flush=True))
                    elif args.action == "report":
                        report = selection_report(state)
                    else:
                        if not args.output:
                            parser.error("export requires --output")
                        excluded = json.loads(Path(args.exclude_isbns).read_text()) if args.exclude_isbns else []
                        report = export_selection(state, args.output, exclude_isbns=excluded,
                                                  max_records=args.max_export_records)
    except BulkPaused as exc:
        print(json.dumps({"status": "PAUSED", "reason": str(exc)}))
        raise SystemExit(2)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
