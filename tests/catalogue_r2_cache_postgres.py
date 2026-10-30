"""Real PostgreSQL parity for exact-set R2 reference inputs; synthetic data only.

Native CI: CATALOGUE_R2_CACHE_TEST_DSN must target localhost/catalogue_r2_cache_test.
Local: --pglite uses the existing pinned tools/history-archive-verify dependency.
Both modes execute the production snapshot SQL, original/cached product_query,
shared-price/history helpers, actual valuation migrations, and restricted-role RLS.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from uuid import UUID

import asyncpg
from fastapi.encoders import jsonable_encoder

from app.catalogue_browser import product_query
from app.catalogue_display_prices import read_shared_prices, with_shared_price
from app.catalogue_price_history import add_reference_history
from app.db import _init_connection
from shared_reference_fixture import install_reference_schema

ROOT = Path(__file__).resolve().parents[1]
OWNER_A = UUID('10000000-0000-0000-0000-000000000001')
OWNER_B = UUID('10000000-0000-0000-0000-000000000002')
ACTOR_A = UUID('20000000-0000-0000-0000-000000000001')
ACTOR_B = UUID('20000000-0000-0000-0000-000000000002')
CANONICAL = UUID('30000000-0000-0000-0000-000000000001')
SHARED = UUID('30000000-0000-0000-0000-000000000003')
AMBIGUOUS = UUID('30000000-0000-0000-0000-000000000004')
MEDIA = UUID('40000000-0000-0000-0000-000000000001')
SCOPE_ARGS = dict(provider='TCGdex', system_code='POKEMON_TCG', language='English', set_id='cache-fixture')
PRIVATE = 'OWNER_PRIVATE_FIXTURE_MUST_NOT_ENTER_R2'

SCHEMA = """
create schema tcg;
create role tcg_api nologin nosuperuser nobypassrls;
create function tcg.current_user_id() returns uuid language sql stable as
$$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create table tcg.owners(id uuid primary key, private_notes text);
create table tcg.owner_memberships(user_id uuid,owner_id uuid,role text,active bool default true);
create table tcg.catalogue_products(id uuid primary key,product_type text,game text,name text,
 set_name text,card_number text,variant text,rarity text,language text,created_by_user_id uuid);
create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text,
 collectible_type text,set_code text,release_date date,identity_status text,attributes jsonb default '{}');
create table tcg.inventory_items(id uuid primary key,owner_id uuid,catalogue_id uuid,status text,
 market_value_minor bigint,acquisition_cost_minor bigint,store_price_minor bigint,private_notes text);
create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,
 release_date date,declared_card_count int,source_url text,refreshed_at timestamptz default now(),
 primary key(provider,system_code,language,set_id));
create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,
 set_id text,name text,card_number text,rarity text,image_url text,source_url text,
 number_key text,finish text,evidence jsonb,refreshed_at timestamptz default now(),
 primary key(provider,system_code,language,provider_id));
create index reference_cards_set_test_idx on tcg.reference_cards(provider,system_code,language,set_id);
create table tcg.reference_market_prices(provider text,system_code text,language text,provider_id text,
 market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,
 quotes jsonb default '[]',checked_at timestamptz,expires_at timestamptz,refresh_revision int default 3,
 primary key(provider,system_code,language,provider_id));
create table tcg.reference_catalogue_prices(like tcg.reference_market_prices including all);
create table tcg.reference_sealed_products(provider text,system_code text,language text,provider_id text,
 set_id text,name text,product_type text,image_url text,source_url text);
create table tcg.reference_sealed_market_prices(provider text,system_code text,language text,
 provider_id text,market_value_minor bigint,market_value_high_minor bigint,
 pricing_updated_at timestamptz,quotes jsonb);
create table tcg.media_assets(id uuid primary key,catalogue_id uuid,owner_id uuid,
 scope text,side text,media_kind text,approval_status text,rights_status text,rights_tier text,
 source_status text,revoked_at timestamptz,approved_at timestamptz,created_at timestamptz default now(),
 shopify_cdn_url text,public_source_url text);
