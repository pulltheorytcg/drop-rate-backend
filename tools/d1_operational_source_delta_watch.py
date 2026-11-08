"""Read-only proof that Drop Rate's private operational D1 snapshot is current.

This is NOT change-data capture or a settlement engine. Every run reads one
Postgres read-only repeatable-read snapshot using existing protected GitHub
secret, compares ORIGINAL record SHA256 with an immutable D1 generation, and
fails closed if the two have drifted. No owner names, IDs, prices, object keys
or PostgreSQL/D1 credentials are ever printed. No database or R2 writes.
"""
from __future__ import annotations

import argparse
import hashlib
import asyncio
from collections import defaultdict
import json
import os
import re

from d1_operational_source_stage import (
    ACCOUNT, DB_NAME, ORDER, TARGETS, D1Client, source_capture,
    StageGuard, _d1_query,
)

UUID_RE=re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
SHA_RE=re.compile(r"[0-9a-f]{64}\Z")


class SnapshotDriftGuard(ValueError):
    pass


def compare_hashes(source,remote) -> dict:
    """Compare individual original IDs/hashes without exposing source values."""
    if not isinstance(source,list) or not isinstance(remote,list):
        raise SnapshotDriftGuard("Invalid private source or D1 shadow records")
    live={}
    for item in source:
        if not isinstance(item,tuple) or len(item)!=4:
            raise SnapshotDriftGuard("Unknown canonical source row shape")
        key,_,_,digest=item
        if not isinstance(key,str) or not key or not isinstance(digest,str) or not SHA_RE.fullmatch(digest):
            raise SnapshotDriftGuard("Invalid original source identity/hash")
        if key in live:
            raise SnapshotDriftGuard("Duplicate private source identity")
        live[key]=digest
    prior={}
    for item in remote:
        if not isinstance(item,dict):
            raise SnapshotDriftGuard("Unknown D1 row shape")
        key,digest=item.get("id"),item.get("source_row_sha256")
        if not isinstance(key,str) or not key or not isinstance(digest,str) or not SHA_RE.fullmatch(digest):
            raise SnapshotDriftGuard("Invalid D1 source hash")
        if key in prior:
            raise SnapshotDriftGuard("Duplicate D1 shadow identity")
        prior[key]=digest
    return {
        "source_now":len(live),
        "d1_generation":len(prior),
        "added_after_snapshot":len(live.keys()-prior.keys()),
        "missing_in_source":len(prior.keys()-live.keys()),
        "changed_after_snapshot":sum(live[x]!=prior[x] for x in live.keys()&prior.keys()),
    }


def explain_changed_fields(source, remote, allowed_columns):
    """Validate private original JSON, then emit only approved column counts.

    Hash differences remain blocking even when caused only by serialization.
    Missing/null and JSON number/string differences must not disappear.
    """
    compare_hashes(source, remote)
    current={row[0]:row for row in source}
    counts=defaultdict(int)
    changed=0
    serialization_only=0
    missing=object()
    for row in remote:
        key=row['id']
        if key not in current or current[key][3]==row['source_row_sha256']:
            continue
        _,body,raw,digest=current[key]
        prior_raw=row.get('source_row_json')
        if (not isinstance(raw,str) or not isinstance(prior_raw,str)
                or len(raw)>1_000_000 or len(prior_raw)>1_000_000
                or hashlib.sha256(raw.encode()).hexdigest()!=digest
                or hashlib.sha256(prior_raw.encode()).hexdigest()!=row['source_row_sha256']):
            raise SnapshotDriftGuard('Private source payload hash mismatch')
        try:
            now=json.loads(raw)
            prior=json.loads(prior_raw)
        except (ValueError,TypeError):
            raise SnapshotDriftGuard('Invalid private source JSON') from None
        if (not isinstance(now,dict) or not isinstance(prior,dict)
                or now!=body or now.get('id')!=key or prior.get('id')!=key):
            raise SnapshotDriftGuard('Private payload identity mismatch')
        fields=set(now)|set(prior)
        if not fields.issubset(allowed_columns):
            raise SnapshotDriftGuard('Unapproved source columns')
        changed+=1
        differences=0
        for field in fields:
            a,b=now.get(field,missing),prior.get(field,missing)
            different=(a is missing)!=(b is missing)
            if a is not missing and b is not missing:
                different=json.dumps(a,sort_keys=True)!=json.dumps(b,sort_keys=True)
            if different:
                counts[field]+=1
                differences+=1
        if differences==0:
            serialization_only+=1
    return {'changed_records_examined':changed,
            'changed_field_counts':dict(sorted(counts.items())),
            'serialization_only_records':serialization_only}


