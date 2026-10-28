"""Real PostgreSQL failure tests for the reviewed, privileged operator repair.

Only a disposable localhost database named sv11b_test is accepted.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import asyncpg

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "00000000-0000-0000-0000-000000000001"
SQL = (ROOT/"database/proposals/repair_sv11b_numbers.sql").read_text(encoding="utf-8")
PREFLIGHT = (ROOT/"database/proposals/repair_sv11b_preflight.sql").read_text(encoding="utf-8")
SCHEMA = """
create schema tcg;
create function tcg.is_platform_admin() returns boolean language sql stable as
$$ select current_setting('tcg.user_id',true)='00000000-0000-0000-0000-000000000001' $$;
create table tcg.reference_sets(provider text,system_code text,language text,set_id text,
 name text,declared_card_count int,source_url text,refreshed_at timestamptz default now(),
 primary key(provider,system_code,language,set_id));
create table tcg.reference_cards(provider text,system_code text,language text,set_id text,
 provider_id text,name text,card_number text,number_key text,source_url text,image_url text,
 finish text,rarity text,evidence jsonb not null,refreshed_at timestamptz default now(),
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,set_id) references tcg.reference_sets);
create table tcg.reference_sync_runs(id uuid primary key default gen_random_uuid(),
 source text,status text,finished_at timestamptz,sets_loaded int,cards_loaded int,report jsonb);
