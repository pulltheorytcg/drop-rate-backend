"""Disposable PostgreSQL proof for advisor-only RLS and FK-index changes.

This runner refuses non-loopback hosts, any other database, and nonempty fixture
schemas. It never connects to Supabase and contains no production credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
POLICY_MIGRATION = ROOT / "database/migrations/20261114120000_advisor_owner_rls_initplans.sql"
INDEX_MIGRATION = ROOT / "database/migrations/20261114121000_advisor_foreign_key_indexes.sql"
ROLLBACK = ROOT / "docs/ops/20261114_advisor_policy_rollback.sql"
POLICIES = {
    "own_action_required_access": ("action_required_items", "20260928211713_import_enrichment_action_queue.sql"),
    "own_enrichment_access": ("import_enrichment_items", "20260928211713_import_enrichment_action_queue.sql"),
    "own_asset_writes": ("media_assets", "20260925154423_media_assets_registry.sql"),
    "readable_assets": ("media_assets", "20260925154423_media_assets_registry.sql"),
}
INDEXES = {
    "action_required_items_resolved_by_user_idx": ("action_required_items", "resolved_by_user_id"),
    "import_enrichment_items_inventory_idx": ("import_enrichment_items", "inventory_id"),
    "media_assets_approved_by_user_fk_idx": ("media_assets", "approved_by_user_id"),
    "media_assets_created_by_user_fk_idx": ("media_assets", "created_by_user_id"),
    "owner_invites_created_by_owner_fk_idx": ("owner_invites", "created_by_owner_id"),
    "owner_invites_redeemed_owner_fk_idx": ("owner_invites", "redeemed_owner_id"),
    "reference_asking_prices_snapshot_fk_idx": ("reference_asking_prices", "snapshot_id"),
    "reference_sealed_products_system_code_fk_idx": ("reference_sealed_products", "system_code"),
    "reference_sets_system_code_fk_idx": ("reference_sets", "system_code"),
    "shopify_postage_actual_costs_owner_fk_idx": ("shopify_postage_actual_costs", "owner_id"),
    "shopify_shipping_profiles_created_by_user_fk_idx": ("shopify_shipping_profiles", "created_by_user_id"),
    "shopify_variant_pool_aliases_owner_fk_idx": ("shopify_variant_pool_aliases", "owner_id"),
}
TABLES = ("action_required_items", "import_enrichment_items", "media_assets")
A, B, INACTIVE, FOUNDER = (UUID(int=n) for n in (101, 102, 103, 104))
OA, OB, INVENTORY = (UUID(int=n) for n in (201, 202, 301))


def original_policy(name: str) -> str:
    table, filename = POLICIES[name]
    source = (ROOT / "database/migrations" / filename).read_text()
    pattern = rf"create policy {name}\s+on tcg\.{table}\b[^;]*;"
    matches = re.findall(pattern, source, flags=re.IGNORECASE)
    assert len(matches) == 1, f"Expected exactly one canonical original: {name}"
    return matches[0]


async def fixture(db: asyncpg.Connection) -> None:
    assert await db.fetchval("select current_database()") == "advisor_test"
    assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname in ('tcg','auth'))"), "Use a fresh disposable database"
    await db.execute("""
        create schema auth; create schema tcg;
        create role tcg_api nologin nosuperuser nobypassrls;
        create role anon nologin; create role authenticated nologin;
        create role service_role nologin; create role tcg_auditor nologin;
        grant usage on schema tcg to tcg_api;
        create table auth.users(id uuid primary key);
        create table tcg.owners(id uuid primary key);
        create table tcg.owner_memberships(owner_id uuid references tcg.owners(id),
            user_id uuid references auth.users(id), active boolean not null,
            primary key(owner_id,user_id));
        grant select on tcg.owner_memberships to tcg_api;
        create table tcg.inventory_items(id uuid primary key);
        create table tcg.collectible_systems(code text primary key);
        create table tcg.reference_asking_history(snapshot_id uuid primary key);
        create table tcg.action_required_items(id uuid primary key,
            owner_id uuid not null references tcg.owners(id), payload text not null default 'original',
            resolved_by_user_id uuid references auth.users(id));
        create table tcg.import_enrichment_items(id uuid primary key,
            owner_id uuid not null references tcg.owners(id), payload text not null default 'original',
            inventory_id uuid not null references tcg.inventory_items(id));
        create table tcg.media_assets(id uuid primary key,
            owner_id uuid not null references tcg.owners(id), payload text not null default 'original',
            scope text not null check(scope in ('CANONICAL_CARD','INVENTORY_ITEM')),
            created_by_user_id uuid not null references auth.users(id),
            approved_by_user_id uuid references auth.users(id));
        create table tcg.owner_invites(id uuid primary key,
            created_by_owner_id uuid not null references tcg.owners(id),
            redeemed_owner_id uuid references tcg.owners(id));
        create table tcg.reference_asking_prices(provider text, system_code text,
            language text, provider_id text,
            snapshot_id uuid not null references tcg.reference_asking_history(snapshot_id),
            primary key(provider,system_code,language,provider_id));
        create table tcg.reference_sets(provider text,
            system_code text references tcg.collectible_systems(code), language text, set_id text,
            primary key(provider,system_code,language,set_id));
        create table tcg.reference_sealed_products(provider text,
            system_code text references tcg.collectible_systems(code), language text, provider_id text,
            set_id text not null, primary key(provider,system_code,language,provider_id),
            foreign key(provider,system_code,language,set_id)
                references tcg.reference_sets(provider,system_code,language,set_id));
        create index reference_sealed_sets_idx on tcg.reference_sealed_products(provider,system_code,language,set_id);
        create table tcg.shopify_postage_actual_costs(id uuid primary key, order_id uuid,
            owner_id uuid not null references tcg.owners(id));
        create index shopify_postage_actual_costs_order_idx on tcg.shopify_postage_actual_costs(order_id,owner_id);
        create table tcg.shopify_shipping_profiles(id uuid primary key,
            created_by_user_id uuid not null references auth.users(id));
        create table tcg.shopify_variant_pool_aliases(legacy_variant_gid text primary key,
            inventory_id uuid not null references tcg.inventory_items(id) on delete restrict,
            owner_id uuid not null references tcg.owners(id) on delete restrict);
        create index shopify_variant_pool_alias_inventory_idx on tcg.shopify_variant_pool_aliases(inventory_id,owner_id);
        create table tcg.marketing_specialist_jobs(id uuid, revision integer,
            created_by uuid not null references auth.users(id),
            primary key(id,revision), unique(id,revision,created_by));
        create table tcg.marketing_specialist_runs(id uuid primary key,
            job_id uuid not null, revision integer not null, stage text not null,
            created_by uuid not null, started_at timestamptz not null default now(),
            unique(job_id,revision,stage), foreign key(job_id,revision,created_by)
                references tcg.marketing_specialist_jobs(id,revision,created_by));
        create index marketing_specialist_runs_actor_time on tcg.marketing_specialist_runs(created_by,started_at);
    """)
    await db.executemany("insert into auth.users values($1)", [(u,) for u in (A, B, INACTIVE, FOUNDER)])
    await db.executemany("insert into tcg.owners values($1)", [(OA,), (OB,)])
    await db.executemany("insert into tcg.owner_memberships values($1,$2,$3)", [(OA,A,True),(OB,B,True),(OA,INACTIVE,False)])
    await db.execute("insert into tcg.inventory_items values($1)", INVENTORY)
    for table in TABLES:
        await db.execute(f"alter table tcg.{table} enable row level security; alter table tcg.{table} force row level security")
        await db.execute(f"revoke all on tcg.{table} from public,anon,authenticated,service_role; grant select,insert,update on tcg.{table} to tcg_api")
        await db.execute(f"create policy admin_access on tcg.{table} for all to postgres using(true) with check(true)")
    for policy in POLICIES:
        await db.execute(original_policy(policy))
    await db.execute("create policy unrelated_false_read on tcg.action_required_items for select to tcg_api using(false)")
    for n, owner in enumerate((OA, OB), 1):
        await db.execute("insert into tcg.action_required_items(id,owner_id) values($1,$2)", UUID(int=n), owner)
        await db.execute("insert into tcg.import_enrichment_items(id,owner_id,inventory_id) values($1,$2,$3)", UUID(int=n), owner, INVENTORY)
        await db.execute("insert into tcg.media_assets(id,owner_id,scope,created_by_user_id) values($1,$2,'INVENTORY_ITEM',$3)", UUID(int=n), owner, A if owner==OA else B)
        await db.execute("insert into tcg.media_assets(id,owner_id,scope,created_by_user_id) values($1,$2,'CANONICAL_CARD',$3)", UUID(int=n+2), owner, A if owner==OA else B)


async def policies(db: asyncpg.Connection) -> list[dict]:
    return [dict(row) for row in await db.fetch("""
        select schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check
        from pg_policies where schemaname='tcg' order by tablename,policyname
    """)]


async def security_metadata(db: asyncpg.Connection) -> dict:
    return {
        "grants": [tuple(row) for row in await db.fetch("select table_name,grantee,privilege_type,is_grantable from information_schema.table_privileges where table_schema='tcg' order by 1,2,3,4")],
        "rls": [tuple(row) for row in await db.fetch("select relname,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='tcg'::regnamespace and relkind='r' order by 1")],
        "roles": [tuple(row) for row in await db.fetch("select rolname,rolsuper,rolbypassrls from pg_roles where rolname in ('tcg_api','anon','authenticated','service_role') order by 1")],
        "foreign_keys": [tuple(row) for row in await db.fetch("select conrelid::regclass::text,conname,pg_get_constraintdef(oid) from pg_constraint where connamespace='tcg'::regnamespace and contype='f' order by 1,2")],
    }


async def data_snapshot(db: asyncpg.Connection) -> dict:
    return {table: await db.fetchval(f"select jsonb_agg(to_jsonb(t) order by id)::text from tcg.{table} t") for table in TABLES}


async def attempt(db: asyncpg.Connection, sql: str, *args) -> str:
    savepoint = db.transaction()
    await savepoint.start()
    try:
        result = await db.execute(sql, *args)
    except asyncpg.PostgresError as exc:
        return exc.sqlstate
    finally:
        await savepoint.rollback()
    return result


async def actor_matrix(dsn: str) -> dict:
    db = await asyncpg.connect(dsn)
    results = {}
    try:
        await db.execute("set role tcg_api")
        # The first case has never set the GUC on this connection. Subsequent
        # statements reuse this same backend to detect leaked prepared plans.
        prepared = {table: await db.prepare(f"select id from tcg.{table} order by id") for table in TABLES}
        # FOUNDER is an identity without membership in this focused fixture.
        # Existing production founder-only media policies are not removed or
        # modeled as globally denied by this four-policy equivalence test.
        actors = [("missing",None), ("empty",""), ("owner_a",str(A)), ("owner_b",str(B)), ("inactive",str(INACTIVE)), ("founder_without_membership",str(FOUNDER)), ("malformed","not-a-uuid"), ("owner_a_again",str(A))]
        for label, actor in actors:
            transaction = db.transaction()
            await transaction.start()
            try:
                if actor is not None:
                    await db.execute("select set_config('tcg.user_id',$1,true)", actor)
                values = {}
                for table in TABLES:
                    nested = db.transaction(); await nested.start()
                    try:
                        values[table] = [str(row['id']) for row in await prepared[table].fetch()]
                    except asyncpg.PostgresError as exc:
                        values[table] = exc.sqlstate
                    finally:
                        await nested.rollback()
                if label == "malformed":
                    assert values["action_required_items"] == "22P02"
                    assert values["import_enrichment_items"] == "22P02"
                    assert values["media_assets"] == "22P02"
                else:
                    own_id = 1 if actor == str(A) else 2 if actor == str(B) else None
                    expected = [] if own_id is None else [str(UUID(int=own_id))]
                    assert values["action_required_items"] == expected
                    assert values["import_enrichment_items"] == expected
                    media = sorted(expected + [str(UUID(int=3)), str(UUID(int=4))])
                    assert values["media_assets"] == media
                    for table in TABLES:
                        own_owner = OB if actor == str(B) else OA
                        foreign_owner = OA if actor == str(B) else OB
                        own_row = UUID(int=own_id or 1)
                        other_row = UUID(int=1 if own_id == 2 else 2)
                        if table == "media_assets":
                            insert = "insert into tcg.media_assets(id,owner_id,scope,created_by_user_id) values($1,$2,'INVENTORY_ITEM',$3)"
                            args = (UUID(int=900), own_owner, A)
                        elif table == "import_enrichment_items":
                            insert = "insert into tcg.import_enrichment_items(id,owner_id,inventory_id) values($1,$2,$3)"
                            args = (UUID(int=900), own_owner, INVENTORY)
                        else:
                            insert = "insert into tcg.action_required_items(id,owner_id) values($1,$2)"
                            args = (UUID(int=900), own_owner)
                        outcomes = {
                            "own_insert": await attempt(db, insert, *args),
                            "foreign_insert": await attempt(db, insert, args[0],foreign_owner,*args[2:]),
                            "own_update": await attempt(db, f"update tcg.{table} set payload='changed' where id=$1",own_row),
                            "foreign_update": await attempt(db, f"update tcg.{table} set payload='changed' where id=$1",other_row),
                            "transfer_owner": await attempt(db, f"update tcg.{table} set owner_id=$1 where id=$2",foreign_owner,own_row),
                            "delete": await attempt(db, f"delete from tcg.{table} where id=$1",own_row),
                        }
                        assert outcomes == {
                            "own_insert":"INSERT 0 1" if own_id else "42501",
                            "foreign_insert":"42501",
                            "own_update":"UPDATE 1" if own_id else "UPDATE 0",
                            "foreign_update":"UPDATE 0",
                            "transfer_owner":"42501" if own_id else "UPDATE 0",
                            "delete":"42501",
                        }, (label,table,outcomes)
                        values[table+"_writes"] = outcomes
                    canonical_own = UUID(int=4 if own_id == 2 else 3)
                    canonical_other = UUID(int=3 if own_id == 2 else 4)
                    canonical = {
                        "own_update": await attempt(db,"update tcg.media_assets set payload='changed' where id=$1",canonical_own),
                        "foreign_update": await attempt(db,"update tcg.media_assets set payload='changed' where id=$1",canonical_other),
                        "own_insert": await attempt(db,"insert into tcg.media_assets(id,owner_id,scope,created_by_user_id) values($1,$2,'CANONICAL_CARD',$3)",UUID(int=901),OB if own_id==2 else OA,A),
                        "foreign_insert": await attempt(db,"insert into tcg.media_assets(id,owner_id,scope,created_by_user_id) values($1,$2,'CANONICAL_CARD',$3)",UUID(int=901),OA if own_id==2 else OB,A),
                    }
                    assert canonical == {"own_update":"UPDATE 1" if own_id else "UPDATE 0", "foreign_update":"UPDATE 0", "own_insert":"INSERT 0 1" if own_id else "42501", "foreign_insert":"42501"}
                    values["canonical_writes"] = canonical
                results[label] = values
            finally:
                await transaction.rollback()
        for role in ("anon","authenticated","service_role"):
            await db.execute("reset role"); await db.execute(f"set role {role}")
            for table in TABLES:
                try:
                    await db.fetchval(f"select count(*) from tcg.{table}")
                except asyncpg.InsufficientPrivilegeError:
                    pass
                else:
                    raise AssertionError(f"Unexpected direct read grant to {role}")
        return results
    finally:
        await db.close()


async def apply(db: asyncpg.Connection, path: Path) -> None:
    try:
        await db.execute(path.read_text())
    except BaseException:
        await db.execute("rollback")
        raise


async def must_fail(db: asyncpg.Connection, path: Path) -> str:
    try:
        await apply(db,path)
    except asyncpg.PostgresError as exc:
        return exc.sqlstate
    raise AssertionError(f"Migration unexpectedly accepted drift: {path.name}")


async def index_snapshot(db: asyncpg.Connection) -> list[tuple]:
    return [tuple(row) for row in await db.fetch("""select t.relname,i.relname,pg_get_indexdef(i.oid),x.indisvalid,x.indisready
        from pg_index x join pg_class i on i.oid=x.indexrelid join pg_class t on t.oid=x.indrelid
        where t.relnamespace='tcg'::regnamespace order by 1,2""")]


async def plan_proof(dsn: str) -> None:
    db = await asyncpg.connect(dsn)
    try:
        await db.execute("set role tcg_api")
        await db.execute("select set_config('tcg.user_id',$1,false)",str(A))
        for table in TABLES:
            raw = await db.fetchval(f"explain (analyze,format json) select id from tcg.{table} order by id")
            plan = json.loads(raw)
            def initplans(node):
                if isinstance(node,dict):
                    return ([node] if str(node.get('Subplan Name','')).startswith('InitPlan') else []) + [item for value in node.values() for item in initplans(value)]
                if isinstance(node,list):
                    return [item for value in node for item in initplans(value)]
                return []
            nodes = initplans(plan)
            assert nodes and all(node['Actual Loops'] <= 1 for node in nodes), table
    finally:
        await db.close()


async def main() -> None:
    dsn = os.environ["SUPABASE_ADVISOR_TEST_DSN"]
    url = urlsplit(dsn)
    assert url.scheme in ("postgres","postgresql") and url.hostname in ("localhost","127.0.0.1")
    assert url.path == "/advisor_test" and not url.query and not url.fragment, "Disposable local DSN only"
    db = await asyncpg.connect(dsn)
    lock_db = None
    try:
        await fixture(db)
        original_policies = await policies(db)
        original_security = await security_metadata(db)
        original_data = await data_snapshot(db)
        original_indexes = await index_snapshot(db)
        before = await actor_matrix(dsn)

        await db.execute("alter policy readable_assets on tcg.media_assets using(true)")
        drifted = await policies(db)
        await must_fail(db,POLICY_MIGRATION)
        assert await policies(db) == drifted, "Drift rejection must be atomic"
        await db.execute("drop policy readable_assets on tcg.media_assets")
        await db.execute(original_policy("readable_assets"))
        assert await policies(db) == original_policies

        # Whitespace inside a quoted SQL literal is semantic, not formatting.
        # A guard that strips every whitespace character accidentally accepts
        # these different GUC keys, NULLIF sentinels, or canonical scope values.
        literal_drifts = (
            ("own_action_required_access", "'tcg.user_id'", "'tcg.user_id '"),
            ("own_action_required_access", ",''", ",' '"),
            ("readable_assets", "'CANONICAL_CARD'", "'CANONICAL_CARD '"),
        )
        for policy, old_literal, changed_literal in literal_drifts:
            table = POLICIES[policy][0]
            original = original_policy(policy)
            changed = original.replace(old_literal,changed_literal)
            assert changed != original
            await db.execute(f"drop policy {policy} on tcg.{table}")
            await db.execute(changed)
            drifted = await policies(db)
            for migration in (POLICY_MIGRATION,ROLLBACK):
                await must_fail(db,migration)
                assert await policies(db) == drifted, "Literal drift must fail without policy changes"
            await db.execute(f"drop policy {policy} on tcg.{table}")
            await db.execute(original)
            assert await policies(db) == original_policies

        # A held conflicting lock proves the real server enforces migration's
        # lock timeout. The fixture connection keeps it until the assertion ends.
        lock_db = await asyncpg.connect(dsn)
        await lock_db.execute("begin; lock table tcg.action_required_items in access exclusive mode")
        started = time.monotonic()
        try:
            assert await must_fail(db,POLICY_MIGRATION) == "55P03"
            assert 1.0 <= time.monotonic()-started < 8.0
        finally:
            await lock_db.execute("rollback"); await lock_db.close(); lock_db=None
        assert await policies(db) == original_policies

        await apply(db,POLICY_MIGRATION)
        updated = await policies(db)
        def unchanged_shape(rows):
            return [{k:v for k,v in row.items() if k not in ('qual','with_check')} for row in rows]
        assert unchanged_shape(updated) == unchanged_shape(original_policies)
        assert [p for p in updated if p['policyname'] not in POLICIES] == [p for p in original_policies if p['policyname'] not in POLICIES]
        assert await security_metadata(db) == original_security
        assert await actor_matrix(dsn) == before
        assert await data_snapshot(db) == original_data
        await plan_proof(dsn)
        await apply(db,POLICY_MIGRATION)
        assert await policies(db) == updated, "Policy reapplication must be idempotent"

        # CREATE INDEX takes SHARE. Its lock must conflict with our guard/build
        # lock so parallel DDL cannot race the equivalent-index preflight.
        lock_db = await asyncpg.connect(dsn)
        await lock_db.execute("begin; lock table tcg.action_required_items in share mode")
        started = time.monotonic()
        try:
            assert await must_fail(db,INDEX_MIGRATION) == "55P03"
            assert 1.0 <= time.monotonic()-started < 8.0
        finally:
            await lock_db.execute("rollback"); await lock_db.close(); lock_db=None
        assert await index_snapshot(db) == original_indexes

        # Conflict at the last target proves that the first eleven creations
        # roll back together; testing only the first target cannot prove that.
        conflict = "shopify_variant_pool_aliases_owner_fk_idx"
        await db.execute(f"create index {conflict} on tcg.shopify_variant_pool_aliases(inventory_id)")
        conflict_snapshot = await index_snapshot(db)
        await must_fail(db,INDEX_MIGRATION)
        assert await index_snapshot(db) == conflict_snapshot, "Index drift rejection must be atomic"
        await db.execute(f"drop index tcg.{conflict}")
        await apply(db,INDEX_MIGRATION)
        indexes_after = await index_snapshot(db)
        for name,(table,column) in INDEXES.items():
            row = await db.fetchrow("""select x.indisvalid,x.indisready,x.indisunique,x.indpred is null as unfiltered,
                x.indexprs is null as plain,x.indnkeyatts,am.amname,
                array(select a.attname from unnest(x.indkey) with ordinality k(attnum,n)
                    join pg_attribute a on a.attrelid=x.indrelid and a.attnum=k.attnum order by k.n) as columns,
                exists(select 1 from pg_constraint f where f.conrelid=x.indrelid and f.contype='f'
                    and f.conkey=array[(select attnum from pg_attribute where attrelid=x.indrelid and attname=$3)]::smallint[]) as covers_fk
                from pg_index x join pg_class i on i.oid=x.indexrelid join pg_class t on t.oid=x.indrelid
                join pg_am am on am.oid=i.relam where i.relnamespace='tcg'::regnamespace and i.relname=$1 and t.relname=$2""",name,table,column)
            assert row and row['indisvalid'] and row['indisready'] and not row['indisunique']
            assert row['unfiltered'] and row['plain'] and row['indnkeyatts']==1 and row['columns']==[column] and row['amname']=='btree' and row['covers_fk'], name
        assert len(indexes_after) == len(original_indexes)+12
        await apply(db,INDEX_MIGRATION)
        assert await index_snapshot(db) == indexes_after
        # Equivalent differently named leading-column coverage must be reused,
        # even when it has another key column. IF NOT EXISTS alone misses this.
        reused = "action_required_items_resolved_by_user_idx"
        await db.execute(f"drop index tcg.{reused}")
        await db.execute("create index fixture_equivalent_fk_cover on tcg.action_required_items(resolved_by_user_id,id)")
        alternative = await index_snapshot(db)
        await apply(db,INDEX_MIGRATION)
        assert await index_snapshot(db) == alternative
        assert not await db.fetchval("select to_regclass('tcg.action_required_items_resolved_by_user_idx') is not null")
        await db.execute("drop index tcg.fixture_equivalent_fk_cover")
        await apply(db,INDEX_MIGRATION)
        assert await index_snapshot(db) == indexes_after
        assert [r for r in original_indexes if r[0]=='marketing_specialist_runs'] == [r for r in indexes_after if r[0]=='marketing_specialist_runs']
        assert await policies(db) == updated
        assert await security_metadata(db) == original_security
        assert await data_snapshot(db) == original_data
        assert await actor_matrix(dsn) == before

        await apply(db,ROLLBACK)
        assert await policies(db) == original_policies
        assert await actor_matrix(dsn) == before
        assert await index_snapshot(db) == indexes_after, "Policy rollback must not remove indexes"
        assert await security_metadata(db) == original_security
        assert await data_snapshot(db) == original_data
        print(json.dumps({"status":"DISPOSABLE_POSTGRES_ADVISOR_PASSED", "policy_count":4,
            "valid_fk_indexes":12,"actor_cases_before_after_and_rollback":8,
            "prepared_actor_switch":True,"initplan_once_per_statement":True,
            "drift_rejection_atomic":True,"real_lock_timeout":True,"rollback_equal_original":True,
            "omitted_marketing_indexes_unchanged":True,"production_connections":0}))
    finally:
        if lock_db is not None:
            await lock_db.execute("rollback"); await lock_db.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
