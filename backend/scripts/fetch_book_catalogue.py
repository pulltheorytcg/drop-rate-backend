"""Resumable, opt-in downloads from authorised GCD / PRH accounts.

No credentials are saved. 401/403/429, redirects and provider schema drift stop
the job with its last committed cursor. Export a completed snapshot as JSONL,
then use import_book_catalogue.py to stage/review it before any database writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from app.book_bulk_import import ImportPaused
from app.book_catalogue_sources import canonical_json, digest

PRH_URL = "https://api.penguinrandomhouse.com/resources/v2/title/domains/PRH.US/titles"
GCD_BASE = "https://www.comics.org/api/"


def open_download(path):
    state = sqlite3.connect(path)
    state.executescript("""create table if not exists download_metadata(key text primary key,value text not null);
        create table if not exists download_records(position integer primary key,entry text not null);""")
    return state


def get(state, key, default=None):
    row = state.execute("select value from download_metadata where key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(state, key, value):
    state.execute("insert or replace into download_metadata values(?,?)", (key, canonical_json(value)))


def bind(state, config):
    if get(state, "config") not in (None, config):
        raise ImportPaused("DOWNLOAD_CONFIG_CHANGED_USE_NEW_STATE")
    with state:
        put(state, "config", config)
        if get(state, "started_on") is None:
            put(state, "started_on", date.today().isoformat())


async def provider_json(client, url, *, params=None, auth=None):
    # Even authenticated response links are untrusted input: only fixed provider
    # endpoints are followed; credentials cannot cross an origin or redirect.
    if url != PRH_URL and not re.fullmatch(r"https://www\.comics\.org/api/(?:series|publisher|issue)/[1-9][0-9]*/", url):
        raise ImportPaused("UNTRUSTED_PROVIDER_URL")
    try:
        async with client.stream("GET", url, params=params, auth=auth, follow_redirects=False, timeout=20) as response:
            if response.status_code != 200:
                status = response.status_code
                retry = response.headers.get("retry-after", "")
                suffix = f"_RETRY_AFTER_{retry}" if status == 429 and re.fullmatch(r"[0-9]{1,7}", retry) else ""
                raise ImportPaused(f"PROVIDER_HTTP_{status}" + suffix)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 5_000_000:
                    raise ImportPaused("PROVIDER_RESPONSE_TOO_LARGE")
            if params and params.get("api_key") and str(params["api_key"]).encode() in body:
                raise ImportPaused("PROVIDER_RESPONSE_CONTAINS_CREDENTIALS")
            try:
                result = json.loads(body)
            except ValueError:
                raise ImportPaused("PROVIDER_SCHEMA_CHANGED") from None
            if not isinstance(result, dict):
                raise ImportPaused("PROVIDER_SCHEMA_CHANGED")
            return result
    except httpx.HTTPError:
        raise ImportPaused("PROVIDER_TRANSPORT_ERROR") from None


async def fetch_prh(state, client, *, api_key, category_id, max_pages=5, interval=1.1):
    if not api_key:
        raise ImportPaused("PRH_API_KEY_REQUIRED")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", category_id) or not 1 <= max_pages <= 100:
        raise ValueError("A provider category ID and 1–100 pages are required")
    bind(state, {"provider": "PRH", "category_id": category_id, "rows": 100, "adapter": 1})
    for _ in range(max_pages):
        if get(state, "complete", False):
            break
        start = get(state, "cursor", 0)
        cutoff = date.fromisoformat(get(state, "started_on")).strftime("%m/%d/%Y")
        page = await provider_json(client, PRH_URL, params={"api_key": api_key, "catId": category_id,
            "start": start, "rows": 100, "sort": "id", "dir": "asc", "returnEmptyLists": "true",
            "onSaleTo": cutoff, "showBoxBundles": "false"})
        rows = page.get("data", {}).get("titles") if isinstance(page.get("data"), dict) else None
        if page.get("status") != "ok" or not isinstance(rows, list) or len(rows) > 100:
            raise ImportPaused("PROVIDER_SCHEMA_CHANGED")
        if any(not isinstance(row, dict) or "isbn" not in row for row in rows):
            raise ImportPaused("PROVIDER_SCHEMA_CHANGED")
        # A repeated nonempty page means the server is ignoring our cursor.
        page_hash = digest(rows)
        if rows and page_hash == get(state, "last_page_hash"):
            raise ImportPaused("PROVIDER_CURSOR_DID_NOT_ADVANCE")
        with state:
            state.executemany("insert into download_records values(?,?)", [(start + n,
                canonical_json({"title": row, "observed_on": date.today().isoformat()})) for n, row in enumerate(rows)])
            put(state, "cursor", start + len(rows))
            put(state, "last_page_hash", page_hash)
            # Only an empty page proves completion; providers may cap page sizes.
            put(state, "complete", not rows)
        if rows and interval:
            await asyncio.sleep(interval)
    return download_report(state)


async def fetch_gcd(state, client, *, username, password, rules, max_requests=50, interval=1.1):
    if not username or not password:
        raise ImportPaused("GCD_CREDENTIALS_REQUIRED")
    if not 1 <= max_requests <= 1000 or not isinstance(rules, list) or not rules:
        raise ValueError("Reviewed series rules and 1–1000 requests required")
    for rule in rules:
        if (not re.fullmatch(r"[1-9][0-9]*", str(rule.get("series_id", "")))
                or rule.get("system_code") not in {"MARVEL_COMICS", "DC_COMICS", "OTHER_COMICS", "MANGA"}
                or rule.get("book_format") not in {"SINGLE_ISSUE", "TRADE_PAPERBACK", "HARDCOVER", "MANGA"}):
            raise ValueError("Invalid reviewed GCD series classification")
    if len({str(r["series_id"]) for r in rules}) != len(rules):
        raise ValueError("Duplicate series rules")
    bind(state, {"provider": "GCD", "rules_digest": digest(rules), "adapter": 1})
    auth, used = httpx.BasicAuth(username, password), 0
    while used < max_requests and not get(state, "complete", False):
        series_index, issue_index = get(state, "cursor", [0, 0])
        if series_index >= len(rules):
            with state:
                put(state, "complete", True)
            break
        rule = rules[series_index]
        bundle = get(state, "series_bundle")
        if bundle is None:
            if used + 2 > max_requests:
                break
            series = await provider_json(client, f"{GCD_BASE}series/{rule['series_id']}/", auth=auth)
            if interval:
                await asyncio.sleep(interval)
            if not isinstance(series.get("active_issues"), list) or not series.get("publisher"):
                raise ImportPaused("PROVIDER_SCHEMA_CHANGED")
            publisher = await provider_json(client, series["publisher"], auth=auth)
            bundle = {"series": series, "publisher": publisher}
            with state:
                put(state, "series_bundle", bundle)
            used += 2
            if interval:
                await asyncio.sleep(interval)
        issues = bundle["series"]["active_issues"]
        if issue_index >= len(issues):
            with state:
                put(state, "cursor", [series_index + 1, 0])
                put(state, "series_bundle", None)
            continue
        if used >= max_requests:
            break
        issue = await provider_json(client, issues[issue_index], auth=auth)
        if issue.get("api_url") != issues[issue_index]:
            raise ImportPaused("PROVIDER_SCHEMA_CHANGED")
        with state:
            state.execute("insert into download_records(entry) values(?)", (canonical_json({**bundle,
                "issue": issue, "classification": rule, "observed_on": date.today().isoformat()}),))
            put(state, "cursor", [series_index, issue_index + 1])
        used += 1
        if interval:
            await asyncio.sleep(interval)
    return download_report(state)


def download_report(state):
    return {"config": get(state, "config"), "records": state.execute("select count(*) from download_records").fetchone()[0],
            "cursor": get(state, "cursor"), "complete": get(state, "complete", False)}


def export_download(state, output):
    if not get(state, "complete", False):
        raise ImportPaused("DOWNLOAD_NOT_COMPLETE")
    # Exclusive creation protects previous snapshots and arbitrary user files.
    with Path(output).open("x", encoding="utf-8") as stream:
        for row in state.execute("select entry from download_records order by position"):
            stream.write(row[0] + "\n")
    return download_report(state)


async def run(args):
    state = open_download(args.state)
    try:
        if args.command == "export":
            return export_download(state, args.output)
        if args.command == "report":
            return download_report(state)
        async with httpx.AsyncClient(headers={"Accept": "application/json", "User-Agent": "DropRateCatalogue/1"}) as client:
            if args.command == "prh":
                return await fetch_prh(state, client, api_key=os.environ.get("PRH_API_KEY"), category_id=args.category_id, max_pages=args.max_pages)
            rules = json.loads(Path(args.rules).read_text())
            return await fetch_gcd(state, client, username=os.environ.get("GCD_USERNAME"), password=os.environ.get("GCD_PASSWORD"), rules=rules, max_requests=args.max_requests)
    finally:
        state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("report")
    prh = commands.add_parser("prh")
    prh.add_argument("--category-id", required=True, help="Actual PRH comics/manga category ID from its category API")
    prh.add_argument("--max-pages", type=int, default=5)
    gcd = commands.add_parser("gcd")
    gcd.add_argument("--rules", required=True, help="Reviewed JSON array of series_id/system_code/book_format")
    gcd.add_argument("--max-requests", type=int, default=50)
    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2))
    except (ImportPaused, OSError, ValueError):
        import sys
        exc = sys.exc_info()[1]
        print(json.dumps({"status": "PAUSED", "reason": str(exc) if isinstance(exc, ImportPaused) else "DOWNLOAD_INPUT_ERROR"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
