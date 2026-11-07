"""Provision an EMPTY, isolated Cloudflare D1 artwork shadow with exact schema parity.

Does not deploy a Worker, publish an image, touch PostgreSQL, or change the
operational D1/Shopify/price/owner pointers. No on-failure database deletions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
DB_NAME = "drop-rate-d1-artwork-shadow-20261106"
SQL_FILE = Path("database/cloudflare_d1/0003_artwork_shadow.sql")
REPORT_FILE = Path("d1-artwork-shadow-report.json")
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")
ALLOWED = {("table", "artwork_shadow_candidates"), ("index", "artwork_shadow_by_scope")}
MAX_EXISTING = 7  # preserve 2 Free D1 slots for operational and rollback work


class ArtworkShadowProvisionError(ValueError):
    pass


def parse_schema(source: str) -> list[str]:
    if not isinstance(source, str) or not 200 <= len(source) <= 16_000:
        raise ArtworkShadowProvisionError("Unexpected D1 artwork schema size")
    lines = [line for line in source.splitlines(keepends=True)
             if not line.lstrip().startswith("--")]
    buffer = ""
    statements = []
    for line in lines:
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip() or len(statements) != 2:
        raise ArtworkShadowProvisionError("Unexpected or incomplete D1 statements")
    names = set()
    for statement in statements:
        found = re.match(
            r"\ACREATE\s+(?:(UNIQUE)\s+)?(TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z_0-9]*)\b",
            statement, re.I,
        )
        if not found:
            raise ArtworkShadowProvisionError("Only named CREATE TABLE/INDEX allowed")
        names.add((found[2].lower(), found[3].lower()))
    if names != ALLOWED:
        raise ArtworkShadowProvisionError("Unexpected or missing artwork shadow object")
    try:
        conn = sqlite3.connect(":memory:")
        conn.executescript(source)
        actual = set(conn.execute(
            "select type,name from sqlite_master where name glob 'artwork_shadow_*'"
        ))
        conn.close()
    except sqlite3.Error as exc:
        raise ArtworkShadowProvisionError("Local SQLite shadow schema rejected") from exc
    if actual != ALLOWED:
        raise ArtworkShadowProvisionError("Local D1 object drift")
    return statements


def _remote_objects(client, dbid: str) -> set[tuple[str, str]]:
    if not isinstance(dbid, str) or not UUID.fullmatch(dbid):
        raise ArtworkShadowProvisionError("Cloudflare returned invalid D1 database ID")
    data, _ = client.query(
        dbid, "select type,name from sqlite_master where name glob 'artwork_shadow_*' order by name"
    )
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ArtworkShadowProvisionError("D1 schema readback missing")
    return {(r["type"], r["name"]) for r in rows
            if isinstance(r, dict) and isinstance(r.get("type"), str)
            and isinstance(r.get("name"), str)}


def provision(client, source: str, *, account_id: str) -> dict:
    if account_id != ACCOUNT or getattr(client, "account_id", None) != ACCOUNT:
        raise ArtworkShadowProvisionError("Unexpected Cloudflare account")
    statements = parse_schema(source)
    all_db = client.list_databases()
    if not isinstance(all_db, list) or not 0 <= len(all_db) <= 10:
        raise ArtworkShadowProvisionError("Invalid database inventory")
    if any(not isinstance(r, dict) or not isinstance(r.get("name"), str)
           for r in all_db):
        raise ArtworkShadowProvisionError("D1 database inventory ambiguous")
    matches = [r for r in all_db if r["name"] == DB_NAME]
    if len(matches) > 1:
        raise ArtworkShadowProvisionError("Duplicate D1 artwork shadows")
    if matches:
        actual = _remote_objects(client, matches[0].get("uuid"))
        if actual != ALLOWED:
            raise ArtworkShadowProvisionError("Existing D1 artwork schema drift")
        new = False
    else:
        if len(all_db) > MAX_EXISTING:
            raise ArtworkShadowProvisionError("D1 Free slots reserved for full migration")
        created, _ = client.call("POST", client.path, {"name": DB_NAME})
        if not isinstance(created, dict) or created.get("name") != DB_NAME:
            raise ArtworkShadowProvisionError("D1 artwork shadow creation not confirmed")
        dbid = created.get("uuid")
        if not isinstance(dbid, str) or not UUID.fullmatch(dbid):
            raise ArtworkShadowProvisionError("New D1 database ID not verified")
        # Fail closed on any partial create; never delete or retry through drift.
        for statement in statements:
            client.query(dbid, statement)
        actual = _remote_objects(client, dbid)
        if actual != ALLOWED:
            raise ArtworkShadowProvisionError("D1 artwork objects failed readback")
        new = True
    return {
        "status": "EMPTY_ARTWORK_D1_SHADOW_VERIFIED",
        "database_name": DB_NAME,
        "schema_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "schema_objects": len(ALLOWED),
        "created_new": new,
        "artwork_rows_inserted": 0,
        "supabase_writes": 0,
        "shopify_writes": 0,
        "production_media_pointer_changed": False,
        "production_database_cutover": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    source = SQL_FILE.read_text("utf-8")
    if args.validate_only:
        report = {"status": "LOCAL_ARTWORK_SHADOW_SCHEMA_VERIFIED",
                  "statements": len(parse_schema(source))}
    else:
        from d1_remote_catalogue_pilot import D1Client
        account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        token = os.getenv("CLOUDFARE_D1_PILOT_TOKEN", "")
        report = provision(D1Client(account, token), source, account_id=account)
    REPORT_FILE.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
