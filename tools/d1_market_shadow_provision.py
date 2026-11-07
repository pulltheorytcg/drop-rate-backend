"""Provision current-price evidence isolation in the EXISTING private D1 shadow.

No price data, no active generation, no Shopify writes and no live price API.
Uses one existing D1 database and an account-guarded protected GitHub job.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from d1_remote_catalogue_pilot import D1Client

ACCOUNT="e4d4b363540e991048d2e1812d5ef53e"
DB_NAME="drop-rate-d1-operational-shadow-20261106"
SQL_PATH=Path("database/cloudflare_d1/0002_market_value_shadow.sql")
REPORT_PATH=Path("d1-market-value-shadow-schema-report.json")
UUID=re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
DDL=re.compile(r"\A\s*CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER|VIEW)\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z_0-9]*)",re.I)

class MarketShadowGuard(ValueError): pass

def parse_schema(source: str):
    if not isinstance(source,str) or not 100 < len(source) < 30000:
        raise MarketShadowGuard("Unexpected market shadow schema length")
    statements=[];buf=""
    for line in source.splitlines(keepends=True):
        if line.lstrip().startswith("--"): continue
        buf+=line
        if sqlite3.complete_statement(buf):
            statement=buf.strip();buf=""
            if statement.upper().replace(" ","").startswith("PRAGMAFOREIGN_KEYS=ON"):
                continue
            statements.append(statement)
    if buf.strip() or not statements:
        raise MarketShadowGuard("Incomplete market-value D1 schema")
    names=set()
    for statement in statements:
        match=DDL.match(statement)
        if match is None:
            raise MarketShadowGuard("Market schema contains a non-CREATE statement")
        kind,name=match.group(1).lower(),match.group(2).lower()
        if not name.startswith("market_shadow_") or (kind,name) in names:
            raise MarketShadowGuard("Unscoped or duplicate Market Value shadow DDL")
        names.add((kind,name))
    required={
      ("table","market_shadow_generations"),
      ("table","market_shadow_profiles"),
      ("table","market_shadow_source_proofs"),
      ("table","market_shadow_current_values"),
      ("view","market_shadow_eligible_values"),
      ("trigger","market_shadow_market_value_source_gate"),
      ("trigger","market_shadow_price_no_update"),
      ("trigger","market_shadow_price_no_delete"),
      ("trigger","market_shadow_proof_no_update"),
      ("trigger","market_shadow_proof_no_delete"),
    }
    if not required.issubset(names):
        raise MarketShadowGuard("Missing no-RRP/asking/guide and immutable provenance controls")
    return statements,names


def remote_names(client,dbid):
    rows,_=client.query(dbid,"SELECT type,name FROM sqlite_master WHERE name GLOB 'market_shadow_*'")
    data=rows.get("results") if isinstance(rows,dict) else None
    if not isinstance(data,list):raise MarketShadowGuard("Missing remote Market Value schema proof")
    out=set()
    for r in data:
        if not isinstance(r,dict) or r.get("type") not in {"table","index","trigger","view"}:
            raise MarketShadowGuard("Unexpected remote market schema object")
        item=(r["type"],r.get("name"))
        if item in out:raise MarketShadowGuard("Duplicate remote schema object")
        out.add(item)
    return out


def provision(client, source):
    if client.account_id!=ACCOUNT:
        raise MarketShadowGuard("Wrong Cloudflare account")
    statements,expected=parse_schema(source)
    databases=client.list_databases()
    matches=[r for r in databases if isinstance(r,dict) and r.get("name")==DB_NAME]
    if len(matches)!=1 or not UUID.fullmatch(matches[0].get("uuid","")):
        raise MarketShadowGuard("Missing exact existing private operational shadow")
    dbid=matches[0]["uuid"]
    preexisting=remote_names(client,dbid)
    if preexisting and preexisting!=expected:
        raise MarketShadowGuard("Existing market D1 schema is incomplete or has drift")
    if not preexisting:
        # Only CREATE (not DROP/ALTER/INSERT/UPDATE). Never provision on PRs.
        for statement in statements:client.query(dbid,statement)
    actual=remote_names(client,dbid)
    if actual!=expected:raise MarketShadowGuard("Market D1 shadow schema readback differs")
    # Source-only; never provide false data/value parity claims.
    return {
      "status":("EXISTING_PRIVATE_MARKET_D1_SCHEMA_VERIFIED" if preexisting
                else "PRIVATE_MARKET_D1_SCHEMA_CREATED_NO_DATA"),
      "database_name":DB_NAME,
      "source_schema_sha256":hashlib.sha256(source.encode()).hexdigest(),
      "expected_schema_objects":len(expected),
      "actual_schema_objects":len(actual),
      "new_database_created":False,
      "customer_or_market_rows_imported":0,
      "eligible_market_value_published":0,
      "guide_or_asking_prices_promoted":0,
      "postgres_writes":0,
      "production_reads_switched":False,
      "source_archives_replaced":False,
    }


def main():
    source=SQL_PATH.read_text(encoding="utf-8")
    statements,names=parse_schema(source)
    if os.getenv("MARKET_D1_VALIDATE_ONLY","").lower()=="true":
        with sqlite3.connect(":memory:") as db:
            db.executescript(source)
            actual={(r[0],r[1]) for r in db.execute(
                "SELECT type,name FROM sqlite_master WHERE name GLOB 'market_shadow_*'")}
        if names!=actual:raise MarketShadowGuard("SQLite market shadow structure mismatch")
        return {"status":"LOCAL_MARKET_D1_SCHEMA_ONLY_VALIDATED","objects":len(names)}
    token=os.getenv("CLOUDFARE_D1_PILOT_TOKEN","").strip()
    account=os.getenv("CLOUDFLARE_ACCOUNT_ID","")
    if account!=ACCOUNT or not token:
        raise MarketShadowGuard("Protected market D1 secret missing")
    return provision(D1Client(account,token),source)


if __name__=="__main__":
    try:
        result=main()
        REPORT_PATH.write_text(json.dumps(result,sort_keys=True)+"\n",encoding="utf-8")
        print(json.dumps(result,sort_keys=True))
    except Exception as exc:
        # Omit Cloudflare credentials, SQL, private record contents or error bodies.
        raise SystemExit("Private Market Value schema check failed: "+type(exc).__name__) from None
