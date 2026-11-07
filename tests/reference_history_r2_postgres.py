"""Real PostgreSQL archive guards. Refuses remote/nonempty databases; synthetic data only."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from app.db import _init_connection

ADMIN=UUID("00000000-0000-0000-0000-000000000001")
OWNER=UUID("00000000-0000-0000-0000-000000000002")
ROOT=Path(__file__).resolve().parents[1]
CALL="select tcg_private.archive_verified_reference_history_r2($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)"
HASH="""select count(*) as count,encode(sha256(convert_to(string_agg(
encode(sha256(convert_to(row_to_json(h)::text,'UTF8')),'hex'),'' order by h.id),'UTF8')),'hex') as root
from tcg.reference_market_history h"""
FIXTURE="""
create schema tcg;
create role tcg_api nologin nobypassrls;
create role anon nologin nobypassrls;
create role authenticated nologin nobypassrls;
create function tcg.current_user_id() returns uuid language sql stable as
$$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create function tcg.is_platform_admin() returns boolean language sql stable as
$$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
grant usage on schema tcg to tcg_api;
create table tcg.owners(id uuid primary key,display_name text,owner_type text,active boolean,founder_slot int);
create table tcg.owner_memberships(id uuid primary key,user_id uuid,owner_id uuid,role text,active boolean,created_at timestamptz default now());
insert into tcg.owners values('10000000-0000-0000-0000-000000000001','Fixture founder','FOUNDER',true,1);
insert into tcg.owner_memberships(id,user_id,owner_id,role,active) values
('20000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001',
'10000000-0000-0000-0000-000000000001','PLATFORM_ADMIN',true);
grant select on tcg.owners,tcg.owner_memberships to tcg_api;
create table tcg.reference_market_history (
 id uuid primary key default gen_random_uuid(),
 reference_kind text not null check(reference_kind in ('CARD','SEALED')),
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null check(jsonb_typeof(quotes)='array'),quote_digest text not null,
 market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,
 recorded_at timestamptz not null default clock_timestamp(),
 unique(reference_kind,provider,system_code,language,provider_id,quote_digest));
create index reference_market_history_timeline on tcg.reference_market_history
(reference_kind,provider,system_code,language,provider_id,recorded_at desc);
alter table tcg.reference_market_history enable row level security;
alter table tcg.reference_market_history force row level security;
create policy reference_history_admin on tcg.reference_market_history for all to postgres using(true) with check(true);
create policy reference_history_read on tcg.reference_market_history for select to tcg_api
using((select tcg.current_user_id()) is not null);
revoke all on tcg.reference_market_history from public,anon,authenticated,tcg_api;
grant select on tcg.reference_market_history to tcg_api;
create table tcg.reference_market_prices(provider_id text primary key,market_value_minor bigint,quotes jsonb);
create table tcg.inventory_items(id uuid primary key,owner_id uuid,cost_minor bigint,store_price_minor bigint);
insert into tcg.reference_market_prices values('current',12345,'[{"source":"fixture"}]');
insert into tcg.inventory_items values
('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',123,456);
"""
async def seed(db,count=3):
    await db.execute("""with evidence as (
 select g,jsonb_build_array(jsonb_build_object('source','FIXTURE','original_currency','JPY',
 'original_minor',g*111,'price_gbp_minor',g*100,'name','\u30d4\u30ab\u30c1\u30e5\u30a6',
 'precise','0.123456789012345678901234567890'::numeric,'large',9007199254740993::bigint,
 'nested',jsonb_build_object('x',true))) as quotes
 from generate_series(1,$1::int) g)
insert into tcg.reference_market_history
(reference_kind,provider,system_code,language,provider_id,quotes,quote_digest,
 market_value_minor,market_value_high_minor,pricing_updated_at)
select 'CARD','Fixture','POKEMON_TCG','Japanese','fixture-'||gen_random_uuid(),
 quotes,md5(quotes::text),case when g%2=0 then null else g*100 end,
 case when g%2=0 then null else g*125 end,timestamptz '2026-10-01 00:01:02.123456+09'