create table tcg.media_object_mirrors(media_asset_id uuid,source_url text,object_key text);
create table tcg.reference_image_mirrors(provider text,system_code text,language text,provider_id text,
 source_url text,object_key text,status text);
grant usage on schema tcg to tcg_api;
grant select on all tables in schema tcg to tcg_api;
alter table tcg.owner_memberships enable row level security;
alter table tcg.owner_memberships force row level security;
create policy membership_read on tcg.owner_memberships for select to tcg_api
 using(user_id=tcg.current_user_id() and active);
alter table tcg.inventory_items enable row level security;
alter table tcg.inventory_items force row level security;
create policy inventory_read on tcg.inventory_items for select to tcg_api
 using(owner_id in(select owner_id from tcg.owner_memberships));
"""


class PGliteError(RuntimeError):
    pass


class PGliteConnection:
    """Tiny asyncpg-shaped SQL transport; no SQL/result mocking."""

    def __init__(self, process):
        self.process = process
        self.transaction_depth = 0

    @classmethod
    async def open(cls):
        process = await asyncio.create_subprocess_exec(
            'node', str(ROOT / 'tests/catalogue_r2_cache_pglite.mjs'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=4_000_000,
        )
        return cls(process)

    async def _request(self, operation, sql='', arguments=()):
        request = json.dumps(dict(operation=operation, sql=sql, arguments=jsonable_encoder(arguments)))
        self.process.stdin.write((request + '\n').encode())
        await self.process.stdin.drain()
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=45)
        if not line:
            diagnostic = (await self.process.stderr.read()).decode()[:2000]
            raise RuntimeError('PGlite exited: ' + diagnostic)
        result = json.loads(line)
        if not result['ok']:
            raise PGliteError(f"{result.get('code')}: {result['message']}")
        return result['rows']

    async def execute(self, sql, *arguments):
        return await self._request('execute', sql, arguments)

    async def fetch(self, sql, *arguments, timeout=None):
        return await self._request('fetch', sql, arguments)

    async def fetchrow(self, sql, *arguments):
        rows = await self.fetch(sql, *arguments)
        return rows[0] if rows else None

    async def fetchval(self, sql, *arguments):
        row = await self.fetchrow(sql, *arguments)
        return next(iter(row.values())) if row else None

    @asynccontextmanager
    async def transaction(self, *, isolation=None, readonly=False):
        # SQL savepoints, not a mocked recovery path. This mirrors the small
        # asyncpg context-manager surface used by the production cache reader.
        outer = self.transaction_depth == 0
        savepoint = f'cache_fixture_{self.transaction_depth}'
        if outer:
            assert isolation in (None,'repeatable_read')
            await self.execute('begin' + (' isolation level repeatable read' if isolation else '')
                               + (' read only' if readonly else ''))
        else:
            await self.execute(f'savepoint {savepoint}')
        self.transaction_depth += 1
        try:
            yield
        except BaseException:
            await self.execute('rollback' if outer else f'rollback to savepoint {savepoint}')
            if not outer:
                await self.execute(f'release savepoint {savepoint}')
            raise
        else:
            await self.execute('commit' if outer else f'release savepoint {savepoint}')
        finally:
            self.transaction_depth -= 1

    async def close(self):
        try:
            await self._request('close')
        finally:
            self.process.stdin.close()
            await asyncio.wait_for(self.process.wait(), timeout=5)


@asynccontextmanager
async def authorized(db, actor=ACTOR_A):
    async with db.transaction(isolation='repeatable_read',readonly=True):
        await db.execute('set local role tcg_api')
        await db.execute("select set_config('tcg.user_id',$1,true)", str(actor) if actor else '')
        yield db


async def seed(db):
    await db.execute(SCHEMA)
    await install_reference_schema(db)
    # Snapshot sources are globally readable only under authenticated API context.
    for table in ('reference_sets','reference_cards','reference_market_prices','reference_catalogue_prices'):
        await db.execute(f'''alter table tcg.{table} enable row level security;
          alter table tcg.{table} force row level security;
          create policy authenticated_reference on tcg.{table} for select to tcg_api
          using((select tcg.current_user_id()) is not null)''')
    for owner, actor in ((OWNER_A, ACTOR_A),(OWNER_B, ACTOR_B)):
        await db.execute('insert into tcg.owners values($1,$2)', owner, PRIVATE)
        await db.execute("insert into tcg.owner_memberships values($1,$2,'OWNER',true)", actor, owner)
    await db.execute("""insert into tcg.reference_sets(provider,system_code,language,set_id,name,release_date,source_url)
      values('TCGdex','POKEMON_TCG','English','cache-fixture','Fixture Set',current_date-30,'https://fixture.invalid/set'),
      ('TCGdex','POKEMON_TCG','Japanese','cache-fixture','Japanese fixture',current_date-30,'https://fixture.invalid/jp'),
      ('TCGdex','POKEMON_TCG','English','another-fixture','Unrelated set',current_date-30,'https://fixture.invalid/other')""")
    for ident,name,number in (('fixture-001','Alpha','001/100'),('fixture-002','Beta','002/100'),
                              ('fixture-003','Gamma','003/100'),('fixture-004','Historical','004/100')):
        await db.execute("""insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,
          name,card_number,rarity,image_url,source_url,number_key,finish,evidence)
          values('TCGdex','POKEMON_TCG','English',$1,'cache-fixture',$2,$3,'Common',
          'https://assets.tcgdex.net/'||$1||'.webp','https://fixture.invalid/'||$1,$4,'Normal',$5::jsonb)""",
          ident,name,number,str(int(number.split('/')[0]))+':/:100',json.dumps(dict(internal_note=PRIVATE)))
    await db.execute("""insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number)
      values('TCGdex','POKEMON_TCG','Japanese','fixture-001','cache-fixture','別のカード','001/100'),
       ('TCGdex','POKEMON_TCG','English','unrelated','another-fixture','Unrelated','999/100')""")
    await db.execute("""insert into tcg.reference_market_prices
      (provider,system_code,language,provider_id,market_value_minor,market_value_high_minor,
       pricing_updated_at,checked_at,expires_at,quotes)
      select 'TCGdex','POKEMON_TCG','English','fixture-001',100,100,now()-interval '1 hour',now(),now()+interval '1 day',
       jsonb_build_array(jsonb_build_object('source','TCGDEX_CARDMARKET','price_gbp_minor',100))""")
    await db.execute("""insert into tcg.reference_catalogue_prices
      (provider,system_code,language,provider_id,market_value_minor,market_value_high_minor,
       pricing_updated_at,checked_at,expires_at,quotes)
      select 'TCGdex','POKEMON_TCG','English','fixture-002',425,425,now()-interval '1 hour',now(),now()+interval '1 day',
       jsonb_build_array(jsonb_build_object('source','CARDMARKET_CATALOGUE','price_gbp_minor',425,
        'reference_identity',jsonb_build_object('name','Beta','set_id','cache-fixture','card_number','002/100','set_name','Fixture Set')))""")
    await db.execute("""insert into tcg.reference_market_prices
      (provider,system_code,language,provider_id,market_value_minor,market_value_high_minor,
       pricing_updated_at,checked_at,expires_at,quotes)
      select 'TCGdex','POKEMON_TCG','English','fixture-004',85,85,now()-interval '8 days',now(),now()+interval '1 day',
       jsonb_build_array(jsonb_build_object('source','TCGDEX_CARDMARKET','price_gbp_minor',85,
        'original_minor',100,'original_currency','EUR','fx_rate_to_gbp','0.85','fx_source','ECB_EURO_REFERENCE_RATES',
        'observed_at',now()-interval '8 days'))""")
    for ident,name,number in ((CANONICAL,'Alpha','001/100'),(SHARED,'Gamma','003/100')):
        await db.execute("""insert into tcg.catalogue_products
          values($1,'CARD','Pokemon',$2,'Fixture Set',$3,'Normal','Common','English',$4)""",ident,name,number,ACTOR_A)
        await db.execute("""insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status)
          values($1,'POKEMON_TCG','CARD','VERIFIED')""",ident)
        await db.execute("""insert into tcg.catalogue_market_snapshots
          (catalogue_id,identity_digest,basis_key,basis_condition,basis_language,market_value_minor,
           recommended_retail_minor,confidence,algorithm_version,oldest_sale_at,evidence_checked_at,
           calculation_day,evidence_digest,evidence)
          select id,md5(concat_ws(chr(31),product_type,game,name,set_name,card_number,variant,rarity,language)),
           'synthetic','Near Mint','English',$2,$2,0.8,'drop-rate-market-v4',now()-interval '10 days',
           now()-interval '1 hour',current_date,'synthetic',
           '{"method":"CATALOGUE_EBAY_V4","input_sale_count":5}'::jsonb
          from tcg.catalogue_products where id=$1""",ident,900 if ident==CANONICAL else 700)
    await db.execute("""insert into tcg.provider_catalogue_mappings
      (catalogue_id,source_provider,system_code,provider_language,provider_id,provider_entity_type,provider_variant_key,match_status)
      values($1,'TCGdex','POKEMON_TCG','English','fixture-001','CARD_PRINTING','','VERIFIED')""",CANONICAL)
    for index,(owner,status) in enumerate(((OWNER_A,'DRAFT'),(OWNER_A,'APPROVED'),(OWNER_B,'DRAFT'),(OWNER_B,'SOLD'))):
        await db.execute('insert into tcg.inventory_items values($1,$2,$3,$4,87654321,76543210,65432109,$5)',
                         UUID(f'50000000-0000-0000-0000-{index+1:012d}'),owner,CANONICAL,status,PRIVATE)
    await db.execute("""insert into tcg.media_assets(id,catalogue_id,owner_id,scope,side,media_kind,approval_status,
      rights_status,rights_tier,source_status,approved_at,public_source_url)
      values($1,$2,$3,'CANONICAL_CARD','FRONT','IMAGE','APPROVED','VERIFIED','STOREFRONT_ALLOWED','ACTIVE',now(),
      'https://fixture.invalid/approved.webp')""",MEDIA,CANONICAL,OWNER_A)
    await db.execute("insert into tcg.media_object_mirrors values($1,'https://fixture.invalid/approved.webp','drop-rate/media/fixture.webp')",MEDIA)
    await db.execute("""insert into tcg.reference_sealed_products values
      ('TCGdex','POKEMON_TCG','English','box-fixture','cache-fixture','Fixture Box','BOOSTER_BOX',
       'https://fixture.invalid/box.webp','https://fixture.invalid/box');
      insert into tcg.reference_sealed_market_prices values
      ('TCGdex','POKEMON_TCG','English','box-fixture',5000,5000,now(),'[]')""")


def rows_by_id(rows):
    return {row['provider_id']: row for row in rows}


async def integration_checks(db):
    from app.catalogue_r2_cache import (ReferenceScope, fetch_snapshot_source,
        parse_reference_snapshot, reference_scope, read_reference_snapshot,
        clear_reference_snapshot_cache)
    from app.object_storage import ObjectStorageError
    scope = ReferenceScope(**SCOPE_ARGS)
    print('PostgreSQL engine:', await db.fetchval('select version()'), flush=True)
    assert await db.fetchval("select encode(sha256(convert_to('abc','UTF8')),'hex')") == hashlib.sha256(b'abc').hexdigest()
    await seed(db)
    inventory_before = await db.fetchval("select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i")

    async def source(actor=ACTOR_A, which=scope):
        async with authorized(db,actor):
            return await fetch_snapshot_source(db,which,include_payload=True)

    def parsed(row, which=scope):
        raw = row['payload'].encode('utf-8')
        assert hashlib.sha256(raw).hexdigest() == row['source_sha256']
        assert len(raw) == row['raw_size_bytes']
        return parse_reference_snapshot(raw,which,row['source_sha256'],row['raw_size_bytes'])

    baseline = await source()
    assert baseline['card_count'] == 4 and baseline['set_count'] == 1
    assert baseline == await source(ACTOR_B), 'Owner changed a supposedly owner-free source snapshot'
    snapshot = parsed(baseline)
    for forbidden in (PRIVATE,str(OWNER_A),str(OWNER_B),str(ACTOR_A),str(ACTOR_B),'owned_quantity',
                      'acquisition_cost_minor','store_price_minor','87654321','76543210','65432109',
                      '別のカード','Unrelated set'):
        assert forbidden not in snapshot.payload, f'Private/out-of-scope field leaked: {forbidden}'
    async with authorized(db,None):
        assert await fetch_snapshot_source(db,scope,include_payload=True) is None, 'Anonymous SQL obtained source payload'

    async def displayed(cached,owner=OWNER_A,actor=ACTOR_A,which=scope,**options):
        query,params = product_query(owner_id=owner,provider=which.provider,system_code=which.system_code,
          language=which.language,set_id=which.set_id,product_type=options.pop('product_type','CARD'),
          sort=options.pop('sort','name'),limit=options.pop('limit',40),offset=options.pop('offset',0),
          reference_snapshot=cached,**options)
        rows = [dict(r) for r in await db.fetch(query,*params)]
        missing = [r for r in rows if r.get('market_value_minor') is None]
        shared = await read_shared_prices(db,missing)
        rows = [with_shared_price(r,shared) for r in rows]
        return await add_reference_history(db,rows)

    async def parity(cached=snapshot,owner=OWNER_A,actor=ACTOR_A,which=scope,**options):
        async with authorized(db,actor):
            direct = await displayed(None,owner,actor,which,**options)
            from_r2 = await displayed(cached,owner,actor,which,**options)
            assert direct == from_r2, ('Original/cached SQL mismatch',jsonable_encoder(direct),jsonable_encoder(from_r2))
            return rows_by_id(from_r2)

    # Only the object transport is a synthetic fixture. Fingerprint selection,
    # savepoint recovery, hash parsing, process caching and product SQL execute
    # the production reader against this actual PostgreSQL connection.
    class PrivateObjectTransport:
        def __init__(self, objects):
            self.objects = objects
            self.requested = []

        def read_verified_reference_snapshot(self, digest):
            self.requested.append(digest)
            if digest not in self.objects:
                raise ObjectStorageError('Synthetic private object unavailable')
            return self.objects[digest]

    transport = PrivateObjectTransport({snapshot.sha256:snapshot.payload.encode()})
    clear_reference_snapshot_cache()
    async with authorized(db):
        loaded = await read_reference_snapshot(db,scope,storage=transport)
        assert loaded is not None and loaded.origin == 'R2'
        assert await displayed(loaded) == await displayed(None)
    async with authorized(db,ACTOR_B):
        loaded = await read_reference_snapshot(db,scope,storage=transport)
        assert loaded is not None and loaded.origin == 'PROCESS'
        assert await displayed(loaded,OWNER_B,ACTOR_B) == await displayed(None,OWNER_B,ACTOR_B)
    assert transport.requested == [snapshot.sha256]
    async with authorized(db,None):
        assert await read_reference_snapshot(db,scope,storage=transport) is None
    assert transport.requested == [snapshot.sha256], 'Unauthorized caller attempted private object retrieval'

    for objects in ({},{snapshot.sha256:b'{"tampered":"source"}'}):
        clear_reference_snapshot_cache()
        async with authorized(db):
            assert await read_reference_snapshot(db,scope,storage=PrivateObjectTransport(objects)) is None
            assert rows_by_id(await displayed(None))['fixture-001']['market_value_minor'] == 900

    async def fail_fingerprint(connection, _scope, **_options):
        # A real database error aborts the savepoint, then the normal live query
        # must still succeed in the enclosing read-only API transaction.
        await connection.fetchval('select 1/0')

    clear_reference_snapshot_cache()
    async with authorized(db):
        with patch('app.catalogue_r2_cache.fetch_snapshot_source',fail_fingerprint):
            assert await read_reference_snapshot(db,scope,storage=transport) is None
        assert rows_by_id(await displayed(None))['fixture-001']['market_value_minor'] == 900

    # A process hit must still compare today's source digest before reusing an
    # object. Changing a field without changing timestamps forces a cache miss.
    async with authorized(db):
        assert await read_reference_snapshot(db,scope,storage=transport) is not None
    await db.execute("update tcg.reference_cards set image_url='https://assets.tcgdex.net/reader-repair.webp' where language='English' and provider_id='fixture-001'")
    async with authorized(db):
        assert await read_reference_snapshot(db,scope,storage=transport) is None
        assert rows_by_id(await displayed(None))['fixture-001']['image_url'].endswith('/reader-repair.webp')
    assert transport.requested[-1] != snapshot.sha256
    await db.execute("update tcg.reference_cards set image_url='https://assets.tcgdex.net/fixture-001.webp' where language='English' and provider_id='fixture-001'")
    clear_reference_snapshot_cache()

    for owner,actor,quantity in ((OWNER_A,ACTOR_A,2),(OWNER_B,ACTOR_B,1)):
        rows = await parity(owner=owner,actor=actor)
        assert rows['fixture-001']['owned_quantity'] == quantity
        assert rows['fixture-001']['market_value_minor'] == 900, 'Canonical sold value lost precedence'
        assert rows['fixture-001']['r2_object_key'] == 'drop-rate/media/fixture.webp'
        assert rows['fixture-002']['market_value_minor'] == 425
        assert rows['fixture-003']['market_value_minor'] == 700, 'Shared alias fallback not live'
        assert rows['fixture-004']['market_value_minor'] is None
        assert rows['fixture-004']['shared_price']['last_known_minor'] == 85
    foreign = await parity(owner=OWNER_B,actor=ACTOR_A)
    assert foreign['fixture-001']['owned_quantity'] == 0, 'Foreign owner count bypassed inventory RLS'
    # Owner state never enters the immutable shared input object. Its current
    # rows and current membership policies still govern every cached query.
    await db.execute("update tcg.inventory_items set status='SOLD' where owner_id=$1 and status='DRAFT'",OWNER_A)
    assert (await source())['source_sha256'] == baseline['source_sha256']
    assert (await parity())['fixture-001']['owned_quantity'] == 1
    await db.execute("update tcg.inventory_items set status='DRAFT' where owner_id=$1 and status='SOLD'",OWNER_A)
    await db.execute('update tcg.owner_memberships set active=false where user_id=$1',ACTOR_A)
    assert (await source())['source_sha256'] == baseline['source_sha256']
    assert (await parity())['fixture-001']['owned_quantity'] == 0
    await db.execute('update tcg.owner_memberships set active=true where user_id=$1',ACTOR_A)
    for sort in ('name_desc','newest','oldest','number'):
        await parity(sort=sort,limit=2,offset=1)

    # Default product-type queries retain live sealed rows, even though the
    # persisted input projection contains only card/set/direct-price relations.
    mixed = await parity(product_type='')
    assert mixed['box-fixture']['market_value_minor'] == 5000
    await db.execute("update tcg.reference_sealed_market_prices set market_value_minor=6000 where provider_id='box-fixture'")
    assert (await source())['source_sha256'] == baseline['source_sha256']
    assert (await parity(product_type=''))['box-fixture']['market_value_minor'] == 6000

    # No source-copy rebuild is required for live approval revocation.
    await db.execute('update tcg.media_assets set revoked_at=now() where id=$1',MEDIA)
    assert (await source())['source_sha256'] == baseline['source_sha256']
    assert (await parity())['fixture-001']['r2_object_key'] is None
    assert (await parity())['fixture-001']['fallback_image_url'] is None
    await db.execute('update tcg.media_assets set revoked_at=null where id=$1',MEDIA)

    # An extra verified canonical mapping makes an exact provider link ambiguous.
    await db.execute("""insert into tcg.catalogue_products values
      ($1,'CARD','Pokemon','Unrelated canonical','Different set','999','Normal','Common','English',$2)""",AMBIGUOUS,ACTOR_B)
    await db.execute("""insert into tcg.provider_catalogue_mappings
      (catalogue_id,source_provider,system_code,provider_language,provider_id,provider_entity_type,provider_variant_key,match_status)
      values($1,'TCGdex','POKEMON_TCG','English','fixture-001','CARD_PRINTING','','VERIFIED')""",AMBIGUOUS)
    assert (await source())['source_sha256'] == baseline['source_sha256']
    ambiguous = await parity()
    assert ambiguous['fixture-001']['catalogue_id'] is None and ambiguous['fixture-001']['owned_quantity'] == 0
    assert ambiguous['fixture-001']['market_value_minor'] == 100
    await db.execute('delete from tcg.provider_catalogue_mappings where catalogue_id=$1',AMBIGUOUS)
    await db.execute('delete from tcg.catalogue_products where id=$1',AMBIGUOUS)

    # An unpriced sibling must invalidate a shared singleton price immediately.
    await db.execute("""insert into tcg.catalogue_products values
      ($1,'CARD','Pokemon','Gamma','Fixture Set','003/100','Holofoil','Common','English',$2)""",AMBIGUOUS,ACTOR_B)
    assert (await source())['source_sha256'] == baseline['source_sha256']
    assert (await parity())['fixture-003']['market_value_minor'] is None
    await db.execute('delete from tcg.catalogue_products where id=$1',AMBIGUOUS)

    # Actual source content changes must invalidate despite fixed row counts and
    # unmodified refreshed_at/checked_at timestamps. Restore each fixture after.
    mutations = [
      ("update tcg.reference_cards set image_url='https://assets.tcgdex.net/repaired.webp' where language='English' and provider_id='fixture-001'",),
      ("update tcg.reference_market_prices set market_value_minor=110,market_value_high_minor=110 where provider_id='fixture-001'",),
      ("update tcg.reference_market_prices set quotes='[{\"source\":\"TCGDEX_CARDMARKET_VARIANT\",\"price_gbp_minor\":100}]' where provider_id='fixture-001'",),
      ("update tcg.reference_cards set name='Corrected identity' where language='English' and provider_id='fixture-002'",),
      ("delete from tcg.reference_cards where provider_id='fixture-003'",),
      ("insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number) values('TCGdex','POKEMON_TCG','English','new-printing','cache-fixture','New printing','100/100')",),
      ("update tcg.reference_sets set release_date=current_date+1 where language='English' and set_id='cache-fixture'",),
    ]
    for (sql,) in mutations:
        await db.execute('begin')
        try:
            await db.execute(sql)
            # Read through the restricted API role, within this synthetic write txn.
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)",str(ACTOR_A))
            changed = await fetch_snapshot_source(db,scope,include_payload=True)
            assert changed['source_sha256'] != baseline['source_sha256'], sql
            try:
                parse_reference_snapshot(snapshot.payload.encode(),scope,changed['source_sha256'],changed['raw_size_bytes'])
            except (ValueError,RuntimeError):
                pass
            else:
                raise AssertionError('Old snapshot accepted against changed source: '+sql)
            fresh = parsed(changed)
            assert await displayed(None) == await displayed(fresh), sql
        finally:
            await db.execute('rollback')

    # Both clock-driven price validity and refresh-needed state change with NO
    # database write, while the raw source fingerprint remains identical.
    await db.execute("""insert into tcg.reference_sets(provider,system_code,language,set_id,name,release_date)
      values('TCGdex','POKEMON_TCG','English','expiry-fixture','Expiry set',current_date-1);
      insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number)
      values('TCGdex','POKEMON_TCG','English','expiry-card','expiry-fixture','Expiry card','001');
      insert into tcg.reference_market_prices
      (provider,system_code,language,provider_id,market_value_minor,market_value_high_minor,
       pricing_updated_at,checked_at,expires_at,quotes)
      values('TCGdex','POKEMON_TCG','English','expiry-card',250,250,
       now()-interval '7 days'+interval '2 seconds',now(),now()+interval '2 seconds',
       '[{"source":"TCGDEX_CARDMARKET","price_gbp_minor":250}]')""")
    expiry_scope = ReferenceScope(**dict(SCOPE_ARGS,set_id='expiry-fixture'))
    expiry_source = await source(which=expiry_scope)
    expiry_snapshot = parsed(expiry_source,expiry_scope)
    early = await parity(cached=expiry_snapshot,which=expiry_scope)
    assert early['expiry-card']['market_value_minor'] == 250 and not early['expiry-card']['market_refresh_needed']
    await asyncio.sleep(2.15)
    assert (await source(which=expiry_scope))['source_sha256'] == expiry_source['source_sha256']
    late = await parity(cached=expiry_snapshot,which=expiry_scope)
    assert late['expiry-card']['market_value_minor'] is None and late['expiry-card']['market_refresh_needed']

    valid = dict(SCOPE_ARGS,product_type='CARD',owned='all',sort='name')
    assert reference_scope(**valid) == scope
    unsupported = (dict(q='Alpha'),dict(keys=[]),dict(keys=['x']),dict(slab_name='Alpha'),
                   dict(owned='owned'),dict(owned='not_owned'),dict(sort='value_desc'),dict(sort='value_asc'),
                   dict(product_type='SEALED'),dict(product_type='COMIC'),dict(provider=None),
                   dict(set_id=''),dict(system_code='COMICS'),dict(language=''))
    for change in unsupported:
        assert reference_scope(**(valid|change)) is None, change
        # Slab routing is guarded before product_query. All remaining cases
        # must also reject a caller attempting to supply a narrow snapshot.
        if 'slab_name' in change:
            continue
        arguments = dict(owner_id=OWNER_A,**(valid|change))
        try:
            product_query(**arguments,reference_snapshot=snapshot)
        except ValueError:
            pass
        else:
            raise AssertionError('Unsupported SQL scope accepted narrow snapshot: '+str(change))
        query,params = product_query(**arguments)
        async with authorized(db):
            await db.fetch(query,*params)
    for change in (dict(set_id='another-fixture'),dict(language='Japanese'),dict(provider='Different provider')):
        try:
            product_query(owner_id=OWNER_A,**(valid|change),reference_snapshot=snapshot)
        except ValueError:
            pass
        else:
            raise AssertionError('Mismatched exact scope accepted narrow snapshot: '+str(change))
    assert await db.fetchval("select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i") == inventory_before
    print('PASS: real PostgreSQL original/cached SQL parity, R2/process hits, missing/corrupt object and SQL-error fallback, RLS owner isolation, live shared/canonical/media/sealed overlays, raw-source invalidation, no-write clock expiry, unsupported scopes, and unchanged inventory')


async def main(pglite=False):
    if pglite:
        db = await PGliteConnection.open()
    else:
        dsn = os.environ['CATALOGUE_R2_CACHE_TEST_DSN']
        parsed_dsn = urlsplit(dsn)
        assert parsed_dsn.hostname in ('localhost','127.0.0.1') and parsed_dsn.path == '/catalogue_r2_cache_test', 'Refusing a non-disposable database'
        db = await asyncpg.connect(dsn,server_settings={'statement_timeout':'15000','TimeZone':'UTC'})
        await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), 'Refusing a nonempty database'
        await integration_checks(db)
    finally:
        await db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pglite',action='store_true')
    asyncio.run(main(parser.parse_args().pglite))
