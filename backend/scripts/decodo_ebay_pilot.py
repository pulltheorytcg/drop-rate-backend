"""Run a bounded acquisition pilot; no database or pricing writes."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.decodo_ebay import DecodoEbaySoldClient, DecodoError


def queries(manifest):
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 36:
        raise ValueError("Expected 1..36 audited reference candidates")
    output, seen = [], set()
    for ref in candidates:
        fields = ("provider", "system_code", "language", "provider_id")
        identity = tuple(ref.get(k) for k in fields)
        if any(not isinstance(x, str) or not x for x in identity) or identity in seen:
            raise ValueError("Invalid or duplicate reference identity")
        seen.add(identity)
        name, number = ref.get("name"), ref.get("card_number")
        if not isinstance(name, str) or not name or not isinstance(number, str) or not number:
            raise ValueError("Reference name and number are required")
        number = re.sub(r"_p\d+$", "", number, flags=re.I)
        language = ref["language"] if ref["language"] != "Unknown" else ""
        query = " ".join(x for x in (name, number, language) if x)
        if len(query) > 500:
            raise ValueError("Reference search exceeds query limit")
        output.append({"reference": dict(zip(fields, identity)), "query": query,
                       "identity_review_required": True,
                       "review_reason": "Search text is not a verified source mapping"})
    return output


async def run(manifest, *, client, max_pages, checkpoint):
    report = {"status": "RUNNING", "database_writes": 0, "newly_priced_references": 0,
              "snapshot_at": manifest.get("snapshot_at"), "items": [], "requests_sent": 0}
    checkpoint(report)
    # Sequential pilot: 10/s is a ceiling, not a target or a throughput promise.
    for item in queries(manifest):
        try:
            payload = await client.sold(query=item["query"], max_pages=max_pages)
        except DecodoError as exc:
            report.update(status="STOPPED", error={"code": exc.code, "status": exc.status,
                          "retry_after": exc.retry_after}, requests_sent=client.requests_sent)
            checkpoint(report)
            return report
        report["items"].append({**item, "evidence": payload})
        report["requests_sent"] = client.requests_sent
        checkpoint(report)
    report["status"] = "COLLECTED_REVIEW_REQUIRED"
    checkpoint(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rps", type=float, default=1)
    parser.add_argument("--max-requests", type=int, default=72)
    parser.add_argument("--pages", type=int, choices=[1, 2], default=1)
    parser.add_argument("--javascript", action="store_true")
    parser.add_argument("--run", action="store_true", help="Actually request the pages; default only prepares searches")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    search_plan = queries(manifest)
    if args.output.exists():
        parser.error("Use a new output filename; prior evidence is not overwritten")
    if not 0 < args.rps <= 10 or not 1 <= args.max_requests <= 200:
        parser.error("Use 0 < rps <= 10 and 1 <= max-requests <= 200")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save(report):
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)

    if not args.run:
        save({"status": "PLAN_ONLY", "requests_sent": 0, "database_writes": 0,
              "newly_priced_references": 0, "max_requests": args.max_requests,
              "requests_per_second_ceiling": args.rps, "items": search_plan})
        print("Prepared", len(search_plan), "searches; no network requests.")
        return
    api_key = os.environ.get("TCG_DECODO_API_KEY", "")
    if not api_key:
        parser.error("TCG_DECODO_API_KEY is not configured in this process")
    client = DecodoEbaySoldClient(api_key=api_key, requests_per_second=args.rps,
                                 max_requests=args.max_requests, javascript=args.javascript)
    report = asyncio.run(run(manifest, client=client, max_pages=args.pages, checkpoint=save))
    print(report["status"], "requests:", report["requests_sent"], "priced:", 0)
    if report["status"] == "STOPPED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