def verify_shadow(client,captured,catalogue, *, explain_drift=False, source_schema=None) -> dict:
    if client.account_id!=ACCOUNT:
        raise SnapshotDriftGuard("Unexpected Cloudflare account")
    databases=[x for x in client.list_databases() if x.get("name")==DB_NAME]
    if len(databases)!=1 or not UUID_RE.fullmatch(databases[0].get("uuid","")):
        raise SnapshotDriftGuard("Unique operational D1 shadow not found")
    dbid=databases[0]["uuid"]
    generations=_d1_query(client,dbid,
        "SELECT g.generation_id,g.state,g.source_manifest_sha256 FROM ops_shadow_generations g "
        "WHERE g.state IN ('STAGING','PARITY_VERIFIED') AND "
        "(SELECT COUNT(*) FROM ops_shadow_table_receipts r WHERE r.generation_id=g.generation_id)=9 "
        "ORDER BY g.created_at DESC,g.generation_id DESC LIMIT 2")
    if not generations:
        raise SnapshotDriftGuard("No private operational generation has been staged")
    gen=generations[0]
    if (gen.get("state") not in {"STAGING","PARITY_VERIFIED"}
            or not isinstance(gen.get("generation_id"),str)
            or not SHA_RE.fullmatch(gen.get("source_manifest_sha256",""))):
        raise SnapshotDriftGuard("Unexpected source generation state")
    generation=gen["generation_id"]
    changes={}
    explanations={}
    for source_name in ORDER:
        target=TARGETS[source_name][0]
        rows=_d1_query(client,dbid,
            f'SELECT id,source_row_sha256 FROM "{target}" '
            "WHERE generation_id=? ORDER BY id",[generation])
        changes[source_name]=compare_hashes(captured[source_name],rows)
        if explain_drift and changes[source_name]['changed_after_snapshot']:
            if not source_schema or source_name not in source_schema:
                raise SnapshotDriftGuard('Source column schema required for diagnostics')
            allowed={x['column'] for x in source_schema[source_name]}
            if any(not isinstance(x,str) or not re.fullmatch(r'[a-z_][a-z0-9_]*',x) for x in allowed):
                raise SnapshotDriftGuard('Invalid source column schema')
            # Same immutable generation, SELECT only; never publish values.
            private_rows=_d1_query(client,dbid,
                f'SELECT id,source_row_sha256,source_row_json FROM "{target}" '
                "WHERE generation_id=? ORDER BY id",[generation])
            compare_hashes(captured[source_name],private_rows)
            if {r['id']:r['source_row_sha256'] for r in private_rows}!={r['id']:r['source_row_sha256'] for r in rows}:
                raise SnapshotDriftGuard('Shadow changed during diagnostic read')
            explanations[source_name]=explain_changed_fields(captured[source_name],private_rows,allowed)

    references=_d1_query(client,dbid,
        "SELECT catalogue_id,reference_manifest_sha256 FROM ops_shadow_catalogue_links "
        "WHERE generation_id=? ORDER BY catalogue_id",[generation])
    remote_catalogue={}
    for row in references:
        key,digest=row.get("catalogue_id"),row.get("reference_manifest_sha256")
        if not isinstance(key,str) or key in remote_catalogue or not isinstance(digest,str):
            raise SnapshotDriftGuard("Unknown D1 canonical catalogue link")
        remote_catalogue[key]=digest
    catalogue_changes={
        "added_after_snapshot":len(catalogue.keys()-remote_catalogue.keys()),
        "missing_in_source":len(remote_catalogue.keys()-catalogue.keys()),
        "changed_after_snapshot":sum(catalogue[k]!=remote_catalogue[k]
            for k in catalogue.keys()&remote_catalogue.keys()),
    }
    mismatches=sum(
        row["added_after_snapshot"]+row["missing_in_source"]
        +row["changed_after_snapshot"] for row in changes.values()
    )+sum(catalogue_changes.values())
    # No ledger value is printed, and no claim that this snapshot supports
    # live settlement. Any changed ledger ID or amount changes its source SHA.
    return {
        "status":("READ_ONLY_OPERATIONAL_D1_SNAPSHOT_PARITY"
                  if mismatches==0 else "READ_ONLY_OPERATIONAL_D1_SNAPSHOT_STALE"),
        "verified_original_tables":len(ORDER),
        "source_drift":changes,
        "column_drift_diagnostics":explanations,
        "catalogue_link_drift":catalogue_changes,
        "changed_or_missing_record_count":mismatches,
        "source_postgres_writes":0,
        "shadow_d1_writes":0,
        "source_r2_writes":0,
        "production_reads_switched":False,
        "safely_authorizes_cutover":False,
        "replays_changes":False,
    }


async def main(*, explain_drift=False):
    dsn=os.getenv("FULL_EXIT_PG_READONLY_DSN","").strip()
    account=os.getenv("CLOUDFLARE_ACCOUNT_ID","").strip()
    token=os.getenv("CLOUDFARE_D1_PILOT_TOKEN","").strip()
    if not dsn or account!=ACCOUNT or not token:
        raise SnapshotDriftGuard("Protected connection configuration missing")
    snapshot,schema,catalogue=await source_capture(dsn)
    result=verify_shadow(D1Client(account,token),snapshot,catalogue,
                         explain_drift=explain_drift,source_schema=schema)
    return result


if __name__=="__main__":
    try:
        parser=argparse.ArgumentParser()
        parser.add_argument('--explain-drift',action='store_true')
        args=parser.parse_args()
        result=asyncio.run(main(explain_drift=args.explain_drift))
        print(json.dumps(result,sort_keys=True,separators=(",",":")))
        if result["changed_or_missing_record_count"]:
            raise SystemExit(2)
    except (StageGuard,SnapshotDriftGuard) as exc:
        raise SystemExit("D1 source parity cannot be established: "+type(exc).__name__) from None
    except Exception as exc:
        raise SystemExit("D1 source parity unavailable: "+type(exc).__name__) from None