from evidence""",count)


async def context(db,user=ADMIN,role="tcg_api"):
    await db.execute("reset role")
    assert role in ("tcg_api","anon","authenticated")
    await db.execute("set role "+role)
    await db.execute("select set_config('tcg.user_id',$1,false)",str(user) if user else "")
    await db.execute("select set_config('tcg.request_id','archive-ci',false)")

async def fails(awaitable,*errors):
    try:
        await awaitable
    except errors:
        return
    raise AssertionError("Unsafe operation unexpectedly succeeded")

async def args_for(db,label):
    row=await db.fetchrow(HASH)
    return [label,row["count"],row["root"],"drop-rate/reference-history/"+"1"*64+".ndjson.gz",
      "drop-rate/reference-history/"+"2"*64+".manifest.json","1"*64,"2"*64,
      "https://fixture.r2.cloudflarestorage.com","fixture-private",datetime.now(timezone.utc)]

async def authority(db):
    await db.execute("reset role")
    return [await db.fetch("select row_to_json(t)::text from tcg."+table+" t order by row_to_json(t)::text")
            for table in ("reference_market_prices","inventory_items")]

async def run_sql_checks(db,other):
    await seed(db,401)
    baseline=await authority(db)
    original=await db.fetchval("select count(*) from tcg.reference_market_history")
    args=await args_for(db,"ci-manual")
    assert await db.fetchval("select relrowsecurity and relforcerowsecurity from pg_class where oid='tcg.reference_history_r2_archives'::regclass")
    for role in ("anon","authenticated"):
        await context(db,ADMIN,role)
        await fails(db.fetchval(CALL,*args),asyncpg.InsufficientPrivilegeError)
    for user in (None,OWNER):
        await context(db,user)
        await fails(db.fetchval(CALL,*args),asyncpg.InsufficientPrivilegeError)
    await context(db)
    for sql in ("delete from tcg.reference_market_history","truncate tcg.reference_market_history",
                "select * from tcg.reference_history_r2_archives"):
        await fails(db.execute(sql),asyncpg.InsufficientPrivilegeError)
    for index,value in ((1,original+1),(2,"0"*64),(3,"drop-rate/private-media/"+"1"*64+".webp"),
      (4,"drop-rate/reference-history/../../manifest.json"),(7,"https://user:password@example.test"),
      (8,"bad/bucket"),(9,datetime.now(timezone.utc)-timedelta(days=2))):
        invalid=list(args);invalid[index]=value
        await fails(db.fetchval(CALL,*invalid),asyncpg.RaiseError)
        assert await db.fetchval("select count(*) from tcg.reference_market_history")==original

    # Concurrent committed inserts make a previously exported snapshot unusable.
    await seed(other,1)
    await fails(db.fetchval(CALL,*args),asyncpg.RaiseError)
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==original+1

    # An old REPEATABLE READ/SERIALIZABLE snapshot must NEVER hide rows from TRUNCATE.
    for isolation in ("repeatable_read","serializable"):
        tx=db.transaction(isolation=isolation)
        await tx.start()
        try:
            snapshot_args=await args_for(db,"stale-"+isolation)
            await seed(other,1)
            await fails(db.fetchval(CALL,*snapshot_args),asyncpg.RaiseError)
        finally:
            await tx.rollback()
    original+=3
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==original
    args=await args_for(db,"ci-manual")

    # Cancellation/rollback after cleanup rolls back both receipt and TRUNCATE.
    tx=db.transaction()
    await tx.start()
    result=await db.fetchval(CALL,*args)
    assert result["status"]=="ARCHIVED" and result["rows_archived"]==original
    await tx.rollback()
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==original
    result=await db.fetchval(CALL,*args)
    assert result["status"]=="ARCHIVED" and result["bytes_reclaimed"]>0
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==0
    await db.execute("reset role")
    receipt=await db.fetchrow("select * from tcg.reference_history_r2_archives where archive_id=$1",args[0])
    assert receipt["archived_by"]==ADMIN and receipt["row_count"]==original
    assert receipt["relation_bytes_before"]-receipt["relation_bytes_after"]==result["bytes_reclaimed"]
    assert await authority(db)==baseline
    await seed(other,1)
    await context(db)
    retry=await db.fetchval(CALL,*args)
    assert retry["status"]=="ALREADY_ARCHIVED" and retry["bytes_reclaimed"]==0
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==1
    different=list(args);different[2]="0"*64
    await fails(db.fetchval(CALL,*different),asyncpg.RaiseError)
    assert await db.fetchval("select count(*) from tcg.reference_market_history")==1
    await db.execute("reset role")
    await db.execute("truncate tcg.reference_market_history")



class MissingObject(Exception):
    response={"Error":{"Code":"NoSuchKey"}}

class MemoryS3:
    """Preserve bytes while actual S3ObjectStorage performs every verification."""
    def __init__(self):
        self.objects={}
        self.gets=0
        self.corrupt_at=None
    def get_object(self,*,Bucket,Key):
        import io
        self.gets+=1
        if (Bucket,Key) not in self.objects:
            raise MissingObject()
        value=self.objects[(Bucket,Key)]
        if self.gets==self.corrupt_at:
            value+=b"CORRUPT"
        return {"Body":io.BytesIO(value),"ContentLength":len(value)}
    def put_object(self,*,Bucket,Key,Body,**kwargs):
        self.objects[(Bucket,Key)]=Body.read() if hasattr(Body,"read") else bytes(Body)
        return {"ETag":"Never-used-as-verification"}

async def worker_roundtrip(db,dsn):
    from app.object_storage import ObjectStorageConfig,ObjectStorageError,S3ObjectStorage
    from app.reference_history_archive import archive_reference_history
    async def setup(conn):
        await conn.execute("set role tcg_api")
    pool=await asyncpg.create_pool(dsn=dsn,min_size=1,max_size=4,init=_init_connection,setup=setup,
        server_settings={"TimeZone":"Pacific/Auckland","statement_timeout":"15000"})
    transport=MemoryS3()
    store=S3ObjectStorage(ObjectStorageConfig(
        endpoint="https://fixture.r2.cloudflarestorage.com",bucket="fixture-private",
        region="auto",access_key_id="synthetic",secret_access_key="synthetic",prefix="drop-rate"),
        client=transport)
    try:
        await seed(db,401)
        baseline=await authority(db)
        before=await db.fetch("select row_to_json(h)::text from tcg.reference_market_history h order by id")
        copied=await archive_reference_history(pool,ADMIN,cleanup=False,store=store)
        assert copied["status"]=="BYTES_AND_RESTORE_VERIFIED",copied
        assert copied["verified_rows"]==401 and copied["restoration_verified"] is True
        assert len(transport.objects)==2
        assert before==await db.fetch("select row_to_json(h)::text from tcg.reference_market_history h order by id")
        count_before=await db.fetchval("select count(*) from tcg.reference_history_r2_archives")
        # First GET successfully verifies existing upload; second corrupts DOWNLOAD.
        transport.corrupt_at=transport.gets+2
        await fails(archive_reference_history(pool,ADMIN,cleanup=True,store=store),ObjectStorageError)
        transport.corrupt_at=None
        assert before==await db.fetch("select row_to_json(h)::text from tcg.reference_market_history h order by id")
        assert await db.fetchval("select count(*) from tcg.reference_history_r2_archives")==count_before
        await fails(archive_reference_history(pool,ADMIN,cleanup=True,max_rows=400,store=store),ObjectStorageError)
        assert before==await db.fetch("select row_to_json(h)::text from tcg.reference_market_history h order by id")
        archived=await archive_reference_history(pool,ADMIN,cleanup=True,store=store)
        assert archived["status"]=="ARCHIVED" and archived["rows_archived"]==401,archived
        assert archived["bytes_reclaimed"]>0
        assert await db.fetchval("select count(*) from tcg.reference_market_history")==0
        assert await db.fetchval("select count(*) from tcg.reference_history_r2_archives")==count_before+1
        assert len(transport.objects)==2,"Deterministic retry must reuse content-addressed files"
        assert await authority(db)==baseline
        empty=await archive_reference_history(pool,ADMIN,cleanup=True,store=store)
        assert empty["status"]=="NO_HISTORY"
    finally:
        await pool.close()
    print("PASS: 401-row remote-byte/typed-restore roundtrip, non-UTC session, Unicode/JSON precision, bounded limits and corrupt download refusal")


async def main():
    dsn=os.environ["HISTORY_R2_TEST_DSN"];url=urlsplit(dsn)
    assert url.hostname in ("localhost","127.0.0.1") and url.path=="/history_r2_test","Disposable localhost database only"
    db=await asyncpg.connect(dsn);other=await asyncpg.connect(dsn)
    await _init_connection(db);await _init_connection(other)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname in ('tcg','tcg_private'))"),"Refusing nonempty schema"
        await db.execute("set timezone='UTC'")
        await db.execute(FIXTURE)
        pending=ROOT/"database/pending/reference_history_r2_archive.sql"
        migrations=sorted((ROOT/"database/migrations").glob("*reference_history_r2_archive.sql"))
        migration=pending if pending.is_file() else migrations[-1]
        await db.execute(migration.read_text(encoding="utf-8"))
        await run_sql_checks(db,other)
        await worker_roundtrip(db,dsn)
    finally:
        await db.close();await other.close()
    print("PASS: archive privileges/RLS, corrupted receipt refusal, concurrent writes, stale snapshots, rollback, retry, unchanged prices/inventory and actual bytes reclaimed")

if __name__=="__main__":
    asyncio.run(main())


