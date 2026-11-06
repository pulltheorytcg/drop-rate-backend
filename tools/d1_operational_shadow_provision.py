"""Provision a *private empty* Cloudflare operational D1 SHADOW on reviewed main only.

This never touches Supabase, Shopify, Market Values, founder stock, payments
or Cloudflare account plans. All source rows remain in PostgreSQL. The first
database creation is irreversible without an independent explicit deletion
approval; never auto-delete after partial schema failure.
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
DB_NAME = "drop-rate-d1-operational-shadow-20261106"
SQL_PATH = Path("database/cloudflare_d1/0001_operational_shadow.sql")
REPORT_PATH = Path("d1-operational-shadow-schema-report.json")
# 5 existing D1 DBs measured on 6 Nov; preserve two future database slots.
MAX_EXISTING_BEFORE_CREATE = 7
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")
DDL_NAME = re.compile(
    r"\A\s*CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER)\s+"
    r"IF\s+NOT\s+EXISTS\s+([a-z_][a-z_0-9]*)",
    flags=re.IGNORECASE,
)


class ProvisionGuard(ValueError):
    """Any unsupported schema, account, database or drift prevents writes."""


def parse_schema(source: str) -> tuple[list[str], set[tuple[str, str]]]:
    if not isinstance(source, str) or not 100 < len(source) < 100_000:
        raise ProvisionGuard("Unexpected operational shadow schema size")
    statements: list[str] = []
    buffer = ""
    for line in source.splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            sql = buffer.strip()
            buffer = ""
            if sql.upper().startswith("PRAGMA FOREIGN_KEYS=ON"):
                continue
            statements.append(sql)
    if buffer.strip() or not statements:
        raise ProvisionGuard("Incomplete or missing SQLite D1 DDL")
    names: set[tuple[str, str]] = set()
    for sql in statements:
        match = DDL_NAME.match(sql)
        if match is None:
            raise ProvisionGuard("Operational stage accepts CREATE statements only")
        kind,name = match[1].lower(),match[2].lower()
        if not name.startswith("ops_shadow_") or (kind,name) in names:
            raise ProvisionGuard("Unscoped or duplicate shadow object")
        names.add((kind,name))
    must_have = {
        ("table","ops_shadow_generations"),
        ("table","ops_shadow_identity_map"),
        ("table","ops_shadow_owners"),
        ("table","ops_shadow_memberships"),
        ("table","ops_shadow_inventory"),
        ("table","ops_shadow_orders"),
        ("table","ops_shadow_order_items"),
        ("table","ops_shadow_refunds"),
        ("table","ops_shadow_ledger"),
        ("table","ops_shadow_webhook_inbox"),
        ("table","ops_shadow_reservations"),
        ("table","ops_shadow_payout_requests"),
        ("table","ops_shadow_shopify_item_links"),
        ("table","ops_shadow_media_assets"),
        ("table","ops_shadow_audit_events"),
        ("table","ops_shadow_table_receipts"),
    }
    if not must_have.issubset(names):
        raise ProvisionGuard("Operational shadow DDL missing money, auth or copy-provenance tables")
    return statements,names


def _remote_names(client, uuid: str) -> set[tuple[str,str]]:
    if not UUID.fullmatch(uuid):
        raise ProvisionGuard("Cloudflare returned an invalid database UUID")
    result,_ = client.query(uuid,
        "SELECT type,name FROM sqlite_master WHERE name GLOB 'ops_shadow_*' ORDER BY type,name")
    data = result.get("results") if isinstance(result,dict) else None
    if not isinstance(data,list):
        raise ProvisionGuard("Unverifiable D1 sqlite_master state")
    keys = set()
    for row in data:
        if not isinstance(row,dict) or not isinstance(row.get("type"),str) or not isinstance(row.get("name"),str):
            raise ProvisionGuard("Unverifiable D1 object")
        kind,name=row["type"].lower(),row["name"].lower()
        if kind not in {"table","index","trigger"} or (kind,name) in keys:
            raise ProvisionGuard("Unexpected/duplicate remote D1 object")
        keys.add((kind,name))
    return keys


def provision(client, schema: str, *, account_id: str) -> dict:
    if account_id != ACCOUNT or getattr(client,"account_id",None) != ACCOUNT:
        raise ProvisionGuard("Unexpected Cloudflare D1 account")
    statements,expected=parse_schema(schema)
    databases=client.list_databases()
    if not isinstance(databases,list) or len(databases)>10:
        raise ProvisionGuard("Unexpected D1 database list")
    found=[r for r in databases if isinstance(r,dict) and r.get("name")==DB_NAME]
    if len(found)>1:
        raise ProvisionGuard("Duplicate operational D1 DB name")
    schema_sha=hashlib.sha256(schema.encode("utf-8")).hexdigest()
    if found:
        dbid=found[0].get("uuid")
        actual=_remote_names(client,dbid)
        if actual!=expected:
            raise ProvisionGuard("Existing operational D1 shadow is incomplete or has schema drift")
        return {
            "status":"EXISTING_EMPTY_OPERATIONAL_D1_SCHEMA_OBJECTS_VERIFIED",
            "database_name":DB_NAME,"source_schema_sha256":schema_sha,
            "expected_schema_objects":len(expected),"actual_schema_objects":len(actual),
            "new_database_created":False,"postgres_writes":0,
            "market_value_writes":0,"customer_data_imported":False,
            "production_reads_switched":False,"production_finance_cutover":False,
        }
    if len(databases)>MAX_EXISTING_BEFORE_CREATE:
        raise ProvisionGuard("Insufficient D1 Free database slots after reserved headroom")
    if any(not isinstance(r,dict) or not isinstance(r.get("name"),str) for r in databases):
        raise ProvisionGuard("Unidentified existing D1 database")
    metadata,_=client.call("POST",client.path,{"name":DB_NAME})
    if not isinstance(metadata,dict) or metadata.get("name")!=DB_NAME:
        raise ProvisionGuard("Cloudflare did not create the exact scoped operational shadow")
    dbid=metadata.get("uuid")
    if not isinstance(dbid,str) or not UUID.fullmatch(dbid):
        raise ProvisionGuard("Cloudflare D1 response lacks valid new database UUID")
    # Any interrupted DDL leaves an isolated incomplete DB requiring a manual
    # review. No automatic retry against partially created schema.
    for sql in statements:
        client.query(dbid,sql)
    actual=_remote_names(client,dbid)
    if actual!=expected:
        raise ProvisionGuard("New isolated operational D1 schema failed remote readback")
    return {
        "status":"PRIVATE_OPERATIONAL_D1_SCHEMA_PROVISIONED_NO_DATA",
        "database_name":DB_NAME,"source_schema_sha256":schema_sha,
        "expected_schema_objects":len(expected),"actual_schema_objects":len(actual),
        "new_database_created":True,"postgres_writes":0,
        "market_value_writes":0,"customer_data_imported":False,
        "production_reads_switched":False,"production_finance_cutover":False,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only",action="store_true")
    args=parser.parse_args()
    schema=SQL_PATH.read_text(encoding="utf-8")
    if args.validate_only:
        statements,names=parse_schema(schema)
        result={"status":"OPERATIONAL_SHADOW_DDL_LOCAL_VALIDATED",
                "schema_objects":len(names),"statements":len(statements)}
    else:
        from d1_remote_catalogue_pilot import D1Client
        account=os.getenv("CLOUDFLARE_ACCOUNT_ID","")
        token=os.getenv("CLOUDFARE_D1_PILOT_TOKEN","")
        result=provision(D1Client(account,token),schema,account_id=account)
    REPORT_PATH.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
