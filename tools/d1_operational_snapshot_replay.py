"""Version-aware immutable catch-up of EXISTING nine-table operational shadow.

Never writes PostgreSQL or financial authority. No in-place inventory update.
Prior generations and all original JSON/hashes remain available for rollback.
Full repeatable-read snapshots catch changes irrespective of timestamp windows;
per-item versions + source snapshot/capture time form the high-water mark.
This is NOT WAL CDC and does not migrate intervening historical audit events.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
from pathlib import Path

from d1_operational_source_stage import (
    ACCOUNT, DB_NAME, TABLES, ORDER, TARGETS, D1Client, StageGuard,
    _d1_query, _digest, _insert_rows, sha, source_capture, stage,
)
from d1_operational_source_delta_watch import compare_hashes, explain_changed_fields, SnapshotDriftGuard


DDL=Path('database/cloudflare_d1/0002_operational_shadow_replay.sql')
PRICING={'market_value_minor','latest_pricing_snapshot_id','recommended_retail_minor','pricing_updated_at'}
TIMESTAMPS={'updated_at'}
LEGITIMATE={'condition','language','location','grading_company','grade','certificate_number'}
PRESERVED={'id','inventory_code','owner_id','catalogue_id','store_price_minor','acquisition_cost_minor','currency','created_at'}


class MeasuredD1Client(D1Client):
    """Aggregate provider row metrics without retaining SQL/parameters/values."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.usage={'api_calls':0,'rows_read':0,'rows_written':0,'request_ms':0.0}
    def call(self,*args,**kwargs):
        result,elapsed=super().call(*args,**kwargs)
        self.usage['api_calls']+=1
        self.usage['request_ms']=round(self.usage['request_ms']+elapsed,3)
        for item in result if isinstance(result,list) else [result]:
            meta=item.get('meta',{}) if isinstance(item,dict) else {}
            for key in ('rows_read','rows_written'):
                value=meta.get(key,0)
                if type(value) is int and value>=0:self.usage[key]+=value
        return result,elapsed


def replay_schema():
    statements=[];buffer=''
    for line in DDL.read_text().splitlines(keepends=True):
        if line.lstrip().startswith('--'):continue
        buffer+=line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip());buffer=''
    expected={'ops_shadow_replay_checkpoints','ops_shadow_inventory_replay',
              'ops_shadow_replay_daily_budget','ops_shadow_replay_head'}
    names=[]
    for sql in statements:
        match=re.match(r'CREATE TABLE IF NOT EXISTS (ops_shadow_[a-z_]+) \(',sql)
        if not match:raise StageGuard('Unapproved replay schema statement')
        names.append(match[1])
    if buffer.strip() or set(names)!=expected or len(names)!=4:
        raise StageGuard('Unexpected additive replay migration')
    return statements


def instant(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError):
        raise StageGuard('Invalid source capture high-water mark') from None


def data_digest(captured,catalogue):
    return sha(''.join(t+':'+_digest(captured[t])+'\n' for t in TABLES)
               +'catalogue:'+sha(json.dumps(catalogue,sort_keys=True))+'\n')


def plan_inventory(source, prior, allowed):
    """Individual classifications stay private; public receipt contains counts."""
    drift=compare_hashes(source,prior)
    if drift['added_after_snapshot'] or drift['missing_in_source']:
        raise StageGuard('Inventory insert/delete requires expanded lineage review')
    # Performs JSON hash/identity/column validation before classification.
    explanation=explain_changed_fields(source,prior,allowed)
    previous={r['id']:r for r in prior}
    journal=[]
    for key,now,raw,digest in source:
        old=previous[key]
        if digest==old['source_row_sha256']:continue
        before=json.loads(old['source_row_json'])
        changed=sorted(k for k in set(now)|set(before)
            if ((k in now)!=(k in before)) or
               (k in now and k in before and json.dumps(now[k],sort_keys=True)!=json.dumps(before[k],sort_keys=True)))
        a,b=before.get('version'),now.get('version')
        if type(a) is not int or type(b) is not int or a<1 or b<a:
            raise StageGuard('Inventory version regression or invalid version')
        if set(changed)&PRESERVED:
            raise StageGuard('Protected ownership, cost, identity or Store Price changed')
        substantive=set(changed)-TIMESTAMPS-{'version'}
        if substantive and b<=a:
            raise StageGuard('Inventory content changed without version advance')
        if set(changed)-PRICING-TIMESTAMPS-LEGITIMATE-{'version'}:
            raise StageGuard('Unexplained inventory columns require review')
        if 'updated_at' in changed and instant(now['updated_at'])<instant(before['updated_at']):
            raise StageGuard('Inventory timestamp regression')
        classification=('SERIALIZATION_DISCREPANCY' if not changed else
            'PRICING_FIELD_UPDATE' if substantive and substantive<=PRICING else
            'LEGITIMATE_INVENTORY_UPDATE' if substantive else
            'TIMESTAMP_ONLY_CHANGE' if set(changed)<=TIMESTAMPS else
            'VERSION_INCREMENT')
        journal.append((key,old['source_row_sha256'],digest,a,b,classification,json.dumps(changed,separators=(',',':'))))
    if len(journal)!=drift['changed_after_snapshot']:
        raise StageGuard('Unclassified inventory differences')
    root=sha(''.join(f'{key}:{rec["version"]}\n' for key,rec,_,_ in sorted(source)))
    return journal,explanation,root


