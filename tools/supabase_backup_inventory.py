"""Read-only Supabase Management API backup inventory check.

Never downloads or restores backups, touches Postgres, or prints access tokens.
A Pro subscription's automatic entitlement is NOT proof of a completed backup.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SUPABASE_MANAGEMENT_ORIGIN = "https://api.supabase.com"
PROJECT_REF = "ozrxenrdladkooixutmm"
MAX_BACKUP_AGE = timedelta(hours=48)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Backup timestamp missing")
    date = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if date.utcoffset() is None:
        raise ValueError("Backup timestamp must be timezone aware")
    return date.astimezone(timezone.utc)


def completed_backups(payload: object) -> list[datetime]:
    """Only provider-reported COMPLETED backups are accepted as evidence."""
    if not isinstance(payload, dict) or not isinstance(payload.get("backups"), list):
        raise ValueError("Supabase backup inventory response missing backups array")
    results = []
    for row in payload["backups"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid backup entry in provider inventory")
        if row.get("status") != "COMPLETED":
            continue
        results.append(_timestamp(row.get("inserted_at")))
    return sorted(results, reverse=True)


def backup_receipt(payload: object, *, now: datetime | None = None) -> dict:
    dates = completed_backups(payload)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    recent = bool(dates and timedelta(0) <= now - dates[0] <= MAX_BACKUP_AGE)
    return {
        "project_ref": PROJECT_REF,
        "completed_backup_count": len(dates),
        "latest_completed_backup_at": dates[0].isoformat() if dates else None,
        "backup_within_48_hours": recent,
        "source": "supabase_management_api_backup_inventory",
        "restoration_tested": False,
        "r2_objects_backed_up": False,
    }


def get_backup_inventory(token: str) -> dict:
    """One GET to one pinned Supabase API URL; never follow redirects."""
    if not token or token.isspace():
        raise ValueError("Management API access token is not configured")
    assert re.fullmatch(r"[a-z]{20}", PROJECT_REF)
    req = Request(
        f"{SUPABASE_MANAGEMENT_ORIGIN}/v1/projects/{PROJECT_REF}/database/backups",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    opener = build_opener(_NoRedirect)
    with opener.open(req, timeout=15) as response:
        if response.status != 200:
            raise ValueError("Backup inventory request was not successful")
        raw = response.read(500_001)
    if len(raw) > 500_000:
        raise ValueError("Unexpectedly large backup inventory response")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid backup inventory payload")
    return parsed


def main() -> int:
    try:
        receipt = backup_receipt(get_backup_inventory(os.environ.get("SUPABASE_ACCESS_TOKEN", "")))
        print(json.dumps(receipt, sort_keys=True))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            # This contains only the approved project reference and timestamps.
            with open(summary, "a", encoding="utf-8") as out:
                out.write(
                    "### Supabase production backup inventory (read-only)\n"
                    f"- Completed backups: {receipt['completed_backup_count']}\n"
                    f"- Latest completed: {receipt['latest_completed_backup_at'] or 'not verified'}\n"
                    f"- Latest within 48 hours: {receipt['backup_within_48_hours']}\n"
                    "- Restore test: not performed\n"
                    "- R2 object backup: not included\n"
                )
        return 0 if receipt["backup_within_48_hours"] else 2
    except HTTPError as error:
        # Never print upstream response bodies, URLs with tokens or headers.
        print(f"Backup inventory verification failed (HTTP {error.code}); no backup verified", file=sys.stderr)
    except (URLError, ValueError, json.JSONDecodeError, OSError) as error:
        print(f"Backup inventory verification failed ({type(error).__name__}); no backup verified", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
