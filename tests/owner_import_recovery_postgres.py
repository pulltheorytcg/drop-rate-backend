"""Disposable real SQL and production handlers; synthetic records, no providers."""
import asyncio
import os
import asyncpg
from urllib.parse import urlsplit
from app.db import _init_connection, user_connection
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from app import imports, owner_auto_imports, owner_import_recovery
from catalogue_r2_cache_postgres import PGliteConnection
from owner_auto_import_postgres import SCHEMA
from import_preview_rebuild_postgres import csv_payload, corrected, collectr_payload

ROOT=Path(__file__).resolve().parents[1]

async def main():
    dsn=os.environ.get('OWNER_RECOVERY_TEST_DSN')
    pool=None
    if dsn:
        parsed=urlsplit(dsn)
        assert parsed.hostname in {'localhost','127.0.0.1'} and parsed.path=='/import_preview_rebuild_test'
        db=await asyncpg.connect(dsn)
        await _init_connection(db)
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        async def setup(conn): await conn.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=2,max_size=4,init=_init_connection,setup=setup)
    else:
        db=await PGliteConnection.open()
    try:
        await db.execute(SCHEMA)
        await db.execute('create schema auth; create table auth.users(id uuid primary key,email_confirmed_at timestamptz)')
        for migration in ('20261011154138_owner_incremental_import_intake.sql','20261002024856_unified_founder_app_access.sql','20261107220000_owner_import_preview_rebuild.sql'):
            await db.execute((ROOT/'database/migrations'/migration).read_text())
        await db.execute((ROOT/'database/migrations/20261107220000_owner_import_preview_rebuild.sql').read_text())
        audit=(ROOT/'database/migrations/202609230006_import_framework.sql').read_text()
        await db.execute('drop trigger candidate_audit on tcg.import_candidates')
        await db.execute(audit[audit.index('create function tcg.audit_import_candidate_change()'):audit.rindex('commit;')])
        owners=[uuid4(),uuid4()];actors=[uuid4(),uuid4()]
        for owner,actor in zip(owners,actors):
            await db.execute("insert into tcg.owners values($1,'Synthetic','CONSIGNOR',null,1000,true)",owner)
            await db.execute("insert into auth.users values($1,now())",actor)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",actor,owner)
        card=uuid4()
        await db.execute("""insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
            values($1,'synthetic','CARD','Pokemon','Known Card','Synthetic Set','001','Normal','C','English')""",card)
        @asynccontextmanager
        async def connection(_pool,actor,request_id,**kwargs):
            if pool:
                async with user_connection(pool,actor,request_id,**kwargs) as conn:
                    yield conn
                return
            async with db.transaction():
                await db.execute('set local role tcg_api')
                await db.execute("select set_config('tcg.user_id',$1,true)",str(actor))
                await db.execute("select set_config('tcg.request_id',$1,true)",request_id)
                yield db
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None,settings=SimpleNamespace(owner_import_preview_rebuild_enabled=True))),state=SimpleNamespace(request_id='synthetic-owner-recovery'))
        user=SimpleNamespace(user_id=actors[0]); other=SimpleNamespace(user_id=actors[1])
        async def rejected(call,status):
            try: await call
            except HTTPException as e: assert e.status_code==status,(e.status_code,e.detail)
            else: raise AssertionError(f'Expected {status}')
        async def snapshot(batch):
            return (await db.fetchrow('select * from tcg.import_batches where id=$1',batch),await db.fetch('select * from tcg.import_candidates where batch_id=$1 order by source_row',batch))
        with patch.object(imports,'user_connection',connection),patch.object(owner_auto_imports,'user_connection',connection),patch.object(owner_import_recovery,'user_connection',connection):
            source=csv_payload('seller-zero-copy')
            source=source.model_copy(update={'content': source.content.replace('Marker\n','Marker,Variant,Rarity\n').replace('seller-zero-copy\n','seller-zero-copy,Normal,C\n')})
            initial=await owner_auto_imports.upload_collection(source,request,user)
            batch=UUID(initial['batch_id']);version=initial['version']
            assert initial['created_count']==0 and initial['automatic_intake']
            before=await snapshot(batch)
            detail=await imports.get_import_batch(batch,request,user)
            assert detail['owner_rebuild_eligible'] and detail['owner_intake_summary']['added_units']==0
            payload=corrected(source,version)
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,payload,request,other),404)
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,corrected(source,version,content=source.content+'\n'),request,user),409)
            assert await snapshot(batch)==before
            await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actors[0])
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,payload,request,user),403)
            await db.execute('update tcg.owner_memberships set active=true where user_id=$1',actors[0])
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",actors[0],owners[1])
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,payload,request,user),409)
            await db.execute('delete from tcg.owner_memberships where user_id=$1 and owner_id=$2',actors[0],owners[1])
            request.app.state.settings.owner_import_preview_rebuild_enabled=False
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,payload,request,user),404)
            request.app.state.settings.owner_import_preview_rebuild_enabled=True
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,corrected(source,version,column_mapping={'name':'Missing header'}),request,user),422)
            assert await snapshot(batch)==before
            result=await owner_import_recovery.rebuild_owner_preview(batch,payload,request,user)
            assert result['created_count']==0 and result['ready_units']==3 and result['review_edits_reset']
            assert await db.fetchval('select count(*) from tcg.inventory_items')==0
            after=await snapshot(batch)
            assert after[0]['source_sha256']==before[0]['source_sha256'] and after[0]['automatic_intake']
            assert after[1][0]['raw_record']==before[1][0]['raw_record']
            assert after[1][0]['id']!=before[1][0]['id']
            assert await db.fetchval("select count(*) from tcg.audit_events where action='DELETE'")>0
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,payload,request,user),409)
            # A stale commit must never apply the newly interpreted candidates.
            await rejected(owner_auto_imports.add_recognised(batch,imports.ImportCommitRequest(version=version),request,user),409)
            applied=await owner_auto_imports.add_recognised(batch,imports.ImportCommitRequest(version=result['version']),request,user)
            assert applied['created_count']==3
            detail=await imports.get_import_batch(batch,request,user)
            assert not detail['owner_rebuild_eligible'] and detail['owner_intake_summary']['added_units']==3
            replay=await owner_auto_imports.upload_collection(source,request,user)
            assert replay['created_count']==0
            await rejected(owner_import_recovery.rebuild_owner_preview(batch,corrected(source,applied['version']),request,user),409)
            assert await db.fetchval('select count(*) from tcg.inventory_items')==3
            assert await db.fetchval("select count(*) from tcg.inventory_items where owner_id<>$1 or status<>'DRAFT' or sale_intent<>'PERSONAL_COLLECTION'",owners[0])==0
            assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.import_candidates','DELETE')")
            assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.import_batches','UPDATE')")
            if pool:
                # Two independent restricted sessions: only one revision may win.
                race_source=source.model_copy(update={'content':source.content.replace('seller-zero-copy','race')})
                race=await owner_auto_imports.upload_collection(race_source,request,user)
                race_id=UUID(race['batch_id']); race_payload=corrected(race_source,race['version'])
                outcomes=await asyncio.gather(*(owner_import_recovery.rebuild_owner_preview(race_id,race_payload,request,user) for _ in range(2)),return_exceptions=True)
                assert sum(isinstance(x,dict) for x in outcomes)==1
                assert sum(isinstance(x,HTTPException) and x.status_code==409 for x in outcomes)==1
                race_batch=await db.fetchrow('select * from tcg.import_batches where id=$1',race_id)
                racing=await asyncio.gather(
                    owner_import_recovery.rebuild_owner_preview(race_id,corrected(race_source,race_batch['version']),request,user),
                    owner_auto_imports.add_recognised(race_id,imports.ImportCommitRequest(version=race_batch['version']),request,user),return_exceptions=True)
                assert sum(isinstance(x,dict) for x in racing)==1
                assert sum(isinstance(x,HTTPException) and x.status_code==409 for x in racing)==1
                assert await db.fetchval('select count(*) from tcg.inventory_items where import_batch_id=$1',race_id) in (0,3)
                current=await db.fetchrow('select * from tcg.import_batches where id=$1',race_id)
                await owner_auto_imports.add_recognised(race_id,imports.ImportCommitRequest(version=current['version']),request,user)
                print('PASS: native PostgreSQL two-session rebuild/rebuild and commit/rebuild serialization')
            # A partially admitted PREVIEW is never a resettable zero-copy batch.
            partial_source=source.model_copy(update={'content':source.content.replace('Wrong Name','Known Card').replace(',,Synthetic Set',',Pokemon,Synthetic Set').replace('001,,','001,English,') + 'Unknown,Unknown,Pokemon,Synthetic Set,999,English,1,1,Near Mint,partial,Normal,C\n'})
            partial=await owner_auto_imports.upload_collection(partial_source,request,user)
            partial_id=UUID(partial['batch_id'])
            assert partial['created_count']>0 and partial['batch_status']=='PREVIEW'
            partial_before=await snapshot(partial_id)
            await rejected(owner_import_recovery.rebuild_owner_preview(partial_id,corrected(partial_source,partial['version']),request,user),409)
            assert await snapshot(partial_id)==partial_before
            from app.import_review import ImportCandidateSkipRequest
            pending=await db.fetchrow("select id from tcg.import_candidates where batch_id=$1 and status='REVIEW'",partial_id)
            await owner_auto_imports.skip_candidate(partial_id,pending['id'],ImportCandidateSkipRequest(version=partial['version']),request,user)
            # Correct the first Collectr snapshot, then prove +1 and decrease semantics.
            collectr=collectr_payload('seller-collectr',2,other=False)
            collectr=collectr.model_copy(update={'content':collectr.content.replace(',English,',',,'),'default_language':'Japanese'})
            first=await owner_auto_imports.upload_collection(collectr,request,user)
            assert first['created_count']==0
            cp=imports.ImportPreviewRebuildRequest(**{**collectr.model_dump(),'version':first['version'],'default_language':'English'})
            rebuilt=await owner_import_recovery.rebuild_owner_preview(UUID(first['batch_id']),cp,request,user)
            applied=await owner_auto_imports.add_recognised(UUID(first['batch_id']),imports.ImportCommitRequest(version=rebuilt['version']),request,user)
            assert applied['created_count']==2
            newer=collectr_payload('seller-collectr',3,other=False)
            newer=newer.model_copy(update={'content':newer.content.replace(',English,',',,'),'default_language':'English'})
            plus=await owner_auto_imports.upload_collection(newer,request,user)
            assert plus['created_count']==1
            assert (await owner_auto_imports.upload_collection(newer,request,user))['created_count']==0
            lower=newer.model_copy(update={'content':newer.content.replace(',3,Near Mint',',1,Near Mint')})
            decrease=await owner_auto_imports.upload_collection(lower,request,user)
            assert decrease['created_count']==0 and decrease['summary']['review_rows']>0
        print('PASS: zero-copy seller recovery, original source/audit retention, wrong/revoked owner denial, stale rebuild/commit rejection, explicit draft admission and duplicate prevention')
    finally:
        if pool:
            await pool.close()
            await db.execute('drop schema if exists tcg_private cascade; drop schema if exists tcg cascade; drop schema if exists auth cascade')
            for role in ('tcg_api','anon','authenticated'): await db.execute(f'drop role if exists {role}')
        await db.close()

if __name__=='__main__':asyncio.run(main())
