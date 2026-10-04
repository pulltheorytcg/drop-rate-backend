"""Explicit CI-only PostgreSQL integration smoke; refuses nonlocal/nonempty databases."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException

from app.db import _init_connection
from app.marketing_specialist_api import CreateCommand, PostgresStore
from app.marketing_specialists import Command, JobInput, digest

ROOT = Path(__file__).resolve().parents[1]
F1 = UUID('00000000-0000-4000-8000-000000000001')
F2 = UUID('00000000-0000-4000-8000-000000000002')
OWNER = UUID('00000000-0000-4000-8000-000000000003')


async def main():
    dsn = os.environ['MARKETING_TEST_DSN']
    parsed = urlsplit(dsn)
    assert parsed.hostname in {'127.0.0.1', 'localhost'}
    assert parsed.path == '/marketing_test'
    admin = await asyncpg.connect(dsn)
    assert await admin.fetchval('select current_database()') == 'marketing_test'
    assert not await admin.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
    await admin.execute('''
        create role tcg_api nologin nobypassrls;
        create role anon nologin;
        create role authenticated nologin;
        create schema auth;
        create table auth.users(id uuid primary key);
        create schema tcg;
        create table tcg.owners(id uuid primary key, display_name text, owner_type text, founder_slot int, active boolean);
        create table tcg.owner_memberships(id uuid primary key, user_id uuid, owner_id uuid, role text, active boolean, created_at timestamptz default now());
        create function tcg.current_user_id() returns uuid language sql stable as
          $$ select nullif(current_setting('tcg.user_id',true),'')::uuid $$;
        create function tcg.is_platform_admin() returns boolean language sql stable as
          $$ select exists(select 1 from tcg.owner_memberships m join tcg.owners o on o.id=m.owner_id
               where m.user_id=tcg.current_user_id() and m.active and o.active and m.role='PLATFORM_ADMIN' and o.owner_type='FOUNDER') $$;
        grant usage on schema tcg to tcg_api,anon,authenticated;
        grant select on tcg.owners,tcg.owner_memberships to tcg_api;
    ''')
    for index, actor in enumerate((F1, F2, OWNER), 1):
        await admin.execute('insert into auth.users values($1)', actor)
        await admin.execute('insert into tcg.owners values($1,$2,$3,$4,true)', actor, 'Fixture', 'FOUNDER' if index < 3 else 'CONSIGNOR', index if index < 3 else None)
        await admin.execute('insert into tcg.owner_memberships(id,user_id,owner_id,role,active) values($1,$1,$1,$2,true)', actor, 'PLATFORM_ADMIN' if index < 3 else 'OWNER')
    migration = ROOT / 'database/migrations/20261004133308_marketing_specialists_v1.sql'
    await admin.execute(migration.read_text())
    assert await admin.fetchval("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='tcg' and c.relname in ('marketing_specialist_jobs','marketing_specialist_runs') and c.relrowsecurity and c.relforcerowsecurity") == 2
    for role in ('anon', 'authenticated'):
        for table in ('marketing_specialist_jobs', 'marketing_specialist_runs'):
            assert not await admin.fetchval('select has_table_privilege($1,$2,\'SELECT\')',role,'tcg.'+table)
    assert not await admin.fetchval("select prosecdef from pg_proc where oid='tcg.marketing_specialist_history_guard()'::regprocedure")

    async def setup(connection):
        await connection.execute('set role tcg_api')

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8, init=_init_connection, setup=setup)
    try:
        store = PostgresStore(pool, F1, str(uuid4()))
        job_id = uuid4()
        source = JobInput(topic='Isolated test only')
        create = CreateCommand(job_id=job_id, actor_user_id=F1, input=source)
        job = await store.create(create)
        assert (await store.create(create))['id'] == job_id
        try:
            await store.create(CreateCommand(job_id=job_id,actor_user_id=F1,input=JobInput(topic='Changed')))
            raise AssertionError('Changed immutable job was accepted')
        except HTTPException as exc:
            assert exc.status_code == 409
        cmd = Command(job_id=job_id,actor_user_id=F1,stage='research',expected_input_sha256=job['input_sha256'])
        results = await asyncio.gather(*(store.claim(cmd, {'topic':'fixture'}, 'a'*64, 'b'*64) for _ in range(8)))
        assert sum(claimed for claimed, _ in results) == 1
        assert len({str(record['id']) for _,record in results}) == 1
        result = await store.finish(cmd,'PREPARED',{'summary':'fixture'}, {'input_tokens':1})
        assert result['state'] == 'PREPARED'
        assert (await store.finish(cmd,'FAILED',{'error_code':'late'},{}))['state'] == 'PREPARED'
        assert (await store.read_stage(cmd,'research'))['output']['summary'] == 'fixture'

        other = PostgresStore(pool, F2, str(uuid4()))
        try:
            await other.read_job(cmd)
            raise AssertionError('Cross-actor job read succeeded')
        except HTTPException as exc:
            assert exc.status_code == 404
        async with other.connection() as conn:
            assert await conn.fetchval('select count(*) from tcg.marketing_specialist_jobs where id=$1',job_id) == 0
        try:
            async with PostgresStore(pool,OWNER,str(uuid4())).connection():
                pass
            raise AssertionError('Non-admin accepted')
        except HTTPException as exc:
            assert exc.status_code == 403
        for statement, params in [
            ('update tcg.marketing_specialist_jobs set input=\'{}\'::jsonb where id=$1', (job_id,)),
            ('delete from tcg.marketing_specialist_runs where job_id=$1', (job_id,)),
            ("update tcg.marketing_specialist_runs set state='FAILED' where job_id=$1", (job_id,)),
        ]:
            try:
                async with store.connection() as conn:
                    await conn.execute(statement,*params)
                raise AssertionError('History mutation accepted')
            except asyncpg.PostgresError:
                pass
        try:
            async with other.connection() as conn:
                await conn.execute('insert into tcg.marketing_specialist_jobs(id,revision,created_by,input,input_sha256) values($1,1,$2,$3::jsonb,$4)', uuid4(),F1,{},'c'*64)
            raise AssertionError('Forged actor insert accepted')
        except asyncpg.InsufficientPrivilegeError:
            pass
        # Fixture-only abandoned run. The application cannot set timestamps itself.
        await admin.execute("insert into tcg.marketing_specialist_runs(job_id,revision,stage,created_by,input,input_sha256,prompt_version,prompt_sha256,model,started_at) values($1,1,'brief',$2,'{}','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc','fixture','dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd','fixture',now()-interval '6 minutes')",job_id,F1)
        old = cmd.model_copy(update={'stage':'brief'})
        claimed, result = await store.claim(old,{},'c'*64,'d'*64)
        assert not claimed and result['state'] == 'UNKNOWN'
        assert result['output_sha256'] == digest({'error_code':'WORKER_RESULT_UNKNOWN'})
        assert (await store.finish(old,'PREPARED',{'summary':'too late'},{}))['state'] == 'UNKNOWN'
        print('PASS: migration, forced RLS, denied public grants, actor isolation, immutable jobs/results, eight-way claim race, replay, unknown recovery and late-result protection')
    finally:
        await pool.close()
        await admin.close()


if __name__ == '__main__':
    asyncio.run(main())
