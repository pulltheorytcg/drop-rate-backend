"""CI-only append-only journal tests, after the existing local marketing fixture."""
import asyncio
import os
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from app.db import _init_connection
from app.social_pilot import Journal, PilotCommand, KINDS

A='00000000-0000-4000-8000-000000000001'
B='00000000-0000-4000-8000-000000000002'

async def main():
    dsn=os.environ['MARKETING_TEST_DSN']
    p=urlsplit(dsn)
    assert p.hostname in ('127.0.0.1','localhost') and p.path=='/marketing_test'
    admin=await asyncpg.connect(dsn)
    assert await admin.fetchval('select current_database()')=='marketing_test'
    assert await admin.fetchval("select count(*) from auth.users where id in ($1,$2)",UUID(A),UUID(B))==2
    assert not await admin.fetchval("select to_regclass('tcg.automation_runs')")
    await admin.execute('''create table tcg.automation_runs(
      id uuid primary key default gen_random_uuid(), owner_id uuid not null references tcg.owners(id),
      job_type text not null check(job_type ~ '^N8N:[a-z0-9][a-z0-9-]{1,119}$'),
      run_key text not null check(length(run_key) between 1 and 255),
      initiated_by text not null check(initiated_by in ('N8N','AUTOMATION_SERVICE')),
      result jsonb not null, created_at timestamptz not null default now(),
      unique(owner_id,job_type,run_key));
      alter table tcg.automation_runs enable row level security;
      alter table tcg.automation_runs force row level security;
      grant select,insert on tcg.automation_runs to tcg_api;
      create policy own_review on tcg.automation_runs for all to tcg_api
      using(owner_id in (select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active))
      with check(owner_id in (select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active));''')
    async def setup(c): await c.execute('set role tcg_api')
    pool=await asyncpg.create_pool(dsn,min_size=1,max_size=8,init=_init_connection,setup=setup)
    cmd=PilotCommand(pilot_id='00000000-0000-4000-8000-000000000088',actor_user_id=A,revision_sha256='a'*64,channel='instagram',operation='publish')
    journal=Journal(pool,cmd,'00000000-0000-4000-8000-000000000099')
    manifest={'approved':'fixture','no_provider_call':True}
    try:
        assert await journal.read() is None
        race=await asyncio.gather(*(journal.claim(manifest) for _ in range(8)))
        assert sum(race)==1
        assert (await journal.read())['state']=='UNKNOWN'
        async with Journal(pool,cmd.model_copy(update={'actor_user_id':B}),'other').connection() as (conn,_):
            assert await conn.fetchval('select count(*) from tcg.automation_runs')==0
        await journal.save({'state':'ACCEPTED','post_id':'fixture-post'})
        await journal.save({'state':'FAILED','post_id':'different-late-post'})
        assert (await journal.read())['post_id']=='fixture-post'
        assert await admin.fetchval('select count(*) from tcg.action_required_items where dedupe_key=$1',journal.key)==0
        for _ in range(2): await journal.save({'state':'DELIVERED','post_id':'fixture-post'},observation=True)
        assert await admin.fetchval('select count(*) from tcg.automation_runs where job_type=$1',KINDS['observation'])==1
        try:
            await journal.claim({'approved':'changed'})
            raise AssertionError('Changed revision accepted')
        except HTTPException as error: assert error.status_code==409
        for sql in ('delete from tcg.automation_runs',"update tcg.automation_runs set result='{}'"):
            try:
                async with journal.connection() as (conn,_): await conn.execute(sql)
                raise AssertionError('Journal mutation accepted')
            except asyncpg.InsufficientPrivilegeError: pass
        tt=Journal(pool,cmd.model_copy(update={'channel':'tiktok'}),'tt')
        assert await tt.claim(manifest)
        await admin.execute("create function tcg.pilot_fixture_fail() returns trigger language plpgsql as $$begin raise exception 'fixture alert rejection'; end;$$; create trigger pilot_fixture_fail before insert on tcg.action_required_items for each row execute function tcg.pilot_fixture_fail()")
        try:
            await tt.save({'state':'UNKNOWN','reason':'fixture'})
            raise AssertionError('Failure was swallowed')
        except asyncpg.RaiseError: pass
        assert (await tt.read())['reason']=='CLAIM_EXISTS_WITHOUT_RESULT'
        await admin.execute('drop trigger pilot_fixture_fail on tcg.action_required_items')
        await tt.save({'state':'UNKNOWN','reason':'fixture'})
        assert (await tt.read())['state']=='UNKNOWN'
        await admin.execute("update tcg.action_required_items set status='RESOLVED' where dedupe_key=$1",tt.key)
        await tt.save({'state':'UNKNOWN','reason':'fixture'})
        assert await admin.fetchval('select status from tcg.action_required_items where dedupe_key=$1',tt.key)=='RESOLVED'
        print('PASS: actual append-only journal, eight-way single claim, actor isolation, immutable intent/result, observations, unknown recovery and alert rollback; no provider request')
    finally:
        await pool.close(); await admin.close()

if __name__=='__main__': asyncio.run(main())