create table tcg.audit_events(id uuid primary key default gen_random_uuid(), actor text,
 request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
create table tcg.inventory_items(id int primary key,owner text,store_price int);
create table tcg.reference_market_prices(id int primary key,value int);
insert into tcg.inventory_items values(1,'founder-2',32000);
insert into tcg.reference_market_prices values(1,33000);
"""
SEED = """
truncate tcg.reference_cards,tcg.reference_sets,tcg.reference_sync_runs,tcg.audit_events cascade;
insert into tcg.reference_sets(provider,system_code,language,set_id,name,declared_card_count,source_url)
 values('TCGdex','POKEMON_TCG','Japanese','SV11B','ブラックボルト',174,'https://api.tcgdex.net/v2/ja/sets/SV11B'),
 ('TCGdex','POKEMON_TCG','Japanese','SV11W','White Flare',174,'https://example.test/SV11W');
insert into tcg.reference_cards(provider,system_code,language,set_id,provider_id,name,card_number,number_key,
 source_url,image_url,finish,rarity,evidence)
 select 'TCGdex','POKEMON_TCG','Japanese','SV11B','SV11B-'||lpad(n::text,3,'0'),'Card '||n,
 lpad(n::text,3,'0')||'/174',n::text||':/:174',
 'https://api.tcgdex.net/v2/ja/cards/SV11B-'||lpad(n::text,3,'0'),
 'https://preserved.example/'||n,'Unresolved','Sentinel',
 jsonb_build_object('provider_local_id',lpad(n::text,3,'0'),'image_reference',jsonb_build_object('verified',true))
 from generate_series(1,174) n;
insert into tcg.reference_cards(provider,system_code,language,set_id,provider_id,name,card_number,number_key,
 source_url,image_url,finish,rarity,evidence)
 values('TCGdex','POKEMON_TCG','Japanese','SV11W','SV11W-001','Unrelated','001/174','1:/:174',
 'https://example.test/unrelated','https://preserved.example/unrelated','Unresolved','Sentinel','{}');
"""
async def snapshot(conn):
    return await conn.fetchval("""select jsonb_agg(to_jsonb(r) order by provider_id)::text from tcg.reference_cards r""")

def script(digest, actor=ACTOR):
    return SQL.replace("__ACTOR_USER_ID__", actor).replace("__SNAPSHOT_SHA256__", digest)

async def rejected(conn, sql, message):
    try:
        await conn.execute(sql)
    except asyncpg.PostgresError as exc:
        await conn.execute("rollback")
        assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError("Expected repair rejection: "+message)
    assert await conn.fetchval("select count(*) from tcg.audit_events")==0
    assert await conn.fetchval("select count(*) from tcg.reference_sync_runs")==0

async def main():
    dsn=os.environ["SV11B_TEST_DSN"]
    parsed=urlsplit(dsn)
    assert parsed.hostname in {"127.0.0.1","localhost"} and parsed.path=="/sv11b_test", "Disposable database required"
    conn=await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA)
        await conn.execute(SEED)
        before=json.loads(await snapshot(conn))
        digest=await conn.fetchval(PREFLIGHT)
        await conn.execute(script(digest))
        after=json.loads(await snapshot(conn))
        assert len(after)==175
        for old,new in zip(before,after):
            if old["set_id"]!="SV11B":
                assert old==new
                continue
            n=int(old["provider_id"][6:])
            assert new["card_number"]==f"{n:03d}/086" and new["number_key"]==f"{n}:/:86"
            assert new["evidence"]["collector_number_reference"]["printed_denominator"]==86
            new["evidence"].pop("collector_number_reference")
            new["card_number"],new["number_key"]=old["card_number"],old["number_key"]
            assert old==new, "Artwork, identity and unrelated metadata must remain byte-equivalent"
        assert await conn.fetchval("select count(*) from tcg.audit_events")==174
        assert await conn.fetchval("select count(*) from tcg.reference_sync_runs where status='COMPLETE' and cards_loaded=174")==1
        assert await conn.fetchval("select count(*) from tcg.audit_events where old_values->>'card_number' like '%/174' and new_values->>'card_number' like '%/086'")==174
        assert await conn.fetchval("select store_price from tcg.inventory_items where id=1")==32000
        assert await conn.fetchval("select value from tcg.reference_market_prices where id=1")==33000
        await conn.execute(script(digest))
        assert await conn.fetchval("select count(*) from tcg.audit_events")==174
        assert await conn.fetchval("select count(*) from tcg.reference_sync_runs")==1
        print("PASS: complete correction, unchanged metadata, audit and idempotency")

        for change, expected in [
            ("update tcg.reference_cards set name='Changed' where provider_id='SV11B-086'","Snapshot changed"),
            ("update tcg.reference_cards set image_url='https://changed.example/' where provider_id='SV11B-086'","Snapshot changed"),
            ("delete from tcg.reference_cards where provider_id='SV11B-174'","Exactly 174"),
            ("update tcg.reference_cards set source_url='https://wrong.example/' where provider_id='SV11B-086'","Reference identity"),
            ("update tcg.reference_cards set number_key='wrong' where provider_id='SV11B-086'","Reference identity"),
            ("update tcg.reference_cards set card_number=null where provider_id='SV11B-086'","Reference identity"),
            ("update tcg.reference_sets set name='Wrong' where set_id='SV11B'","set identity")
        ]:
            await conn.execute(SEED)
            digest=await conn.fetchval(PREFLIGHT)
            await conn.execute(change)
            before=await snapshot(conn)
            await rejected(conn,script(digest),expected)
            assert before==await snapshot(conn)
        print("PASS: changed identities, reviewed snapshot and image races reject before writes")

        await conn.execute(SEED)
        digest=await conn.fetchval(PREFLIGHT)
        await rejected(conn,script(digest,"00000000-0000-0000-0000-000000000002"),"administrator required")
        other=await asyncpg.connect(dsn)
        try:
            await other.execute("select pg_advisory_lock(847220092)")
            await rejected(conn,script(digest),"maintenance busy")
        finally:
            await other.close()
        print("PASS: administrator and concurrent maintenance guards")

        await conn.execute("""create function tcg.fail_audit() returns trigger language plpgsql as $$
          begin if new.old_values->>'provider_id'='SV11B-087' then raise exception 'INJECTED_AUDIT_FAILURE'; end if; return new; end $$;
          create trigger fail_audit before insert on tcg.audit_events for each row execute function tcg.fail_audit();""")
        before=await snapshot(conn)
        await rejected(conn,script(digest),"INJECTED_AUDIT_FAILURE")
        assert before==await snapshot(conn)
        print("PASS: failure after 86 updates rolls back all data, audit and run receipt")
    finally:
        await conn.close()

if __name__=="__main__":
    asyncio.run(main())
