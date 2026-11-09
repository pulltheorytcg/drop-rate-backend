"""Resume R2-first sports/figures/Magic source references into ONE private D1.

Strictly no public catalogue route, owner inventory, monetary prices or
Shopify writes. A complete, verified Yu-Gi-Oh! D1 active pointer gates this
queue. One maximum 8,000-new-row receipt for the *whole* follow-on D1 per UTC
day, never in the UTC day Yu-Gi-Oh! finishes. Immutable scoped sources only.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

import httpx

from app import d1_shadow_catalogue as codec
from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import (
    SOURCE_PATH, _oidc_token, _query, _schema, load_verified_source,
    verify_d1_projection, MigrationGuard,
)
from d1_yugioh_shadow import _stable_source_projection, _verify_staged_prefix

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
YGO_DB = "drop-rate-d1-real-yugioh-shadow"
YGO_SCOPE = ("ygoprodeck", "YUGIOH", "English")
YGO_SOURCE_SHA = "e85fb49e5cf81427cec68b24749de5e273845f1b2245536e4879ded0e4b0a9dd"
YGO_EXPECTED = 45_418
DB_NAME = "drop-rate-d1-all-followon-catalogue-shadow"
DAILY_ROWS = 8_000
SAFETY_BYTES = 390_000_000
REPORT = "d1-followon-r2-shadow-report.json"
MAX_SOURCE_ATTEMPTS = 30


@dataclass(frozen=True)
class Source:
    code: str
    scope: tuple[str, str, str]
    expected_rows: int
    manifest_sha: str
    max_bytes: int
    max_parts: int


SOURCES = (
    Source("sports", ("cardcollectorcapital", "SPORTS_CARDS", "English"),
           1722, "025043fb2594a98f18c070ecbdcdfa682b25a3447839ebca1cdfb84d33bdae1f",
           3_000_000, 20),
    Source("sports-heritage",
           ("cardcollectorcapital_heritage", "SPORTS_CARDS", "English"),
           100, "94f4c7af3097b439dafc2826d613e78fe2e6569f757ee11078bdda8123484146",
           200_000, 10),
    Source("figures", ("reviewed_figures", "FIGURES", "Not applicable"),
           4, "8bafa9e80735482c62dbb201ad26c21fa6c157c941d4e5c6edfc81a09f092d72",
           20_000, 10),
    Source("magic", ("mtgjson", "MAGIC_THE_GATHERING", "English"),
           153662, "be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28",
           110_000_000, 512),
)

BUDGET_SCHEMA = """create table if not exists followon_daily_budget (
    utc_day text primary key,
    source_code text not null,
    manifest_sha text not null references shadow_generations(manifest_sha),
    rows_budget integer not null check(rows_budget between 1 and 8000),
    github_run_id text not null
)"""

BUDGET_INSERT = """insert into followon_daily_budget
(utc_day,source_code,manifest_sha,rows_budget,github_run_id)
values(?,?,?,?,?)"""

KNOWN_SCHEMA = {
    "shadow_generations", "shadow_cards", "shadow_active_partitions",
    "followon_daily_budget",
}


def _day(now: datetime | None) -> str:
    value=(now or datetime.now(timezone.utc))
    if value.tzinfo is None:
        raise MigrationGuard("Missing UTC timestamp")
    return value.astimezone(timezone.utc).date().isoformat()


def _database_identity(rec: dict) -> str:
    uid=rec.get("uuid")
    if not isinstance(uid,str) or not re.fullmatch(
            r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}",uid):
        raise MigrationGuard("D1 database identity failed validation")
    return uid


def _listed(cloud: D1Client):
    listed=cloud.list_databases()
    if not isinstance(listed,list) or len(listed)>10:
        raise MigrationGuard("D1 account exceeds Free-tier database limit")
    names=[x.get("name") for x in listed]
    if any(type(n) is not str or not n for n in names) or len(names)!=len(set(names)):
        raise MigrationGuard("Ambiguous D1 account database names")
    return {x["name"]:_database_identity(x) for x in listed}


def _yugioh_source_gate(cloud: D1Client, databases: dict[str,str]):
    """Read the verified active generation; never assume source count is static.

    A newer, larger retained generation keeps follow-on imports blocked until
    its full D1 projection is activated by the Yu-Gi-Oh source importer.
    The pinned minimum is a floor, never a substitute for current parity.
    """
    ident=databases.get(YGO_DB)
    if ident is None:
        return {"ready":False,"count":0,"source_rows":YGO_EXPECTED,
                "reason":"YGO_D1_NOT_PRESENT"}
    generations=_query(cloud,ident,
        "select manifest_sha,expected_rows,projection_sha from shadow_generations "
        "where provider=? and system_code=? and language=?",YGO_SCOPE)
    if not generations:
        return {"ready":False,"count":0,"source_rows":YGO_EXPECTED,
                "reason":"YGO_D1_SOURCE_NOT_STAGED"}
    if len(generations)>2:
        raise MigrationGuard("Ambiguous retained Yu-Gi-Oh generations")
    for row in generations:
        if (not isinstance(row.get("manifest_sha"),str)
                or not re.fullmatch(r"[0-9a-f]{64}",row["manifest_sha"])
                or type(row.get("expected_rows")) is not int
                or not YGO_EXPECTED<=row["expected_rows"]<=50_000
                or not isinstance(row.get("projection_sha"),str)
                or not re.fullmatch(r"[0-9a-f]{64}",row["projection_sha"])):
            raise MigrationGuard("Invalid Yu-Gi-Oh D1 generation metadata")
    ordered=sorted(generations,key=lambda r:r["expected_rows"])
    if len(ordered)>1 and ordered[-1]["expected_rows"]==ordered[-2]["expected_rows"]:
        raise MigrationGuard("Ambiguous same-size Yu-Gi-Oh source generations")
    target=ordered[-1]
    count_rows=_query(cloud,ident,
        "select count(*) as n from shadow_cards where manifest_sha=?",
        (target["manifest_sha"],))
    if len(count_rows)!=1 or type(count_rows[0].get("n")) is not int:
        raise MigrationGuard("YGO D1 staging state unavailable")
    count=count_rows[0]["n"]
    expected=target["expected_rows"]
    if not 0<=count<=expected:
        raise MigrationGuard("YGO staging count exceeds selected R2 source")
    active=_query(cloud,ident,
        "select manifest_sha from shadow_active_partitions "
        "where provider=? and system_code=? and language=?",YGO_SCOPE)
    if len(active)>1:
        raise MigrationGuard("Duplicate Yu-Gi-Oh active pointers")
    if active:
        active_sha=active[0].get("manifest_sha")
        active_meta=[r for r in generations if r["manifest_sha"]==active_sha]
        if len(active_meta)!=1:
            raise MigrationGuard("Unknown Yu-Gi-Oh active pointer")
        check=_query(cloud,ident,
            "select count(*) as n from shadow_cards where manifest_sha=?",
            (active_sha,))
        if len(check)!=1 or check[0].get("n")!=active_meta[0]["expected_rows"]:
            raise MigrationGuard("YGO active pointer is inconsistent")
    ready=(len(active)==1 and active[0]["manifest_sha"]==target["manifest_sha"]
           and count==expected)
    if not ready:
        return {"ready":False,"count":count,"source_rows":expected,
                "reason":"YGO_NEWER_GENERATION_PENDING" if active else "YGO_FULL_PARITY_NOT_COMPLETE"}
    return {"ready":True,"count":count,"source_rows":expected,
            "reason":"YGO_FULL_PARITY_VERIFIED"}


def _gate_yugioh(cloud: D1Client, databases: dict[str,str], today: str):
    source=_yugioh_source_gate(cloud,databases)
    if not source["ready"]:
        return source
    ident=databases[YGO_DB]
    latest=_query(cloud,ident,"select max(utc_day) as day from shadow_daily_write_budget")
    if len(latest)!=1:
        raise MigrationGuard("YGO prior daily write receipts unavailable")
    if latest[0].get("day")==today:
        return {**source,"ready":False,"reason":"YGO_WROTE_TODAY"}
    return {**source,"reason":"YGO_COMPLETE_PREVIOUS_DAY"}


def _get_shadow(cloud: D1Client, databases: dict[str,str]):
    existing=databases.get(DB_NAME)
    if existing:
        _check_private_tables(cloud,existing)
        return existing
    # Reserve one free database slot for a future audited operational ledger.
    if len(databases)>=9:
        raise MigrationGuard("D1 database slots are too scarce for next shadow")
    response,_=cloud.call("POST",cloud.path,{"name":DB_NAME})
    if not isinstance(response,dict) or response.get("name")!=DB_NAME:
        raise MigrationGuard("Cloudflare did not create exact private shadow database")
    return _database_identity(response)


def _check_private_tables(cloud: D1Client, dbid: str):
    tables=_query(cloud,dbid,
                  "select name from sqlite_master where type='table'")
    names={x.get("name") for x in tables}
    if not names <= KNOWN_SCHEMA:
        raise MigrationGuard("Unexpected existing D1 tables; refusing mutation")


def _disk_used(cloud: D1Client, dbid: str):
    """Use Cloudflare's supported GET D1 database detail file_size.

    Some SQLite pragmas such as page_count are rejected by D1 REST HTTP 400.
    Never interpret a failed SQL pragma as evidence of available disk.
    """
    detail,_=cloud.call("GET",f"{cloud.path}/{dbid}")
    if (not isinstance(detail,dict) or detail.get("uuid")!=dbid
            or type(detail.get("file_size")) is not int
            or detail["file_size"]<0):
        raise MigrationGuard("D1 database file_size not proven by Cloudflare")
    used=detail["file_size"]
    if used>=SAFETY_BYTES:
        raise MigrationGuard("D1 database nearing Free single-file storage ceiling")
    return used


def _source_active(cloud: D1Client, dbid: str, source: Source):
    rows=_query(cloud,dbid,
                "select manifest_sha from shadow_active_partitions "
                "where provider=? and system_code=? and language=?",source.scope)
    if len(rows)>1:
        raise MigrationGuard("Duplicate D1 source publication pointer")
    if not rows:
        return False
    if rows[0].get("manifest_sha")!=source.manifest_sha:
        raise MigrationGuard("Unexpected D1 active R2 generation")
    count=_query(cloud,dbid,
                 "select count(*) as n from shadow_cards where manifest_sha=?",
                 (source.manifest_sha,))
    if len(count)!=1 or count[0].get("n")!=source.expected_rows:
        raise MigrationGuard("Active source D1 count differs from original R2")
    return True


def _fetch_verified_source(source: Source, http: httpx.Client):
    namespace=SOURCE_PATH+"/followon/"+source.code
    for attempt in range(MAX_SOURCE_ATTEMPTS):
        token=_oidc_token()
        try:
            projection,manifest=load_verified_source(
                http,token,source_path=namespace,allowed_scope=source.scope,
                min_rows=source.expected_rows,max_rows=source.expected_rows,
                max_bytes=source.max_bytes,max_parts=source.max_parts,
            )
            break
        except MigrationGuard as exc:
            if (str(exc) not in ("R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503")
                    or attempt==MAX_SOURCE_ATTEMPTS-1):
                raise
            time.sleep(10)
    if (projection.manifest_sha!=source.manifest_sha
            or projection.scope!=source.scope
            or projection.expected_rows!=source.expected_rows):
        raise MigrationGuard("Follow-on source did not match immutable registry")
    return _stable_source_projection(projection)


def _generation(cloud: D1Client, dbid: str, source: Source, proj):
    rows=_query(cloud,dbid,
                "select manifest_sha,provider,system_code,language,expected_rows,"
                "projection_sha,source_content_sha,source_revision "
                "from shadow_generations where provider=? and system_code=? "
                "and language=?",source.scope)
    if len(rows)>1:
        raise MigrationGuard("Multiple unreviewed generation snapshots")
    expected=(proj.manifest_sha,*proj.scope,proj.expected_rows,
              proj.projection_sha,proj.source_content_sha,proj.source_revision)
    cols=("manifest_sha","provider","system_code","language","expected_rows",
          "projection_sha","source_content_sha","source_revision")
    if rows:
        if tuple(rows[0][col] for col in cols)!=expected:
            raise MigrationGuard("Staged generation metadata differs from R2")
    else:
        statement=codec.generation_statement(proj)
        _query(cloud,dbid,statement["sql"],statement["params"])


def _stage_day(cloud: D1Client, dbid: str, source: Source, proj,
               today: str, run_id: str):
    # Check every previously written D1 row against original verified R2
    # before writing any new stage rows, including across GitHub reruns.
    before=_verify_staged_prefix(cloud,dbid,proj)
    if before>=source.expected_rows:
        return before,0
    prior=_query(cloud,dbid,"select utc_day,source_code,manifest_sha "
                 "from followon_daily_budget where utc_day=?",(today,))
    if len(prior)>1:
        raise MigrationGuard("Duplicate account-wide follow-on budget receipt")
    if prior:
        if (prior[0]["source_code"]!=source.code
                or prior[0]["manifest_sha"]!=proj.manifest_sha):
            raise MigrationGuard("Another follow-on partition used today's allowance")
        return before,0
    limit=min(DAILY_ROWS,source.expected_rows-before)
    _query(cloud,dbid,BUDGET_INSERT,
           (today,source.code,proj.manifest_sha,limit,run_id))
    subset=replace(proj,rows=proj.rows[before:before+limit],expected_rows=limit)
    statements=list(codec.insert_statements(subset))
    for start in range(0,len(statements),codec.MAX_BATCH_STATEMENTS):
        cloud.batch(dbid,statements[start:start+codec.MAX_BATCH_STATEMENTS])
    after=_verify_staged_prefix(cloud,dbid,proj)
    if after!=before+limit:
        raise MigrationGuard("D1 staged row count mismatches bounded receipt")
    return after,limit


def _activate(cloud: D1Client, dbid: str, source: Source, proj):
    if verify_d1_projection(cloud,dbid,proj)!=source.expected_rows:
        raise MigrationGuard("Whole source D1 SHA256 parity not met")
    statement=codec.activation_statement(proj)
    _query(cloud,dbid,statement["sql"],statement["params"])
    if not _source_active(cloud,dbid,source):
        raise MigrationGuard("Full R2 partition not active after D1 transaction")
    if verify_d1_projection(cloud,dbid,proj)!=source.expected_rows:
        raise MigrationGuard("Active source D1 SHA256 differs from original R2")


def run(account: str, token: str, run_id: str, attempt: str, *,
        http: httpx.Client|None=None,now: datetime|None=None):
    if account!=ACCOUNT or not re.fullmatch(r"[0-9]{1,20}",run_id) or not re.fullmatch(
            r"[0-9]{1,4}",attempt):
        raise MigrationGuard("Only approved GitHub Actions run may stage source")
    if http is None:
        with httpx.Client(follow_redirects=False,timeout=httpx.Timeout(25)) as client:
            return run(account,token,run_id,attempt,http=client,now=now)
    today=_day(now)
    cloud=D1Client(account,token)
    databases=_listed(cloud)
    gate=_gate_yugioh(cloud,databases,today)
    if not gate["ready"]:
        return {
            "status":"FOLLOWON_WAITING_FOR_YUGIOH_OR_DAILY_WINDOW",
            "reason":gate["reason"],"yugioh_staged_rows":gate["count"],
            "yugioh_source_rows":gate["source_rows"],
            "d1_writes":0,"production_reads_switched":False,
            "owner_and_settlement_writes":0,"market_value_writes":0,
        }
    dbid=databases.get(DB_NAME)
    if dbid:
        _check_private_tables(cloud,dbid)
        _disk_used(cloud,dbid)
        # read-only inspection of existing progress before source fetch
        active={source.code:_source_active(cloud,dbid,source) for source in SOURCES}
        if all(active.values()):
            return {"status":"ALL_FOLLOWON_R2_FIRST_SOURCES_VERIFIED",
                    "source_rows":sum(s.expected_rows for s in SOURCES),
                    "verified_d1_rows":sum(s.expected_rows for s in SOURCES),
                    "d1_database_name":DB_NAME,
                    "production_reads_switched":False,
                    "owner_and_settlement_writes":0,"market_value_writes":0}
        source=next(s for s in SOURCES if not active[s.code])
    else:
        source=SOURCES[0]
    proj=_fetch_verified_source(source,http)
    dbid=_get_shadow(cloud,databases)
    _schema(cloud,dbid)
    _query(cloud,dbid,BUDGET_SCHEMA)
    _disk_used(cloud,dbid)
    _generation(cloud,dbid,source,proj)
    count,added=_stage_day(cloud,dbid,source,proj,today,run_id)
    if count==source.expected_rows:
        _activate(cloud,dbid,source,proj)
        state="FOLLOWON_R2_PARTITION_FULLY_VERIFIED"
    else:
        state="FOLLOWON_R2_PARTITION_PARTIAL_STAGED"
    return {
        "status":state,"source":source.code,
        "source_rows":source.expected_rows,"d1_staged_rows":count,
        "new_rows_this_run":added,
        "d1_database_name":DB_NAME,"r2_source_manifest_sha":proj.manifest_sha,
        "d1_projection_sha":proj.projection_sha if count==source.expected_rows else None,
        "production_reads_switched":False,
        "owner_and_settlement_writes":0,"market_value_writes":0,
        "supabase_writes":0,"r2_writes":0,
    }


def main() -> int:
    try:
        result=run(
            os.getenv("CLOUDFLARE_ACCOUNT_ID",""),
            os.getenv("CLOUDFARE_D1_PILOT_TOKEN",""),
            os.getenv("GITHUB_RUN_ID",""),
            os.getenv("GITHUB_RUN_ATTEMPT",""),
        )
    except (PilotError,MigrationGuard,ValueError,httpx.HTTPError) as exc:
        print("Follow-on full catalogue D1 staging safely blocked: "+str(exc))
        return 1
    Path(REPORT).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
