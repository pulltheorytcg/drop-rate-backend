"""Stage the ENTIRE typed legacy R2 catalogue into an isolated D1 reference DB.

A single immutable, owner-free source (generation 122500) carries five
DIFFERENT relations. Preserve every original field and composite key as
payload + hashed identity, rather than treating sets/sealed/comics as cards.
Never publish until every source row is SHA256-equal after full D1 readback.
No production search, Shopify, Market Value, inventory or ledger writes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

import httpx

from app import catalogue_r2_live as legacy
from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import (
    SOURCE_PATH, _oidc_token, _query, fetch_bytes, MigrationGuard,
)
from d1_followon_r2_shadow import (
    ACCOUNT, DB_NAME as FOLLOWON_DB, SOURCES as FOLLOWON_SOURCES,
    _listed, _source_active, _disk_used,
)

SOURCE_PATH_LEGACY_D1 = SOURCE_PATH + "/legacy-d1"
LEGACY_DB = "drop-rate-d1-real-legacy-catalogue-shadow"
GENERATION = 122500
MANIFEST_SHA = "2dc9e6bd30d3508388d41513cfeb7a9b6d003dd6223a3f6a2d08c28b5aad7403"
SOURCE_BYTES = 29_831_680
SOURCE_PARTS = 161
COUNTS = {
    "reference_cards": 69697,
    "reference_sets": 1472,
    "reference_sealed_products": 3893,
    "catalogue_products": 2062,
    "catalogue_product_profiles": 2062,
}
RELATION_SHA = {
    "reference_cards": "5c04191f7979c76765b557c222fd9e1ec08bb0885d5e7fbc5e4b268ad8de14aa",
    "reference_sets": "2e62a558c3f0349b5a4050b1b4f67a46cd14903cdeb41a6dd0091d61be7",
    "reference_sealed_products": "cc7e206837729fb67f2abd330d909f4f8b2b81cad35937a32ad7fb74d4083961",
    "catalogue_products": "7a11685afaba6ca761676f5d2c486a98a095e67b7448634040abe3dd0a6bab3c",
    "catalogue_product_profiles": "0a6c9a2b277fd0212bcf5a736cb197052c7cb4c715652ce420e2418fc50be560",
}
EXPECTED_ROWS = 79_186
DAILY_ROWS = 5_000
MAX_DB_SLOTS_BEFORE_NEW = 8
SAFETY_BYTES = 390_000_000
REPORT = "d1-legacy-real-r2-shadow-report.json"
COLUMNS = (
    "manifest_sha","relation","identity_sha","payload_json",
    "provider","system_code","language","set_id","name_fold",
    "lookup_id","product_type",
)

SCHEMA = """
create table if not exists legacy_generations(
  manifest_sha text primary key check(length(manifest_sha)=64),
  generation integer not null, expected_rows integer not null,
  source_schema text not null, counts_json text not null,
  projection_sha text not null check(length(projection_sha)=64)
);
create table if not exists legacy_shadow_rows(
  manifest_sha text not null references legacy_generations(manifest_sha),
  relation text not null, identity_sha text not null check(length(identity_sha)=64),
  payload_json text not null,
  provider text, system_code text, language text, set_id text,
  name_fold text, lookup_id text, product_type text,
  primary key(manifest_sha,relation,identity_sha)
);
create index if not exists legacy_shadow_identity_idx on legacy_shadow_rows(
  manifest_sha,relation,provider,system_code,language,lookup_id
);
create index if not exists legacy_shadow_browse_idx on legacy_shadow_rows(
  manifest_sha,relation,system_code,language,set_id,name_fold
);
create table if not exists legacy_active_generation(
  singleton integer primary key check(singleton=1),
  manifest_sha text not null references legacy_generations(manifest_sha)
);
create table if not exists legacy_daily_budget(
  utc_day text primary key,
  manifest_sha text not null references legacy_generations(manifest_sha),
  run_id text not null,
  rows_limit integer not null check(rows_limit between 1 and 5000)
);
create view if not exists legacy_live_rows as
  select r.* from legacy_shadow_rows r join legacy_active_generation a
  on a.manifest_sha=r.manifest_sha where a.singleton=1;
"""

GENERATION_SQL = """insert into legacy_generations
(manifest_sha,generation,expected_rows,source_schema,counts_json,projection_sha)
values(?,?,?,?,?,?)"""
ROWS_SQL = "insert into legacy_shadow_rows (" + ",".join(COLUMNS) + ") values "
READBACK_SQL = ("select " + ",".join(COLUMNS) +
                " from legacy_shadow_rows where manifest_sha=? "
                "order by relation,identity_sha limit ? offset ?")
ACTIVATE_SQL = """insert into legacy_active_generation(singleton,manifest_sha)
select 1,? where
  (select count(*) from legacy_shadow_rows where manifest_sha=?)=?
