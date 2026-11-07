"""Native PostgreSQL 17 integration proof in a fresh localhost-only database.

Applies the real bookmark and R2-first migrations. Authentication/legacy tables
are a minimal fixture with real owner RLS, not production data. R2 is an in-memory
byte store: this script cannot fetch providers, write cloud objects or deploy.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app import r2_first_catalogue as codec
from app import r2_first_import as publisher
from app import r2_first_service as service
from app.db import _init_connection, user_connection


ROOT = Path(__file__).resolve().parents[1]
ADMIN = UUID("00000000-0000-0000-0000-000000000001")
ADMIN_B = UUID("00000000-0000-0000-0000-000000000002")
SELLER = UUID("00000000-0000-0000-0000-000000000003")
OUTSIDER = UUID("00000000-0000-0000-0000-000000000004")
UNROSTERED = UUID("00000000-0000-0000-0000-000000000005")
SELLER_OWNER = UUID("10000000-0000-0000-0000-000000000003")
ADMIN_OWNER = UUID("10000000-0000-0000-0000-000000000001")
PROVIDER = "ygoprodeck"
SYSTEM = "YUGIOH"
LANGUAGE = "English"
SCOPE = (PROVIDER, SYSTEM, LANGUAGE)
KEY = codec.stable_key(*SCOPE, "fixture-1")
OTHER_KEY = codec.stable_key(*SCOPE, "fixture-2")


class PrivateR2Fixture:
    def __init__(self):
        self.objects = {}
        self.reads = 0

    def put_verified_reference_snapshot(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        self.objects[digest] = raw
        return {"verified": True, "sha256": digest}

    def read_verified_reference_snapshot(self, digest):
        self.reads += 1
        return self.objects[digest]


async def snapshot(store, version):
    rows = [{"provider": PROVIDER, "system_code": SYSTEM, "language": LANGUAGE,
             "provider_id": f"fixture-{number}", "product_type": "CARD",
             "name": f"{'Alpha' if number == 1 else 'Beta' if number == 2 else 'Future'} card v{version}",
             "set_id": "1" if number < 3 else "99", "set_name": "Released fixture" if number < 3 else "Future fixture",
             "card_number": str(number), "rarity": "Rare", "finish": None,
             "release_date": "2020-01-01" if number < 3 else "2099-01-01",
             "source_url": "https://db.ygoprodeck.com/api/v7/cardinfo.php"} for number in (1, 2, 3)]
    bundle = codec.prepare_catalogue(rows, provider=PROVIDER, system_code=SYSTEM,
        language=LANGUAGE, source_url=rows[0]["source_url"], source_revision=f"fixture-v{version}",
        permission_ref="https://ygoprodeck.com/api-guide/")
    await codec.upload_and_verify(bundle, store)
    return await codec.load_catalogue(await codec.load_manifest(bundle.manifest_digest, store), store)


async def expect_sql_error(pool, actor, sql, *args, sqlstate="42501"):
    try:
        async with user_connection(pool, actor, "r2-first-denial-test") as connection:
            await connection.execute(sql, *args)
    except asyncpg.PostgresError as exc:
        assert exc.sqlstate == sqlstate, (type(exc).__name__, exc.sqlstate, sqlstate)
    else:
        raise AssertionError("Expected PostgreSQL refusal")


async def expect_http(status, operation):
    try:
        await operation
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, status)
    else:
        raise AssertionError(f"Expected HTTP {status}")


async def seed(admin):
    await admin.execute("""
        create schema auth; create schema tcg; create schema tcg_private;
        create role anon nologin nosuperuser nobypassrls;
        create role authenticated nologin nosuperuser nobypassrls;
        create role service_role nologin nosuperuser nobypassrls;
        create role tcg_api nologin nosuperuser nobypassrls;
        create table auth.users(id uuid primary key);
        create table tcg.owners(id uuid primary key,display_name text not null,
            owner_type text not null,active boolean not null,founder_slot integer);
        create table tcg.owner_memberships(id uuid primary key default gen_random_uuid(),
            user_id uuid not null references auth.users(id), owner_id uuid not null references tcg.owners(id),
            role text not null,active boolean not null,created_at timestamptz default now());
        create table tcg.founder_roster(user_id uuid primary key,founder_slot integer not null);
        create function tcg.current_user_id() returns uuid language sql stable as
            $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
        create function tcg.current_owner_id() returns uuid language sql stable as
            $$select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$;
        create function tcg.current_access_role() returns text language sql stable as
            $$select m.role from tcg.owner_memberships m join tcg.owners o on o.id=m.owner_id
              where m.user_id=tcg.current_user_id() and m.active and o.active limit 1$$;
        create function tcg.is_platform_admin() returns boolean language sql stable as
            $$select exists(select 1 from tcg.owner_memberships m join tcg.owners o on o.id=m.owner_id
              join tcg.founder_roster r on r.user_id=m.user_id and r.founder_slot=o.founder_slot
              where m.user_id=tcg.current_user_id() and m.active and o.active
                and m.role='PLATFORM_ADMIN' and o.owner_type='FOUNDER')$$;
        alter table tcg.owners enable row level security;
        alter table tcg.owners force row level security;
        alter table tcg.owner_memberships enable row level security;
        alter table tcg.owner_memberships force row level security;
        create policy own_membership on tcg.owner_memberships for select to tcg_api
            using(user_id=(select tcg.current_user_id()));
        create policy own_owner on tcg.owners for select to tcg_api
            using(active and id=(select tcg.current_owner_id()));
        create table tcg.collectible_systems(code text primary key);
        insert into tcg.collectible_systems values ('YUGIOH'),('DISNEY_LORCANA'),('POKEMON_TCG');
        create table tcg.catalogue_products(id uuid primary key default gen_random_uuid(),
            identity_key text unique not null,product_type text not null,game text not null,
            name text not null,set_name text not null,card_number text,variant text not null,
            rarity text not null,language text,created_at timestamptz default now());
        alter table tcg.catalogue_products enable row level security;
        alter table tcg.catalogue_products force row level security;
        create policy catalogue_read on tcg.catalogue_products for select to tcg_api
            using(exists(select 1 from tcg.owners));
        create policy catalogue_insert on tcg.catalogue_products for insert to tcg_api
            with check(exists(select 1 from tcg.owners));
        create table tcg.inventory_items(id uuid primary key default gen_random_uuid(),
            owner_id uuid not null references tcg.owners(id),catalogue_id uuid not null references tcg.catalogue_products(id),
            status text not null,market_value_minor bigint,acquisition_cost_minor bigint,
            store_price_minor bigint,private_notes text,
            grading_company text,grade text,certificate_number text);
        alter table tcg.inventory_items enable row level security;
        alter table tcg.inventory_items force row level security;
        create policy own_inventory_read on tcg.inventory_items for select to tcg_api
            using(owner_id=(select tcg.current_owner_id()));
        create policy own_inventory_insert on tcg.inventory_items for insert to tcg_api
            with check(owner_id=(select tcg.current_owner_id()));
        -- A production-shape, private owner-scoped photo entitlement fixture.
        -- Only tcg_api SELECT is needed: DR104 never uploads or approves media.
        create table tcg.media_assets (
            id uuid primary key default gen_random_uuid(),
            inventory_id uuid not null references tcg.inventory_items(id),
            owner_id uuid not null references tcg.owners(id),
            scope text, media_kind text, side text, source_type text,
            rights_tier text,rights_status text,approval_status text,
            source_status text,revoked_at timestamptz,shopify_file_status text,
            shopify_cdn_url text,public_source_url text,capture_context text
        );
        alter table tcg.media_assets enable row level security;
        alter table tcg.media_assets force row level security;
        create policy own_photo_read on tcg.media_assets for select to tcg_api
            using(owner_id=(select tcg.current_owner_id()));
        grant select on tcg.media_assets to tcg_api;
        create table tcg.reference_cards(provider text,provider_id text,name text);
        insert into tcg.reference_cards values('legacy','unchanged','Existing catalogue stays in SQL');
        grant usage on schema tcg,tcg_private to tcg_api;
        grant select on tcg.owners,tcg.owner_memberships,tcg.founder_roster,tcg.collectible_systems to tcg_api;
        grant select,insert on tcg.catalogue_products,tcg.inventory_items to tcg_api;
    """)
    await admin.executemany("insert into auth.users values($1)", [(actor,) for actor in (ADMIN, ADMIN_B, SELLER, OUTSIDER, UNROSTERED)])
    owners = [(ADMIN_OWNER, "Founder A", "FOUNDER", 1),
              (UUID("10000000-0000-0000-0000-000000000002"), "Founder B", "FOUNDER", 2),
              (SELLER_OWNER, "Seller", "CONSIGNOR", None),
              (UUID("10000000-0000-0000-0000-000000000005"), "Not a founder", "CONSIGNOR", None)]
    await admin.executemany("insert into tcg.owners values($1,$2,$3,true,$4)", owners)
    await admin.executemany("insert into tcg.owner_memberships(user_id,owner_id,role,active) values($1,$2,$3,true)",
        [(ADMIN, owners[0][0], "PLATFORM_ADMIN"), (ADMIN_B, owners[1][0], "PLATFORM_ADMIN"),
         (SELLER, SELLER_OWNER, "OWNER"), (UNROSTERED, owners[3][0], "PLATFORM_ADMIN")])
    await admin.executemany("insert into tcg.founder_roster values($1,$2)", [(ADMIN, 1), (ADMIN_B, 2)])
    await admin.execute((ROOT / "database/migrations/20261103143718_catalogue_saved_references.sql").read_text())
    await admin.execute((ROOT / "database/migrations/20261103222018_r2_first_catalogue_registry.sql").read_text())


async def run_checks(admin, pool):
    store = PrivateR2Fixture()
    snapshots = []

    # The production CHECK hashes PostgreSQL's compact JSON-array encoding.
    # Prove it agrees with the actual Python key codec, including code points
    # that should remain distinct rather than silently normalizing identities.
    provider_ids = (
        "fixture-1", "a:b/c", "caf\u00e9/\u5fc3", "cafe\u0301", 'quoted "printing"',
        "back\\slash", "\U0001f0cf/foil", "a\u2028b",
    )
    for provider_id in provider_ids:
        actual = await admin.fetchval("""select 'x:' || encode(sha256(convert_to(
            array_to_json($1::text[])::text,'UTF8')),'hex')""", [*SCOPE, provider_id])
        assert actual == codec.stable_key(*SCOPE, provider_id)
    assert codec.stable_key(*SCOPE, "caf\u00e9") != codec.stable_key(*SCOPE, "cafe\u0301")

    async def fresh(version):
        value = await snapshot(store, version)
        snapshots.append(value)
        return value

    async def publication():
        return await admin.fetchrow("select * from tcg_private.r2_first_catalogue_publications where provider=$1 and system_code=$2 and language=$3", *SCOPE)

    async def audit_count():
        return await admin.fetchval("select count(*) from tcg_private.r2_first_catalogue_events")

    async def warm():
        current = dict(await publication())
        if current["manifest_sha256"] not in service._cache:
            await service._load(current, store)
        assert current["manifest_sha256"] in service._cache

    async def selected(actor, key=KEY):
        async with user_connection(pool, actor, "r2-first-select-fixture") as connection:
            item = await service.resolve(connection, key)
            assert item is not None
            row = await service.materialize(connection, item)
            return dict(row)

    try:
        first = await fresh(1)
        for actor in (SELLER, OUTSIDER, UNROSTERED):
            await expect_http(403, publisher.publish_verified(pool, actor, first))
        assert await publication() is None and await audit_count() == 0
        await publisher.publish_verified(pool, ADMIN, first)
        current = await publication()
        assert current["generation"] == 1 and current["published_by"] == ADMIN
        assert current["record_count"] == 3 and current["released_record_count"] == 2
        assert current["set_count"] == 1 and current["raw_bytes"] == first.manifest["raw_bytes"]
        assert current["manifest_sha256"] == first.manifest_digest
        event = await admin.fetchrow("select * from tcg_private.r2_first_catalogue_events")
        assert event["old_manifest_sha256"] is None and event["new_manifest_sha256"] == first.manifest_digest
        assert event["actor_user_id"] == ADMIN and event["generation"] == 1
        assert await admin.fetchval("select count(*) from tcg.catalogue_products") == 0
        assert await admin.fetchval("select count(*) from tcg.inventory_items") == 0
        assert await admin.fetchval("select count(*) from tcg.reference_cards") == 1

        for table in ("r2_first_catalogue_publications", "r2_first_catalogue_events", "r2_first_catalogue_links"):
            flags = await admin.fetchrow("select relrowsecurity,relforcerowsecurity from pg_class where oid=$1::regclass", "tcg_private." + table)
            assert flags["relrowsecurity"] and flags["relforcerowsecurity"]
            for role in ("anon", "authenticated", "service_role"):
                assert not await admin.fetchval("select has_table_privilege($1,$2,'SELECT,INSERT,UPDATE,DELETE')", role, "tcg_private." + table)
        async with user_connection(pool, SELLER, "r2-first-owner-rls") as connection:
            assert len(await service.sources(connection)) == 1
            assert await connection.fetchval("select count(*) from tcg_private.r2_first_catalogue_events") == 0
            assert await connection.execute("update tcg_private.r2_first_catalogue_publications set active=false,generation=generation+1") == "UPDATE 0"
        async with user_connection(pool, OUTSIDER, "r2-first-outsider-rls") as connection:
            assert await service.sources(connection) == []
        assert (await publication())["active"] and await audit_count() == 1

        insert_publication = """insert into tcg_private.r2_first_catalogue_publications
            (provider,system_code,language,manifest_sha256,source_revision,permission_ref,source_url,
             record_count,released_record_count,raw_bytes,set_count,generation,published_by)
            values('forbidden','YUGIOH','English',$1,'fixture','fixture','https://example.com/source',3,2,100,1,1,$2)"""
        await expect_sql_error(pool, SELLER, insert_publication, "e" * 64, SELLER)
        await expect_sql_error(pool, ADMIN, insert_publication, "e" * 64, SELLER)
        for generation in (1, 3):
            await expect_sql_error(pool, ADMIN,
                "update tcg_private.r2_first_catalogue_publications set generation=$1", generation, sqlstate="23514")
        await expect_sql_error(pool, ADMIN,
            "update tcg_private.r2_first_catalogue_publications set provider='changed',generation=2", sqlstate="23514")
        for statement in ("delete from tcg_private.r2_first_catalogue_publications",
                          "delete from tcg_private.r2_first_catalogue_events",
                          "update tcg_private.r2_first_catalogue_events set active=false"):
            await expect_sql_error(pool, ADMIN, statement)
        await expect_sql_error(pool, ADMIN, """insert into tcg_private.r2_first_catalogue_events
            (provider,system_code,language,new_manifest_sha256,generation,active,actor_user_id)
            values('ygoprodeck','YUGIOH','English',$1,99,true,$2)""", "f" * 64, ADMIN)
        assert (await publication())["generation"] == 1 and await audit_count() == 1

        # A failing audit write must roll back the actual publisher's pointer.
        await admin.execute("revoke insert on tcg_private.r2_first_catalogue_events from tcg_api")
        try:
            try:
                await publisher.publish_verified(pool, ADMIN, await fresh(2), expected_generation=1)
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("Publication escaped a failed audit insert")
        finally:
            await admin.execute("grant insert on tcg_private.r2_first_catalogue_events to tcg_api")
        assert (await publication())["generation"] == 1 and await audit_count() == 1

        await warm()
        reads = store.reads
        row = await selected(SELLER)
        assert store.reads == reads, "A cached selection must not perform R2 I/O inside SQL"
        assert row["identity_key"] == "r2:v1:" + KEY[2:] and row["name"] == "Alpha card v1"
        link = await admin.fetchrow("select * from tcg_private.r2_first_catalogue_links where reference_key=$1", KEY)
        assert link["created_by"] == SELLER and link["catalogue_id"] == row["id"]
        assert link["source_manifest_sha256"] == first.manifest_digest
        await expect_sql_error(pool, SELLER, """insert into tcg_private.r2_first_catalogue_links
            (reference_key,catalogue_id,provider,system_code,language,provider_id,
             source_manifest_sha256,created_by)
            values($1,$2,$3,$4,$5,'not-fixture-1',$6,$7)""",
            KEY, row["id"], *SCOPE, first.manifest_digest, SELLER, sqlstate="23514")
        assert (await selected(ADMIN))["id"] == row["id"]
        assert await admin.fetchval("select count(*) from tcg.inventory_items") == 0
        async with user_connection(pool, SELLER, "r2-first-tampered-display") as connection:
            evidence = await service.resolve(connection, KEY)
            correct = await service.materialize(connection, {**evidence, "name": "Forged", "provider_id": "other", "language": "Japanese"})
            assert correct["id"] == row["id"] and correct["name"] == "Alpha card v1"
            assert await service.resolve(connection, codec.stable_key(*SCOPE, "fixture-3")) is None

        # Creating a canonical/link is atomic with the caller's outer transaction.
        try:
            async with user_connection(pool, SELLER, "r2-first-outer-rollback") as connection:
                evidence = await service.resolve(connection, OTHER_KEY)
                await service.materialize(connection, evidence)
                raise RuntimeError("synthetic later intake failure")
        except RuntimeError as exc:
            assert str(exc) == "synthetic later intake failure"
        assert await admin.fetchval("select count(*) from tcg_private.r2_first_catalogue_links where reference_key=$1", OTHER_KEY) == 0
        assert await admin.fetchval("select count(*) from tcg.catalogue_products where identity_key=$1", "r2:v1:" + OTHER_KEY[2:]) == 0
        copies = await asyncio.gather(selected(SELLER, OTHER_KEY), selected(ADMIN, OTHER_KEY))
        assert copies[0]["id"] == copies[1]["id"]
        assert await admin.fetchval("select count(*) from tcg_private.r2_first_catalogue_links") == 2
        assert await admin.fetchval("select count(*) from tcg.catalogue_products") == 2
        await expect_sql_error(pool, ADMIN, "delete from tcg_private.r2_first_catalogue_links")
        await expect_sql_error(pool, ADMIN, "update tcg_private.r2_first_catalogue_links set created_by=$1", ADMIN)

        # Real owner RLS and the exact key overlay must not count another seller.
        await admin.executemany("""insert into tcg.inventory_items(owner_id,catalogue_id,status,market_value_minor,
            acquisition_cost_minor,store_price_minor,private_notes) values($1,$2,$3,$4,777,999,'fixture-private')""",
            [(SELLER_OWNER, row["id"], "DRAFT", 100), (SELLER_OWNER, row["id"], "DRAFT", None),
             (SELLER_OWNER, row["id"], "REMOVED", 10000), (ADMIN_OWNER, row["id"], "DRAFT", 400)])
        admin_copy = await admin.fetchval("select id from tcg.inventory_items where owner_id=$1 and catalogue_id=$2 and status='DRAFT'", ADMIN_OWNER, row["id"])
        # The seller owns two distinct copies: their photos are never borrowed
        # as a globally reusable reference image. The founder owns one copy.
        await admin.execute("""
            insert into tcg.media_assets(inventory_id,owner_id,scope,media_kind,side,
                source_type,rights_tier,rights_status,approval_status,source_status,
                shopify_file_status,shopify_cdn_url,capture_context)
            values($1,$2,'INVENTORY_ITEM','IMAGE','FRONT',
                'FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','VERIFIED','APPROVED','ACTIVE',
                'READY','https://cdn.shopify.com/s/files/test/founder-copy.webp','RAW_CARD')
            """, admin_copy, ADMIN_OWNER)
        for actor, owner, quantity in ((SELLER, SELLER_OWNER, 2), (ADMIN, ADMIN_OWNER, 1)):
            async with user_connection(pool, actor, "r2-first-owner-overlay") as connection:
                page = await service.browse(connection, owner_id=owner, system_code=SYSTEM, keys=[KEY], limit=1)
                assert len(page["items"]) == 1 and page["items"][0]["owned_quantity"] == quantity
                assert page["items"][0]["market_value_minor"] is None
                if actor == ADMIN:
                    assert page["items"][0]["owner_inventory_image_path"] == (
                        f"/api/v1/owner/inventory/{admin_copy}/image")
                else:
                    assert "owner_inventory_image_path" not in page["items"][0], (
                        "Never borrow an arbitrary physical photo when multiple copies exist")
                assert not any(field in page["items"][0] for field in ("owner_id", "private_notes", "acquisition_cost_minor", "store_price_minor"))
                assert (await service.browse(connection, owner_id=owner, system_code=SYSTEM, keys=[]))["items"] == []
                # Even a tampered caller-supplied owner filter cannot bypass the
                # database role's RLS. Missing private counts must stay missing.
                other_owner = ADMIN_OWNER if owner == SELLER_OWNER else SELLER_OWNER
                foreign = await service.browse(connection, owner_id=other_owner,
                    system_code=SYSTEM, keys=[KEY], limit=1)
                assert foreign["items"][0]["owned_quantity"] == 0
                assert (await service.browse(connection, owner_id=other_owner,
                    system_code=SYSTEM, owned="owned"))["items"] == []
        # A graded copy must not reuse RAW_CARD art; actual slab photography
        # becomes eligible only when the exact physical item is approved.
        await admin.execute("update tcg.inventory_items set grading_company='PSA',grade='10' where id=$1", admin_copy)
        async with user_connection(pool, ADMIN, "r2-first-graded-no-raw-image") as connection:
            graded = await service.browse(connection, owner_id=ADMIN_OWNER, keys=[KEY])
            assert "owner_inventory_image_path" not in graded["items"][0]
        await admin.execute("update tcg.media_assets set capture_context='GRADED_SLAB' where inventory_id=$1", admin_copy)
        async with user_connection(pool, ADMIN, "r2-first-graded-approved-copy") as connection:
            graded = await service.browse(connection, owner_id=ADMIN_OWNER, keys=[KEY])
            assert graded["items"][0]["owner_inventory_image_path"] == (
                f"/api/v1/owner/inventory/{admin_copy}/image")
        await admin.execute("update tcg.media_assets set revoked_at=now() where inventory_id=$1", admin_copy)
        async with user_connection(pool, ADMIN, "r2-first-graded-revoked") as connection:
            revoked = await service.browse(connection, owner_id=ADMIN_OWNER, keys=[KEY])
            assert "owner_inventory_image_path" not in revoked["items"][0]
        assert all(b"fixture-private" not in raw for raw in store.objects.values())

        # x bookmarks use the real migration and remain private to their user.
        for actor in (SELLER, ADMIN):
            async with user_connection(pool, actor, "r2-first-bookmark") as connection:
                await connection.execute("insert into tcg.catalogue_saved_references(user_id,reference_key) values($1,$2)", actor, KEY)
                assert await connection.fetchval("select count(*) from tcg.catalogue_saved_references") == 1
        await expect_sql_error(pool, SELLER,
            "insert into tcg.catalogue_saved_references(user_id,reference_key) values($1,$2)", ADMIN_B, OTHER_KEY)
        await expect_sql_error(pool, SELLER,
            "insert into tcg.catalogue_saved_references(user_id,reference_key) values($1,'x:bad')", SELLER, sqlstate="23514")
        async with user_connection(pool, ADMIN_B, "r2-first-other-bookmark") as connection:
            assert await connection.fetchval("select count(*) from tcg.catalogue_saved_references") == 0
            assert await connection.execute("delete from tcg.catalogue_saved_references where user_id=$1", SELLER) == "DELETE 0"

        async with user_connection(pool, SELLER, "r2-first-stale-selection") as connection:
            old_evidence = await service.resolve(connection, KEY)
        await expect_http(409, publisher.publish_verified(pool, ADMIN, await fresh(2), expected_generation=0))
        assert (await publication())["generation"] == 1 and await audit_count() == 1
        second = await fresh(2)
        await publisher.publish_verified(pool, ADMIN_B, second, expected_generation=1)
        assert (await publication())["generation"] == 2 and await audit_count() == 2
        await warm()
        async with user_connection(pool, SELLER, "r2-first-stale-selection-recheck") as connection:
            await expect_http(409, service.materialize(connection, old_evidence))
        assert (await selected(SELLER))["id"] == row["id"]
        assert await admin.fetchval("select name from tcg.catalogue_products where id=$1", row["id"]) == "Alpha card v1"
        assert await admin.fetchval("select source_manifest_sha256 from tcg_private.r2_first_catalogue_links where reference_key=$1", KEY) == first.manifest_digest

        await publisher.publish_verified(pool, ADMIN, await fresh(2), expected_generation=2, active=False)
        assert (await publication())["generation"] == 3 and not (await publication())["active"]
        async with user_connection(pool, SELLER, "r2-first-revoked-source") as connection:
            assert await service.sources(connection) == []
            assert await service.resolve(connection, KEY) is None
            await expect_http(404, service.materialize(connection, old_evidence))
        await publisher.publish_verified(pool, ADMIN, await fresh(2), expected_generation=3)
        assert (await publication())["generation"] == 4
        competitors = [await fresh(3), await fresh(4)]
        outcomes = await asyncio.gather(
            publisher.publish_verified(pool, ADMIN, competitors[0], expected_generation=4),
            publisher.publish_verified(pool, ADMIN_B, competitors[1], expected_generation=4),
            return_exceptions=True)
        assert sum(isinstance(value, HTTPException) and value.status_code == 409 for value in outcomes) == 1, outcomes
        assert sum(not isinstance(value, Exception) for value in outcomes) == 1, outcomes
        assert (await publication())["generation"] == 5 and await audit_count() == 5
        winner_digest = (await publication())["manifest_sha256"]
        winner = next(value for value in competitors if value.manifest_digest == winner_digest)
        repeat = await publisher.publish_verified(pool, ADMIN, winner, expected_generation=4)
        assert repeat["status"] == "CURRENT" and repeat["generation"] == 5
        assert await audit_count() == 5
        events = await admin.fetch("select generation,old_manifest_sha256,new_manifest_sha256 from tcg_private.r2_first_catalogue_events order by generation")
        assert [event["generation"] for event in events] == list(range(1, 6))
        assert all(events[index]["old_manifest_sha256"] == events[index-1]["new_manifest_sha256"] for index in range(1, len(events)))
        assert await admin.fetchval("select name from tcg.reference_cards") == "Existing catalogue stays in SQL"
        print("R2-first PostgreSQL 17: owner RLS, reviewed publication/audit CAS, rollback, stable concurrent selection, revocation, private bookmarks and bounded owner overlays passed")
    finally:
        await service.close()
        for value in snapshots:
            value.close()


async def main():
    dsn = os.environ["R2_FIRST_TEST_DSN"]
    parsed = urlsplit(dsn)
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.path != "/r2_first_test" or parsed.query or parsed.fragment):
        raise RuntimeError("Only a disposable localhost r2_first_test database is allowed")
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        assert int(await admin.fetchval("show server_version_num")) // 10000 == 17, "Native PostgreSQL 17 required"
        assert not await admin.fetchval("select exists(select 1 from pg_namespace where nspname in ('tcg','tcg_private','auth'))"), "Fresh disposable database only"
        await _init_connection(admin)
        await seed(admin)

        async def setup(connection):
            await connection.execute("set role tcg_api")
            role = await connection.fetchrow(
                "select rolname,rolsuper,rolbypassrls from pg_roles where rolname=current_user")
            assert role["rolname"] == "tcg_api" and not role["rolsuper"] and not role["rolbypassrls"], \
                "Integration assertions must run as the restricted application role"

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_init_connection, setup=setup,
            command_timeout=20, server_settings={"statement_timeout": "15000", "lock_timeout": "5000"})
        with patch.dict(os.environ, {"TCG_R2_FIRST_CATALOGUE_ENABLED": "true"}):
            await run_checks(admin, pool)
    finally:
        if pool is not None:
            await pool.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
