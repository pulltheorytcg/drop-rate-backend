"""Stage real Supabase operational records into EMPTY, private Cloudflare D1.

This is an intentionally bounded, immutable, one-generation **shadow** import,
NOT a live read switch and NOT a replacement for private R2 source archives.
A protected main-branch GitHub Actions job uses its existing Supabase postgres
secret for one READ-ONLY repeatable-read snapshot, and the existing D1 token.
Never use the application TCG_DATABASE_URL, a Supabase user session, or a
caller-supplied D1 database name.

No R2 byte copy, Auth migration, market-value publication, order posting,
settlement or payment occurs here. Nothing is written to PostgreSQL.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from uuid import UUID

import asyncpg
from d1_remote_catalogue_pilot import D1Client

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
DB_NAME = "drop-rate-d1-operational-shadow-20261106"
PG_PROJECT = "ozrxenrdladkooixutmm"
MAX_SOURCE_ROWS = 3500
MAX_D1_ROWS = 2500
HASH = re.compile(r"[0-9a-f]{64}\Z")
TABLES = (
    "owners", "owner_memberships", "inventory_items", "orders", "order_items",
    "financial_ledger_entries", "refund_events", "shopify_webhook_events",
    "media_assets", "media_object_mirrors",
)
FLOORS = {
    "owners":6, "owner_memberships":6, "inventory_items":621,
    "orders":3, "order_items":3, "financial_ledger_entries":13,
    "refund_events":3, "shopify_webhook_events":14,
    "media_assets":515, "media_object_mirrors":401,
}
TARGETS = {
    "owners":("ops_shadow_owners",(
        "generation_id","id","display_name","owner_type","founder_slot",
        "active","commission_bps","source_row_sha256","source_row_json")),
    "owner_memberships":("ops_shadow_memberships",(
        "generation_id","id","legacy_user_id","owner_id","role","active",
        "source_row_sha256","source_row_json")),
    "inventory_items":("ops_shadow_inventory",(
        "generation_id","id","inventory_code","catalogue_id","owner_id",
        "acquisition_cost_minor","market_value_minor","store_price_minor",
        "currency","condition","grading_company","grade","certificate_number",
        "language","location","status","sale_intent","version",
        "source_row_sha256","source_row_json")),
    "orders":("ops_shadow_orders",(
        "generation_id","id","source","source_reference","currency","status",
        "placed_at","source_row_sha256","source_row_json")),
    "order_items":("ops_shadow_order_items",(
        "generation_id","id","order_id","inventory_id","owner_id",
        "sale_price_minor","discount_minor","net_sale_minor","cost_basis_minor",
        "commission_bps_snapshot","commission_minor","sold_at",
        "source_row_sha256","source_row_json")),
    "refund_events":("ops_shadow_refunds",(
        "generation_id","id","owner_id","order_id","order_item_id","inventory_id",
        "source_reference","amount_minor","currency","occurred_at",
        "source_row_sha256","source_row_json")),
    "financial_ledger_entries":("ops_shadow_ledger",(
        "generation_id","id","owner_id","order_id","order_item_id",
        "payout_request_id","entry_type","amount_minor","currency",
        "funds_status","source_key","occurred_at","available_at",
        "source_row_sha256","source_row_json")),
    "shopify_webhook_events":("ops_shadow_webhook_inbox",(
        "generation_id","id","webhook_id","topic","shop_domain",
        "payload_sha256","status","received_at",
        "source_row_sha256","source_row_json")),
    "media_assets":("ops_shadow_media_assets",(
        "generation_id","id","owner_id","inventory_id","media_kind",
        "media_scope","media_variant","rights_status","approval_status",
        "content_sha256","r2_private_object_key","source_row_sha256",
        "source_row_json")),
}
ORDER = (
    "owners","owner_memberships","inventory_items","orders","order_items",
    "refund_events","financial_ledger_entries","shopify_webhook_events",
    "media_assets",
)
assert set(ORDER)==set(TARGETS)


class StageGuard(ValueError):
    pass


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identity(item: dict) -> str:
    identity = item.get("id")
    if not isinstance(identity,str) or not identity:
        raise StageGuard("Source identity missing")
    return identity


def capture_table(source: list[str], name: str) -> list[tuple[str,dict,str,str]]:
    if name not in TABLES or not isinstance(source,list):
        raise StageGuard("Unapproved PostgreSQL source")
    if not FLOORS[name] <= len(source) <= MAX_SOURCE_ROWS:
        raise StageGuard("Source row count below independent full-table floor or above bound")
    seen = set()
    captured = []
    for payload in source:
        if not isinstance(payload,str) or len(payload)>1_000_000:
            raise StageGuard("Invalid source row JSON")
        record=json.loads(payload)
        if not isinstance(record,dict):
            raise StageGuard("Invalid source row structure")
        key=_identity(record)
        if key in seen:
            raise StageGuard("Duplicate original primary key")
        seen.add(key)
        captured.append((key,record,payload,sha(payload)))
    captured.sort(key=lambda row:row[0])
    return captured


def _digest(records: list[tuple[str,dict,str,str]]) -> str:
    return sha("".join(key+":"+row_sha+"\n" for key,_,_,row_sha in records))


async def source_capture(dsn: str) -> tuple[dict,dict,dict]:
    if not isinstance(dsn,str) or not dsn.startswith("postgresql://") or PG_PROJECT not in dsn:
        raise StageGuard("Unexpected PostgreSQL source")
    conn=await asyncpg.connect(dsn=dsn,command_timeout=90,server_settings={
        "application_name":"drop-rate-d1-private-source-stage",
        "statement_timeout":"90000",
        "idle_in_transaction_session_timeout":"120000",
        "search_path":"pg_catalog,tcg",
    })
    try:
        async with conn.transaction(isolation="repeatable_read",readonly=True):
            role=await conn.fetchrow("""SELECT current_user AS username,
                (SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user) AS bypass""")
            if role["username"]!="postgres" or role["bypass"] is not True:
                raise StageGuard("Source must be existing privileged backup connection in read-only snapshot")
            out={}
            meta={}
            for table in TABLES:
                # Whitelisted identifiers; never SQL constructed from user input.
                records=await conn.fetch(
                    f'SELECT row_to_json(t)::text AS payload FROM tcg."{table}" t ORDER BY t."id"')
                out[table]=capture_table([r["payload"] for r in records],table)
                meta[table]=[{"column":r["attname"],"type":r["data_type"]}
                    for r in await conn.fetch("""SELECT attname,
                    format_type(atttypid,atttypmod) AS data_type
                    FROM pg_attribute
                    WHERE attrelid=$1::regclass AND attnum>0 AND NOT attisdropped
                    ORDER BY attnum""",f"tcg.{table}")]
            # Include a sourced stable ID digest for inventory's canonical FK
            # only. This is NOT an R2 catalogue publication receipt.
            keys={UUID(x[1]["catalogue_id"]) for x in out["inventory_items"]}
            catalogue=await conn.fetch("""SELECT row_to_json(t)::text AS payload
                FROM tcg.catalogue_products t WHERE t.id = ANY($1::uuid[])
                ORDER BY t.id""",sorted(keys))
            catalog={}
            for row in catalogue:
                payload=row["payload"]; obj=json.loads(payload)
                catalog[obj["id"]]=sha(payload)
            if set(catalog)!={str(k) for k in keys}:
                raise StageGuard("Missing source canonical products for inventory")
            if sum(len(v) for v in out.values())>MAX_SOURCE_ROWS:
                raise StageGuard("Operational source snapshot too large for today's bounded transfer")
            return out,meta,catalog
    finally:
        await conn.close()


def _bool(x):
    return int(bool(x))


def _map_row(name: str, gen: str, item: dict, raw: str,
             digest: str, mirrors: dict[str,dict]) -> tuple:
    if name=="owners":
        return (gen,item["id"],item["display_name"],item["owner_type"],
            item["founder_slot"],_bool(item["active"]),item["commission_bps"],
            digest,raw)
    if name=="owner_memberships":
        return (gen,item["id"],item["user_id"],item["owner_id"],item["role"],
                _bool(item["active"]),digest,raw)
    if name=="inventory_items":
        return (gen,item["id"],item["inventory_code"],item["catalogue_id"],
                item["owner_id"],item["acquisition_cost_minor"],
                item["market_value_minor"],item["store_price_minor"],item["currency"],
                item["condition"],item["grading_company"],item["grade"],
                item["certificate_number"],item["language"],item["location"],
                item["status"],item["sale_intent"],item["version"],digest,raw)
    if name=="orders":
        return (gen,item["id"],item["source"],item["source_reference"],
                item["currency"],item["status"],item["placed_at"],digest,raw)
    if name=="order_items":
        return (gen,item["id"],item["order_id"],item["inventory_id"],item["owner_id"],
                item["sale_price_minor"],item["discount_minor"],item["net_sale_minor"],
                item["cost_basis_minor"],item["commission_bps_snapshot"],
                item["commission_minor"],item["sold_at"],digest,raw)
    if name=="refund_events":
        return (gen,item["id"],item["owner_id"],item["order_id"],item["order_item_id"],
                item["inventory_id"],item["source_reference"],item["amount_minor"],
                item["currency"],item["occurred_at"],digest,raw)
    if name=="financial_ledger_entries":
        return (gen,item["id"],item["owner_id"],item["order_id"],item["order_item_id"],
                item["payout_request_id"],item["entry_type"],item["amount_minor"],
                item["currency"],item["funds_status"],item["source_key"],
                item["occurred_at"],item["available_at"],digest,raw)
    if name=="shopify_webhook_events":
        return (gen,item["id"],item["webhook_id"],item["topic"],item["shop_domain"],
                item["payload_sha256"],item["status"],item["received_at"],digest,raw)
    if name=="media_assets":
        mirror=mirrors.get(item["id"])
        # A mirror metadata row is not proof the object bytes exist in R2.
        # Keep the R2 key NULL until independent byte-level verification.
        _=mirror
        return (gen,item["id"],item["owner_id"],item["inventory_id"],
                item["media_kind"],item["scope"],item["media_variant"],
                item["rights_status"],item["approval_status"],
                item["content_sha256"],None,digest,raw)
    raise StageGuard("Unexpected target map")


def _d1_query(client, dbid: str, sql: str, params=()) -> list[dict]:
    result,_=client.query(dbid,sql,params)
    data=result.get("results") if isinstance(result,dict) else None
    if not isinstance(data,list):
        raise StageGuard("Cloudflare D1 readback missing")
    return data


def _insert_rows(client,dbid,table,columns,records):
    width=len(columns)
    if width<1 or width>40 or not records:
        raise StageGuard("Invalid source stage statement")
    chunk=max(1,72//width)
    querylist=[]
    for start in range(0,len(records),chunk):
        subset=records[start:start+chunk]
        if any(len(row)!=width for row in subset):
            raise StageGuard("Source fields do not match D1 target")
        sql=(f'INSERT OR IGNORE INTO "{table}" ('
             + ",".join(f'"{c}"' for c in columns)+") VALUES "
             + ",".join("("+",".join("?" for _ in columns)+")" for _ in subset))
        querylist.append({"sql":sql,"params":[v for row in subset for v in row]})
    for offset in range(0,len(querylist),8):
        client.batch(dbid,querylist[offset:offset+8])


def _verify_rows(client,dbid,table,gen,expected):
    rows=_d1_query(client,dbid,
        f'SELECT id,source_row_sha256 FROM "{table}" WHERE generation_id=? ORDER BY id',
        [gen])
    actual=[(r["id"],r["source_row_sha256"]) for r in rows]
    wanted=[(r[0],r[3]) for r in expected]
    if len(actual)!=len(wanted) or actual!=wanted:
        raise StageGuard("D1 shadow row-count/identity/hash parity failure")


def stage(client, captured, schema, catalogue) -> dict:
    if client.account_id!=ACCOUNT:
        raise StageGuard("Wrong Cloudflare account")
    databases=client.list_databases()
    db=[d for d in databases if d.get("name")==DB_NAME]
    if len(db)!=1 or not re.fullmatch(r"[a-fA-F0-9-]{36}",db[0].get("uuid","")):
        raise StageGuard("Private operational shadow unavailable")
    dbid=db[0]["uuid"]
    schema_objects=_d1_query(client,dbid,
        "SELECT type,name FROM sqlite_master WHERE name GLOB 'ops_shadow_*'")
    if len(schema_objects)!=32:
        raise StageGuard("Target D1 schema no longer matches verified 32-object shadow")
    data_digest=sha("".join(t+":"+_digest(captured[t])+"\n" for t in TABLES)
                    +"catalogue:"+sha(json.dumps(catalogue,sort_keys=True))+"\n")
    schema_digest=sha(json.dumps(schema,sort_keys=True,separators=(",",":")))
    generation="src-"+data_digest[:32]
    total=sum(len(captured[t]) for t in ORDER)+len(catalogue)+len({
        x[1]["user_id"] for x in captured["owner_memberships"]})+len(ORDER)+1
    if total>MAX_D1_ROWS:
        raise StageGuard("Unapproved D1 daily write budget")
    _insert_rows(client,dbid,"ops_shadow_generations",
        ("generation_id","source_manifest_sha256","source_captured_at","source_schema_sha256","state"),
        [(generation,data_digest,datetime.now(timezone.utc).isoformat(),
            schema_digest,"STAGING")])
    users=sorted({x[1]["user_id"] for x in captured["owner_memberships"]})
    _insert_rows(client,dbid,"ops_shadow_identity_map",
        ("generation_id","legacy_user_id"),
        [(generation,u) for u in users])
    _insert_rows(client,dbid,"ops_shadow_catalogue_links",
        ("generation_id","catalogue_id","reference_manifest_sha256"),
        [(generation,k,v) for k,v in sorted(catalogue.items())])
    mirror_by_asset={x[1]["media_asset_id"]:x[1]
                     for x in captured["media_object_mirrors"]}
    receipts=[]
    for name in ORDER:
        table,columns=TARGETS[name]
        items=captured[name]
        rows=[_map_row(name,generation,rec,raw,digest,mirror_by_asset)
              for _,rec,raw,digest in items]
        _insert_rows(client,dbid,table,columns,rows)
        _verify_rows(client,dbid,table,generation,items)
        digest=_digest(items)
        receipts.append((generation,"tcg",name,len(items),len(items),digest,
                         digest,datetime.now(timezone.utc).isoformat()))
    _insert_rows(client,dbid,"ops_shadow_table_receipts",
        ("generation_id","source_schema","source_table","exact_source_rows",
         "exact_staged_rows","source_sha256","staged_sha256","verified_at"),
        receipts)
    actual_receipts=_d1_query(client,dbid,"SELECT source_table FROM ops_shadow_table_receipts WHERE generation_id=?",[generation])
    if set(x["source_table"] for x in actual_receipts)!=set(ORDER):
        raise StageGuard("Incomplete D1 source parity receipts")
    # Query monetary totals back from the D1 shadow and cross-check every
    # original owner/currency balance to the penny (including negative entries).
    sums=defaultdict(int)
    for _,record,_,_ in captured["financial_ledger_entries"]:
        sums[(record["owner_id"],record["currency"])]+=record["amount_minor"]
    remote=_d1_query(client,dbid,
        "SELECT owner_id,currency,SUM(amount_minor) AS total FROM ops_shadow_ledger "
        "WHERE generation_id=? GROUP BY owner_id,currency",[generation])
    remote_sums={(r["owner_id"],r["currency"]):r["total"] for r in remote}
    if dict(sums)!=remote_sums:
        raise StageGuard("Founder ledger balance differs by owner/currency")
    return {
        "status":"PRIVATE_OPERATIONAL_D1_SOURCE_STAGED_NOT_LIVE",
        "generation_sha256":data_digest,
        "source_schema_sha256":schema_digest,
        "counts":{name:len(captured[name]) for name in ORDER},
        "catalogue_links":len(catalogue),
        "identity_mappings_without_credentials":len(users),
        "verified_table_receipts":len(receipts),
        "source_business_writes":0,
        "supabase_source_retired":False,
        "production_read_switch":False,
        "customer_auth_migrated":False,
        "market_value_published":False,
        "payment_or_settlement_executed":False,
        "r2_source_upload_verified_by_this_job":False,
    }


async def main():
    dsn=os.getenv("FULL_EXIT_PG_READONLY_DSN","")
    token=os.getenv("CLOUDFARE_D1_PILOT_TOKEN","")
    account=os.getenv("CLOUDFLARE_ACCOUNT_ID","")
    if account!=ACCOUNT or not token.strip() or not dsn:
        raise StageGuard("Protected credentials or expected account missing")
    captured,schema,catalogue=await source_capture(dsn)
    client=D1Client(account,token)
    return stage(client,captured,schema,catalogue)


if __name__=="__main__":
    try:
        result=asyncio.run(main())
        print(json.dumps(result,sort_keys=True,separators=(",",":")))
    except Exception as exc:
        # NEVER print private source rows, SQL parameters, DSNs or secrets.
        raise SystemExit("Private D1 stage did not verify: "+type(exc).__name__) from None