on conflict(singleton) do update set manifest_sha=excluded.manifest_sha"""


@dataclass(frozen=True)
class LegacyProjection:
    manifest_sha: str
    generation: int
    counts: dict
    digest: str
    rows: tuple[tuple, ...]

    @property
    def count(self) -> int:
        return len(self.rows)


def _json(obj: object) -> str:
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":"))


def _source(http: httpx.Client):
    """No D1 writes before all 161 original bytes and relations have passed."""
    for attempt in range(30):
        token = _oidc_token()
        try:
            raw = fetch_bytes(
                http,SOURCE_PATH_LEGACY_D1+"/manifest",token,120_000,
                source_path=SOURCE_PATH_LEGACY_D1,
            )
            break
        except MigrationGuard as exc:
            if str(exc) not in ("R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503") or attempt==29:
                raise
            time.sleep(10)
    try:
        manifest = legacy.validate_manifest(json.loads(raw), GENERATION)
    except (TypeError,ValueError,legacy.ObjectStorageError) as exc:
        raise MigrationGuard("Legacy source manifest invalid") from exc
    if (legacy.manifest_digest(manifest)!=MANIFEST_SHA
            or manifest["counts"]!=COUNTS
            or manifest["raw_bytes"]!=SOURCE_BYTES
            or len(manifest["parts"])!=SOURCE_PARTS):
        raise MigrationGuard("Legacy R2 generation changed: manual source review required")
    parts=[]
    for index,part in enumerate(manifest["parts"]):
        data=fetch_bytes(
            http,f"{SOURCE_PATH_LEGACY_D1}/part/{index}",token,4_000_000,
            source_path=SOURCE_PATH_LEGACY_D1,
        )
        try:
            legacy.parse_part(data,part["relation"],part["sha256"],
                              part["raw_bytes"],part["rows"])
        except (TypeError,ValueError,legacy.ObjectStorageError) as exc:
            raise MigrationGuard("Legacy source part checksum failed") from exc
        parts.append(data)
    try:
        snap=legacy.assemble(manifest,parts)
    except (TypeError,ValueError,legacy.ObjectStorageError) as exc:
        raise MigrationGuard("Legacy original identities failed reconstruction") from exc
    return _project(snap)


def _project(snap: legacy.LiveCatalogue) -> LegacyProjection:
    if snap.generation!=GENERATION or snap.manifest_digest!=MANIFEST_SHA:
        raise MigrationGuard("Wrong legacy R2 source revision")
    if set(snap.rows)!=set(legacy.RELATIONS):
        raise MigrationGuard("Legacy source relation set is incomplete")
    records=[]
    for relation in sorted(legacy.RELATIONS):
        values=snap.rows[relation]
        if len(values)!=COUNTS[relation]:
            raise MigrationGuard("Missing original legacy source rows")
        checksum=hashlib.sha256()
        for value in values:
            if set(value)!={key for key,_ in legacy.RELATIONS[relation]}:
                raise MigrationGuard("Legacy record has unapproved columns")
            original_key=tuple(value[k] for k in legacy.KEYS[relation])
            if any(not isinstance(k,str) or not k for k in original_key):
                raise MigrationGuard("Legacy source key is incomplete")
            identity_sha=hashlib.sha256(_json([relation,original_key]).encode()).hexdigest()
            payload=_json(value)
            checksum.update(payload.encode()+b"\n")
            lookup=(value.get("provider_id") or value.get("id")
                    or value.get("catalogue_id") or value.get("set_id"))
            records.append((
                snap.manifest_digest,relation,identity_sha,payload,
                value.get("provider"),value.get("system_code"),
                value.get("language"),value.get("set_id") or value.get("set_code"),
                (value.get("name") or "").casefold(),lookup,
                value.get("product_type") or value.get("collectible_type"),
            ))
        if checksum.hexdigest()!=RELATION_SHA[relation]:
            raise MigrationGuard("Legacy original relation source digest mismatch")
    records.sort(key=lambda item:(item[1],item[2]))
    if len(records)!=EXPECTED_ROWS or len({(r[1],r[2]) for r in records})!=EXPECTED_ROWS:
        raise MigrationGuard("Legacy source projection duplicates or truncation")
    digest=hashlib.sha256()
    for record in records:
        digest.update(json.dumps(record,ensure_ascii=False,
                                 separators=(",",":")).encode()+b"\n")
    return LegacyProjection(snap.manifest_digest,GENERATION,dict(COUNTS),
                            digest.hexdigest(),tuple(records))


def _staged_rows(cloud: D1Client,uid: str, source: LegacyProjection) -> int:
    counts=_query(cloud,uid,
        "select count(*) as n from legacy_shadow_rows where manifest_sha=?",
        (source.manifest_sha,))
    if len(counts)!=1 or type(counts[0].get("n")) is not int:
        raise MigrationGuard("Cannot verify legacy shadow row count")
    n=counts[0]["n"]
    if not 0<=n<=source.count:
        raise MigrationGuard("Unexpected legacy shadow row count")
    start=0
    while start<n:
        page=_query(cloud,uid,READBACK_SQL,
                    (source.manifest_sha,min(100,n-start),start))
        if len(page)!=min(100,n-start):
            raise MigrationGuard("Truncated legacy D1 page")
        for i,row in enumerate(page):
            if (not isinstance(row,dict) or set(row)!=set(COLUMNS)
                    or tuple(row[name] for name in COLUMNS)!=source.rows[start+i]):
                raise MigrationGuard("Legacy staged row differs from original source")
        start+=len(page)
    return n


def _verify_full(cloud: D1Client,uid: str, source: LegacyProjection) -> int:
    if _staged_rows(cloud,uid,source)!=source.count:
        raise MigrationGuard("Legacy D1 reference count has not reached source total")
    digest=hashlib.sha256()
    found={name:0 for name in COUNTS}
    offset=0
    while offset<source.count:
        rows=_query(cloud,uid,READBACK_SQL,
                    (source.manifest_sha,min(100,source.count-offset),offset))
        if not rows:
            raise MigrationGuard("Missing legacy D1 readback page")
        for row in rows:
            item=tuple(row[name] for name in COLUMNS)
            if item[1] not in found:
                raise MigrationGuard("Unexpected D1 relation")
            found[item[1]]+=1
            digest.update(json.dumps(item,ensure_ascii=False,
                                     separators=(",",":")).encode()+b"\n")
        offset+=len(rows)
    if digest.hexdigest()!=source.digest or found!=source.counts:
        raise MigrationGuard("Legacy D1 complete source SHA/count parity mismatch")
    return source.count


def _next_stage(cloud: D1Client,uid: str,source:LegacyProjection,today: str,run_id: str):
    current=_staged_rows(cloud,uid,source)
    if current==source.count:
        return current,0
    prior=_query(cloud,uid,
                 "select manifest_sha from legacy_daily_budget where utc_day=?",
                 (today,))
    if len(prior)>1:
        raise MigrationGuard("Duplicate legacy write receipt")
    if prior:
        if prior[0]["manifest_sha"]!=source.manifest_sha:
            raise MigrationGuard("Another legacy source used today's D1 quota")
        return current,0
    limit=min(DAILY_ROWS,source.count-current)
    _query(cloud,uid,"insert into legacy_daily_budget(utc_day,manifest_sha,run_id,rows_limit) "
           "values(?,?,?,?)",(today,source.manifest_sha,run_id,limit))
    chunk=100//len(COLUMNS)
    for start in range(current,current+limit,chunk):
        batch=source.rows[start:min(current+limit,start+chunk)]
        values=",".join("("+",".join("?" for _ in COLUMNS)+")" for _ in batch)
        flattened=[item for row in batch for item in row]
        _query(cloud,uid,ROWS_SQL+values,flattened)
    updated=_staged_rows(cloud,uid,source)
    if updated!=current+limit:
        raise MigrationGuard("Legacy staged D1 row count differs from daily receipt")
    return updated,limit


def _preflight(cloud:D1Client,dbs:dict[str,str],today:str):
    """Block before source fetch and any D1 create until all follow-on sources done."""
    def waiting(reason):
        return {
            "status":"LEGACY_WAITING_FOR_PRECEDING_CATALOGUE",
            "reason":reason,"source_rows":EXPECTED_ROWS,"d1_staged_rows":0,
            "d1_writes":0,"market_value_writes":0,
            "owner_and_settlement_writes":0,"production_reads_switched":False,
        }
    uid=dbs.get(FOLLOWON_DB)
    if uid is None:
        return waiting("FOLLOWON_D1_NOT_YET_PRESENT")
    for source in FOLLOWON_SOURCES:
        if not _source_active(cloud,uid,source):
            return waiting("FOLLOWON_FULL_PARITY_NOT_YET_ACTIVE")
    day_rows=_query(cloud,uid,
        "select max(utc_day) as day from followon_daily_budget")
    if len(day_rows)!=1 or day_rows[0].get("day")==today:
        return waiting("FOLLOWON_WROTE_TODAY_OR_RECEIPT_UNAVAILABLE")
    total=0
    for uuid in dbs.values():
        size=_disk_used(cloud,uuid)
        total+=size
    if total>=4_000_000_000:
        return waiting("D1_ACCOUNT_STORAGE_HEADROOM_NOT_PROVEN")
    if LEGACY_DB not in dbs and len(dbs)>=MAX_DB_SLOTS_BEFORE_NEW:
        return waiting("FREE_DATABASE_SLOT_RESERVED_FOR_OPERATIONS")
    return None


def run(account:str,token:str,run_id:str,attempt:str,*,
        http:httpx.Client|None=None,now:datetime|None=None):
    if account!=ACCOUNT or not re.fullmatch(r"[0-9]{1,20}",run_id) or not re.fullmatch(
            r"[0-9]{1,4}",attempt):
        raise MigrationGuard("Only trusted fixed main workflow can migrate legacy source")
    if http is None:
        with httpx.Client(follow_redirects=False,timeout=httpx.Timeout(25)) as session:
            return run(account,token,run_id,attempt,http=session,now=now)
    when=(now or datetime.now(timezone.utc))
    if when.tzinfo is None:
        raise MigrationGuard("UTC date required")
    today=when.astimezone(timezone.utc).date().isoformat()
    cloud=D1Client(account,token)
    dbs=_listed(cloud)
    blocked=_preflight(cloud,dbs,today)
    if blocked is not None:
        return blocked

    source=_source(http)
    uid=dbs.get(LEGACY_DB)
    if uid is None:
        response,_=cloud.call("POST",cloud.path,{"name":LEGACY_DB})
        if not isinstance(response,dict) or response.get("name")!=LEGACY_DB:
            raise MigrationGuard("D1 did not create approved private legacy DB")
        uid=response.get("uuid")
        if not isinstance(uid,str) or not re.fullmatch(
                r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",uid):
            raise MigrationGuard("D1 did not return exact legacy database UUID")
    _disk_used(cloud,uid)
    for statement in SCHEMA.split(";"):
        if statement.strip():
            _query(cloud,uid,statement)
    generations=_query(cloud,uid,"select manifest_sha,generation,expected_rows,"
        "source_schema,counts_json,projection_sha from legacy_generations")
    expected=(source.manifest_sha,source.generation,source.count,legacy.SCHEMA,
              _json(source.counts),source.digest)
    keys=("manifest_sha","generation","expected_rows","source_schema",
          "counts_json","projection_sha")
    if generations:
        if (len(generations)!=1
                or tuple(generations[0][k] for k in keys)!=expected):
            raise MigrationGuard("Previously staged legacy source generation changed")
    else:
        _query(cloud,uid,GENERATION_SQL,expected)
    current,added=_next_stage(cloud,uid,source,today,run_id)
    if current<source.count:
        return {"status":"LEGACY_D1_PARTIAL_VERIFIED",
                "source_rows":source.count,"d1_staged_rows":current,
                "new_rows_this_run":added,"d1_database_name":LEGACY_DB,
                "market_value_writes":0,"owner_and_settlement_writes":0,
                "production_reads_switched":False}

    _verify_full(cloud,uid,source)
    _query(cloud,uid,ACTIVATE_SQL,(source.manifest_sha,source.manifest_sha,source.count))
    active=_query(cloud,uid,
                  "select manifest_sha from legacy_active_generation where singleton=1")
    if len(active)!=1 or active[0].get("manifest_sha")!=source.manifest_sha:
        raise MigrationGuard("Legacy D1 active generation did not commit")
    _verify_full(cloud,uid,source)
    return {"status":"LEGACY_FIVE_RELATIONS_D1_FULL_PARITY_VERIFIED",
            "source_rows":source.count,"d1_verified_rows":source.count,
            "r2_manifest_sha256":source.manifest_sha,
            "d1_projection_sha256":source.digest,
            "relations":dict(source.counts),"d1_database_name":LEGACY_DB,
            "market_value_writes":0,"owner_and_settlement_writes":0,
            "production_reads_switched":False,
            "supabase_writes":0,"r2_writes":0}


def main():
    try:
        result=run(os.getenv("CLOUDFLARE_ACCOUNT_ID",""),
                   os.getenv("CLOUDFARE_D1_PILOT_TOKEN",""),
                   os.getenv("GITHUB_RUN_ID",""),
                   os.getenv("GITHUB_RUN_ATTEMPT",""))
    except (MigrationGuard,PilotError,ValueError,httpx.HTTPError) as exc:
        print("Legacy R2-to-D1 typed import blocked safely: "+str(exc),file=sys.stderr)
        return 1
    Path(REPORT).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