def db_scope(client):
    if client.account_id!=ACCOUNT:raise StageGuard('Wrong Cloudflare account')
    db=[r for r in client.list_databases() if r.get('name')==DB_NAME]
    if len(db)!=1:raise StageGuard('Existing private shadow required')
    return db[0]['uuid']


def replay(client,captured,schema,catalogue,metadata, *, apply=False):
    dbid=db_scope(client)
    stamp=instant(metadata.get('captured_at'))
    snapshot=metadata.get('source_snapshot')
    if not isinstance(snapshot,str) or not snapshot or len(snapshot)>10000:
        raise StageGuard('Consistent source snapshot marker required')
    # Require the complete nine-table baseline; ignore incomplete staged generations.
    generations=_d1_query(client,dbid,
        "SELECT g.generation_id,g.source_manifest_sha256,g.source_schema_sha256 FROM ops_shadow_generations g "
        "WHERE g.state IN ('STAGING','PARITY_VERIFIED') AND "
        "(SELECT COUNT(*) FROM ops_shadow_table_receipts r WHERE r.generation_id=g.generation_id)=9 "
        "ORDER BY g.created_at DESC,g.generation_id DESC LIMIT 1")
    if len(generations)!=1:raise StageGuard('Complete original shadow required')
    baseline=generations[0]
    digest=data_digest(captured,catalogue)
    generation='src-'+digest[:32]
    schema_digest=sha(json.dumps(schema,sort_keys=True,separators=(',',':')))
    if schema_digest!=baseline['source_schema_sha256']:
        raise StageGuard('Source schema changed since baseline')
    # These relations cannot change as a side effect of inventory-only replay.
    for name in ORDER:
        if name=='inventory_items':continue
        rows=_d1_query(client,dbid,f'SELECT id,source_row_sha256 FROM "{TARGETS[name][0]}" WHERE generation_id=? ORDER BY id',[baseline['generation_id']])
        if any(compare_hashes(captured[name],rows)[k] for k in ('added_after_snapshot','missing_in_source','changed_after_snapshot')):
            raise StageGuard('Non-inventory shadow drift requires independent reconciliation')
    links=_d1_query(client,dbid,'SELECT catalogue_id,reference_manifest_sha256 FROM ops_shadow_catalogue_links WHERE generation_id=?',[baseline['generation_id']])
    if {r['catalogue_id']:r['reference_manifest_sha256'] for r in links}!=catalogue:
        raise StageGuard('Canonical product links changed')
    prior=_d1_query(client,dbid,'SELECT id,source_row_sha256,source_row_json FROM ops_shadow_inventory WHERE generation_id=? ORDER BY id',[baseline['generation_id']])
    allowed={r['column'] for r in schema['inventory_items']}
    journal,explanation,version_root=plan_inventory(captured['inventory_items'],prior,allowed)
    plan_hash=sha(json.dumps(journal,separators=(',',':')))
    public={'status':'INVENTORY_REPLAY_DRY_RUN_VALIDATED','changed_records':len(journal),
        'classification_counts':dict(Counter(r[5] for r in journal)),
        'column_drift_diagnostics':explanation,'unexplained_differences':0,
        'generation_sha256':digest,'inventory_version_root':version_root,
        'source_postgres_writes':0,'financial_authority_changed':False,
        'production_reads_switched':False,'audit_history_fully_migrated':False,
        'payment_or_settlement_executed':False,'supabase_source_retired':False}
    if not apply:return public
    statements=replay_schema()
    for statement in statements:client.query(dbid,statement)
    head=_d1_query(client,dbid,'SELECT generation_id,captured_at FROM ops_shadow_replay_head WHERE singleton=1')
    if len(head)>1:raise StageGuard('Ambiguous replay head')
    if head and instant(head[0]['captured_at'])>stamp:
        raise StageGuard('Stale source snapshot cannot advance replay head')
    if head and head[0]['generation_id']==generation:
        public.update(status='INVENTORY_REPLAY_ALREADY_VERIFIED',changed_records=0,replay_idempotent=True)
        return public
    # Reserve one bounded new snapshot per UTC day, including all journal rows.
    total=sum(len(captured[t]) for t in ORDER)+len(catalogue)+len({r[1]['user_id'] for r in captured['owner_memberships']})+len(ORDER)+1+len(journal)+3
    if total>2500:raise StageGuard('Existing 2500-row replay budget exceeded')
    day=stamp.date().isoformat()
    existing=_d1_query(client,dbid,'SELECT generation_id,logical_rows_reserved,parent_generation_id,captured_at,source_snapshot FROM ops_shadow_replay_daily_budget WHERE utc_day=?',[day])
    if existing and (len(existing)!=1 or existing[0]['generation_id']!=generation or existing[0]['logical_rows_reserved']!=total):
        public.update(status='INVENTORY_REPLAY_DEFERRED_DAILY_BUDGET')
        return public
    if not existing:
        client.query(dbid,'INSERT INTO ops_shadow_replay_daily_budget(utc_day,generation_id,logical_rows_reserved,parent_generation_id,captured_at,source_snapshot) VALUES(?,?,?,?,?,?)',
            [day,generation,total,baseline['generation_id'],metadata['captured_at'],snapshot])
    else:
        if existing[0]['parent_generation_id']!=baseline['generation_id']:
            raise StageGuard('Replay parent differs from reserved checkpoint')
        metadata={**metadata,'captured_at':existing[0]['captured_at']}
        snapshot=existing[0]['source_snapshot']
    staged=stage(client,captured,schema,catalogue,captured_at=metadata['captured_at'],initial_state='REJECTED')
    if staged['generation_sha256']!=digest:raise StageGuard('Staged generation mismatch')
    _insert_rows(client,dbid,'ops_shadow_inventory_replay',
        ('generation_id','inventory_id','prior_sha256','source_sha256','prior_version','source_version','classification','changed_columns_json'),
        [(generation,*r) for r in journal]) if journal else None
    readback=_d1_query(client,dbid,'SELECT inventory_id,prior_sha256,source_sha256,prior_version,source_version,classification,changed_columns_json FROM ops_shadow_inventory_replay WHERE generation_id=? ORDER BY inventory_id',[generation])
    columns=('inventory_id','prior_sha256','source_sha256','prior_version','source_version','classification','changed_columns_json')
    if [tuple(r[k] for k in columns) for r in readback]!=sorted(journal):
        raise StageGuard('Replay journal differs from verified plan')
    _insert_rows(client,dbid,'ops_shadow_replay_checkpoints',
        ('generation_id','parent_generation_id','source_snapshot','captured_at','inventory_version_root','changed_records','plan_sha256'),
        [(generation,baseline['generation_id'],snapshot,metadata['captured_at'],version_root,len(journal),plan_hash)])
    checkpoint=_d1_query(client,dbid,'SELECT inventory_version_root,plan_sha256 FROM ops_shadow_replay_checkpoints WHERE generation_id=?',[generation])
    if checkpoint!=[{'inventory_version_root':version_root,'plan_sha256':plan_hash}]:
        raise StageGuard('Replay checkpoint verification failed')
    # D1 batch commits the head CAS and visibility state in one transaction.
    if head:
        head_sql='UPDATE ops_shadow_replay_head SET generation_id=?,captured_at=? WHERE singleton=1 AND generation_id=?'
        head_params=[generation,metadata['captured_at'],head[0]['generation_id']]
    else:
        head_sql='INSERT OR IGNORE INTO ops_shadow_replay_head(singleton,generation_id,captured_at) VALUES(1,?,?)'
        head_params=[generation,metadata['captured_at']]
    client.batch(dbid,[{'sql':head_sql,'params':head_params},
        {'sql':"UPDATE ops_shadow_generations SET state='PARITY_VERIFIED' WHERE generation_id=? AND EXISTS (SELECT 1 FROM ops_shadow_replay_head WHERE singleton=1 AND generation_id=?)",
         'params':[generation,generation]}])
    final=_d1_query(client,dbid,'SELECT generation_id,captured_at FROM ops_shadow_replay_head WHERE singleton=1')
    if final!=[{'generation_id':generation,'captured_at':metadata['captured_at']}]:
        raise StageGuard('Concurrent replay head advanced; checkpoint retained')
    public.update(status='INVENTORY_REPLAY_SNAPSHOT_PARITY_VERIFIED',logical_rows_reserved=total,
                  post_replay_snapshot_differences=0,replay_idempotent=True)
    return public


async def main(apply=False):
    metadata={}
    captured,schema,catalogue=await source_capture(os.environ.get('FULL_EXIT_PG_READONLY_DSN',''),snapshot_metadata=metadata)
    client=MeasuredD1Client(os.environ.get('CLOUDFLARE_ACCOUNT_ID',''),os.environ.get('CLOUDFARE_D1_PILOT_TOKEN',''))
    result=replay(client,captured,schema,catalogue,metadata,apply=apply)
    result['cloudflare_usage_this_run']=client.usage
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    try:print(json.dumps(asyncio.run(main(args.apply)),sort_keys=True))
    except Exception as exc:
        raise SystemExit('Private inventory catch-up blocked: '+type(exc).__name__) from None
