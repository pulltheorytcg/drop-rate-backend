"""Real handlers + disposable PostgreSQL/RLS. No Shopify, production JWT or orders.

The fixture mirrors the relevant live grants, ownership policies and import
constraints. It is not a replay of the complete production migration history.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException

from app import imports, owner_auto_imports as api
from app.db import _init_connection, user_connection
from app.import_review import ImportCandidateSkipRequest

ROOT=Path(__file__).resolve().parents[1]

SCHEMA="""
create schema tcg;
create role tcg_api nologin nosuperuser nobypassrls;
create role anon nologin;create role authenticated nologin;
create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot int,commission_bps int,active bool default true);
create table tcg.owner_memberships(id uuid default gen_random_uuid() primary key,user_id uuid,owner_id uuid references tcg.owners,role text,active bool default true,created_at timestamptz default now());
create function tcg.is_platform_admin() returns boolean language sql stable as $$select exists(select 1 from tcg.owner_memberships where user_id=tcg.current_user_id() and active and role='PLATFORM_ADMIN')$$;
create table tcg.catalogue_products(id uuid primary key,identity_key text unique,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text,created_at timestamptz default now());
create table tcg.import_batches(id uuid default gen_random_uuid() primary key,owner_id uuid references tcg.owners,source text not null check(btrim(source)<>''),source_sha256 text,source_rows int check(source_rows>0),physical_units int check(physical_units>0),created_at timestamptz default now(),filename text,adapter text default 'LEGACY' check(adapter in('LEGACY','COLLECTR','EBAY_PURCHASES','HOLODEX','GENERIC_CSV')),status text default 'COMMITTED' check(status in('PREVIEW','COMMITTED','CANCELLED')),warnings jsonb default '[]',version int default 1 check(version>=1),committed_at timestamptz,unique(owner_id,source_sha256));
create table tcg.import_candidates(id uuid default gen_random_uuid() primary key,batch_id uuid references tcg.import_batches,owner_id uuid references tcg.owners,source_row int check(source_row>0),quantity int default 1 check(quantity>0 and quantity<=1000),raw_record jsonb,normalized_record jsonb,catalogue_id uuid references tcg.catalogue_products,status text check(status in('READY','REVIEW','COMMITTED','SKIPPED')),issues jsonb default '[]',created_at timestamptz default now(),unique(batch_id,source_row));
create table tcg.inventory_items(id uuid primary key,inventory_code text unique,catalogue_id uuid references tcg.catalogue_products,owner_id uuid references tcg.owners,acquisition_cost_minor bigint,currency text,condition text,seal_status text,grading_company text,grade text,certificate_number text,language text,identity_confirmed bool,status text,notes text,import_batch_id uuid references tcg.import_batches,source_row int,source_copy int,source_record jsonb,unique(import_batch_id,source_row,source_copy));
create table tcg.import_enrichment_items(batch_id uuid,owner_id uuid,overall_status text);
create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
create table tcg.fixture_committed_events(batch_id uuid,version int,unique(batch_id,version));
create function tcg.fixture_audit() returns trigger language plpgsql security definer set search_path=pg_catalog as $$begin insert into tcg.audit_events values(nullif(current_setting('tcg.user_id',true),''),nullif(current_setting('tcg.request_id',true),''),TG_OP,TG_TABLE_NAME,new.id,case when TG_OP='INSERT' then null else to_jsonb(old) end,to_jsonb(new));return new;end$$;
create function tcg.fixture_committed_event() returns trigger language plpgsql security definer set search_path=pg_catalog as $$begin if new.status='COMMITTED' and (TG_OP='INSERT' or old.status<>'COMMITTED') then insert into tcg.fixture_committed_events values(new.id,new.version);end if;return new;end$$;
create trigger batch_audit after insert or update on tcg.import_batches for each row execute function tcg.fixture_audit();
create trigger candidate_audit after insert or update on tcg.import_candidates for each row execute function tcg.fixture_audit();
create trigger inventory_audit after insert on tcg.inventory_items for each row execute function tcg.fixture_audit();
create trigger commit_event after insert or update on tcg.import_batches for each row execute function tcg.fixture_committed_event();
grant usage on schema tcg to tcg_api;
grant select on tcg.owners,tcg.owner_memberships,tcg.catalogue_products,tcg.import_batches,tcg.import_candidates,tcg.inventory_items,tcg.import_enrichment_items to tcg_api;
grant insert on tcg.import_batches,tcg.import_candidates,tcg.inventory_items to tcg_api;
grant update on tcg.import_candidates to tcg_api;
alter table tcg.owner_memberships enable row level security;
create policy own_membership on tcg.owner_memberships for select to tcg_api using(user_id=tcg.current_user_id() and active);
alter table tcg.owners enable row level security;alter table tcg.owners force row level security;
create policy owner_read on tcg.owners for select to tcg_api using(active and (tcg.is_platform_admin() or exists(select 1 from tcg.owner_memberships m where m.owner_id=owners.id and m.user_id=tcg.current_user_id() and m.active)));
alter table tcg.import_batches enable row level security;alter table tcg.import_batches force row level security;
create policy own_records on tcg.import_batches to tcg_api using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));
alter table tcg.import_candidates enable row level security;
create policy own_records on tcg.import_candidates to tcg_api using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));
alter table tcg.inventory_items enable row level security;alter table tcg.inventory_items force row level security;
create policy own_records on tcg.inventory_items to tcg_api using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));
alter table tcg.import_enrichment_items enable row level security;
create policy own_records on tcg.import_enrichment_items to tcg_api using(owner_id in(select id from tcg.owners));
"""


def payload(quantity=2, *, review=True, suffix=''):
    text='Portfolio Name,Category,Product Name,Set,Card Number,Rarity,Variance,Quantity,Card Condition,Language,Grade,Average Cost Paid,Confidence\n'
    text+=f'Mine,Pokemon,Known Card,Synthetic Set,001,C,Normal,{quantity},Near Mint,English,Ungraded,,100\n'
    if review:
        text+='Mine,Pokemon,Needs Review,Synthetic Set,002,C,Normal,1,Near Mint,,Ungraded,,100\n'
    return imports.ImportPreviewRequest(filename='synthetic-collection.csv',adapter='COLLECTR',content=text+suffix)


async def expected_error(awaitable,code):
    try:
        await awaitable
    except HTTPException as exc:
        assert exc.status_code==code,(code,exc.status_code,exc.detail)
    else:
        raise AssertionError(f'Expected HTTP {code}')


async def main():
    dsn=os.environ['IMPORT_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/import_intake_test','Disposable local test database only'
    db=await asyncpg.connect(dsn);await _init_connection(db);pool=None
    assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"),'Refusing a nonempty application database'
    try:
        await db.execute(SCHEMA)
        owner_a,owner_b,actor_a,actor_b,card_a,card_b=[uuid4() for _ in range(6)]
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,'CONSIGNOR',1000)",[(owner_a,'Synthetic Seller A'),(owner_b,'Synthetic Seller B')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",[(actor_a,owner_a),(actor_b,owner_b)])
        await db.executemany("""insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
            values($1,$2,'CARD','Pokemon',$3,'Synthetic Set',$4,'Normal','C','English')""",[(card_a,'synthetic:a','Known Card','001'),(card_b,'synthetic:b','Resolved Card','002')])
        async def setup(connection):
            await connection.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=6,init=_init_connection,setup=setup,command_timeout=10)
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),state=SimpleNamespace(request_id='intake-regression'))
        a=SimpleNamespace(user_id=actor_a);b=SimpleNamespace(user_id=actor_b)
        try:
            await api.upload_collection(payload(),request,a)
            raise AssertionError('Missing UPDATE grant was not reproduced')
        except asyncpg.InsufficientPrivilegeError:
            pass
        try:
            async with user_connection(pool,actor_a,'old-lock') as c:
                await c.fetchval('select id from tcg.owners where id=$1 for update',owner_a)
            raise AssertionError('Old ownership-row lock unexpectedly succeeded')
        except asyncpg.InsufficientPrivilegeError:
            pass
        assert await db.fetchval('select count(*) from tcg.inventory_items')==0
        pending=await db.fetch('select id,owner_id,source_sha256,status,version from tcg.import_batches order by id')
        migrations=list((ROOT/'database/migrations').glob('*_owner_incremental_import_intake.sql'));assert len(migrations)==1
        migration=migrations[0].read_text()
        await db.execute(migration);await db.execute(migration)
        assert pending==await db.fetch('select id,owner_id,source_sha256,status,version from tcg.import_batches order by id'),'Migration changed source records'
        assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.import_batches','UPDATE')")
        assert not await db.fetchval("select has_any_column_privilege('tcg_api','tcg.owners','UPDATE')")
        columns=await db.fetch("select attname from pg_attribute where attrelid='tcg.import_batches'::regclass and attnum>0 and not attisdropped and has_column_privilege('tcg_api',attrelid,attname,'UPDATE')")
        assert {r['attname'] for r in columns}=={'version','status','committed_at','automatic_intake','last_auto_apply_version'}
        for role in ('anon','authenticated'):
            assert not await db.fetchval("select has_any_column_privilege($1,'tcg.import_batches','UPDATE')",role)
        result=await api.upload_collection(payload(),request,a)
        batch_id=UUID(result['batch_id'])
        assert result['created_count']==2 and result['summary']['added_units']==2 and result['summary']['review_rows']==1
        assert result['status']=='PREVIEW' and result['automatic_intake']
        assert await db.fetchval('select count(*) from tcg.fixture_committed_events')==0,'Partial batch emitted completion'
        inventory=await db.fetch('select * from tcg.inventory_items order by id')
        assert all(r['owner_id']==owner_a and r['status']=='DRAFT' and not r['identity_confirmed'] and r['acquisition_cost_minor'] is None for r in inventory)
        candidate=await db.fetchrow("select * from tcg.import_candidates where batch_id=$1 and status='REVIEW'",batch_id)
        assert 'missing_language' in candidate['issues'] and not candidate['normalized_record'].get('confidence'),'CSV confidence was trusted'
        version=result['version']
        for _ in range(5):
            replay=await api.upload_collection(payload(),request,a)
            assert replay['created_count']==0 and replay['replayed'] and replay['version']==version
        assert inventory==await db.fetch('select * from tcg.inventory_items order by id')
        await expected_error(api.upload_collection(payload(3),request,a),409)
        assert await db.fetchval('select count(*) from tcg.inventory_items')==2,'New export bypassed open review'
        for operation in (
            imports.get_import_batch(batch_id,request,b),
            api.add_recognised(batch_id,imports.ImportCommitRequest(version=version),request,b),
            api.confirm_candidate(batch_id,candidate['id'],api.ConfirmImportCandidate(version=version,catalogue_id=card_b),request,b),
            api.skip_candidate(batch_id,candidate['id'],ImportCandidateSkipRequest(version=version),request,b),
        ):
            await expected_error(operation,404)
        async with user_connection(pool,actor_b,'foreign-read') as c:
            assert await c.fetchval('select count(*) from tcg.inventory_items')==0
            assert await c.execute('update tcg.import_batches set version=version+1 where id=$1',batch_id)=='UPDATE 0'
        for column in ('owner_id','source_sha256','source_rows'):
            try:
                async with user_connection(pool,actor_a,'immutable-source') as c:
                    await c.execute(f'update tcg.import_batches set {column}={column} where id=$1',batch_id)
                raise AssertionError('Source metadata could be rewritten')
            except asyncpg.InsufficientPrivilegeError:
                pass
        await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actor_b)
        await expected_error(imports.list_import_batches(request,b),403)
        await db.execute('update tcg.owner_memberships set active=true where user_id=$1',actor_b)
        await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",actor_b,owner_a)
        await expected_error(imports.list_import_batches(request,b),409)
        await db.execute('delete from tcg.owner_memberships where user_id=$1 and owner_id=$2',actor_b,owner_a)
        confirmed=await api.confirm_candidate(batch_id,candidate['id'],api.ConfirmImportCandidate(version=version,catalogue_id=card_b),request,a)
        assert confirmed['candidate']['status']=='COMMITTED' and confirmed['created_count']==1
        assert confirmed['summary']['added_units']==3 and confirmed['summary']['review_rows']==0 and confirmed['status']=='COMMITTED'
        assert confirmed['candidate']['normalized_record']['language']=='English'
        assert confirmed['candidate']['normalized_record']['import_identity_confirmation']['method']=='MANUAL'
        retry=await api.confirm_candidate(batch_id,candidate['id'],api.ConfirmImportCandidate(version=version,catalogue_id=card_b),request,a)
        assert retry['replayed'] and retry['created_count']==0
        assert await db.fetchval('select count(*) from tcg.fixture_committed_events where batch_id=$1',batch_id)==1
        assert await db.fetchval('select count(*) from tcg.inventory_items')==3
        # The earlier rejected new preview has a stale baseline. Fresh export
        # includes a harmless newline, not a way to bypass duplicate stock.
        next_result=await api.upload_collection(payload(3,suffix='\n'),request,a)
        assert next_result['created_count']==1 and next_result['summary']['review_rows']==0,'Confirmed source mapping was not retained on re-export'
        assert await db.fetchval('select count(*) from tcg.inventory_items')==4
        decrease=await api.upload_collection(payload(1,suffix='\n'),request,a)
        assert decrease['created_count']==0 and decrease['summary']['review_rows']==1
        before=await db.fetch('select * from tcg.inventory_items order by id')
        decrease_id=UUID(decrease['batch_id'])
        down=await db.fetchrow("select id from tcg.import_candidates where batch_id=$1 and status='REVIEW'",decrease_id)
        await api.skip_candidate(decrease_id,down['id'],ImportCandidateSkipRequest(version=decrease['version']),request,a)
        assert before==await db.fetch('select * from tcg.inventory_items order by id'),'Decrease removed stock'
        plus=await api.upload_collection(payload(4,suffix='\n'),request,a)
        assert plus['created_count']==1,'Skipped decrease corrupted baseline'
        # Concurrent calls through the real restricted pool insert one set only.
        preview=await imports.preview_import(payload(2,review=False),request,b)
        b_id=UUID(preview['batch_id']);commit=imports.ImportCommitRequest(version=preview['version'])
        first,second=await asyncio.gather(api.add_recognised(b_id,commit,request,b),api.add_recognised(b_id,commit,request,b))
        assert sorted([first['created_count'],second['created_count']])==[0,2]
        assert sum(bool(x['replayed']) for x in (first,second))==1
        assert await db.fetchval('select count(*) from tcg.inventory_items where owner_id=$1',owner_b)==2
        # Inject a late failure: copied inventory, candidate writes and audits
        # must all roll back together. The earlier preview is still resumable.
        await db.execute("""create function tcg.fixture_fail_apply() returns trigger language plpgsql as $$begin
            if current_setting('tcg.request_id',true)='rollback-regression' then raise exception 'injected late failure';end if;return new;end$$;
            create trigger fail_apply before update on tcg.import_batches for each row execute function tcg.fixture_fail_apply()""")
        rollback_request=SimpleNamespace(app=request.app,state=SimpleNamespace(request_id='rollback-regression'))
        preview=await imports.preview_import(payload(3,review=False),request,b)
        snapshots={t:await db.fetch(f'select * from tcg.{t} order by 1') for t in ('inventory_items','import_candidates','audit_events')}
        try:
            await api.add_recognised(UUID(preview['batch_id']),imports.ImportCommitRequest(version=preview['version']),rollback_request,b)
            raise AssertionError('Injected failure did not fire')
        except asyncpg.RaiseError:
            pass
        for t,rows in snapshots.items():
            assert rows==await db.fetch(f'select * from tcg.{t} order by 1'),f'Rollback leaked changes in {t}'
        assert await db.fetchval('select count(*)=count(distinct inventory_code) from tcg.inventory_items')
        assert await db.fetchval('select count(*) from tcg.catalogue_products')==2,'Importer created canonical cards'
        print('PASS: original permission/owner-lock failures reproduced; narrow migration/replay; immediate partial Draft intake; manual language confirmation; source mapping persistence; repeated files; +1/decrease; concurrent apply; RLS/foreign/revoked/ambiguous isolation; late-failure atomic rollback; no canonical/Shopify/payment writes.')
    finally:
        if pool:
            await pool.close()
        await db.close()


if __name__=='__main__':
    asyncio.run(main())
