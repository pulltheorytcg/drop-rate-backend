"""Exact-copy photo API against real media migrations, RLS and audit triggers.

Synthetic data only. --pglite is a disposable real PostgreSQL engine; native
CI accepts PHOTO_TEST_DSN only for localhost/inventory_photo_test. Only Shopify
network calls are mocked. API SQL, transactions, constraints and RLS are real.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import FastAPI
from PIL import Image

from app import comic_listing_preparation as photos
from app import condition_review
from app.db import _init_connection
from app.media_resolver import resolve_storefront_media
from catalogue_r2_cache_postgres import PGliteConnection

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "20260925154423_media_assets_registry.sql",
    "20260926002000_media_live_side_uniqueness.sql",
    "20260926003000_media_condition_review.sql",
    "20260927160758_media_rights_resolver.sql",
    "20260928224759_sealed_product_media.sql",
    "20261101203926_platform_comic_photo_review.sql",
]
SCHEMA = """
create schema tcg; create schema auth;
create role tcg_api nologin nosuperuser nobypassrls;
create role anon nologin; create role authenticated nologin;
create table auth.users(id uuid primary key);
create table tcg.owners(id uuid primary key,owner_type text,active bool default true,
 display_name text default 'Synthetic owner',founder_slot int,commission_bps int default 1000);
create table tcg.owner_memberships(id uuid default gen_random_uuid(),user_id uuid,owner_id uuid references tcg.owners,
 role text,active bool default true,created_at timestamptz default now());
create function tcg.current_user_id() returns uuid language sql stable as
 $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create function tcg.is_platform_admin() returns bool language sql stable as
 $$select exists(select 1 from tcg.owner_memberships where user_id=tcg.current_user_id() and role='PLATFORM_ADMIN' and active)$$;
create table tcg.catalogue_products(id uuid primary key,name text,language text,variant text,product_type text,
 game text default 'Synthetic game',set_name text default 'Synthetic set',card_number text default '1');
create table tcg.inventory_items(id uuid primary key,owner_id uuid references tcg.owners,
 catalogue_id uuid references tcg.catalogue_products,language text,condition text,grading_company text,grade text,
 seal_status text,certificate_number text,acquisition_cost_minor bigint,source_record jsonb default '{}',
 status text default 'INSPECTION',version int default 3,updated_at timestamptz default now(),
 inventory_code text default 'SYNTHETIC-COPY',identity_confirmed bool default true,
 store_price_minor bigint default 7500,market_value_minor bigint,recommended_retail_minor bigint);
create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
grant usage on schema tcg to tcg_api;
grant select on all tables in schema tcg to tcg_api;
grant update on tcg.inventory_items to tcg_api;
alter table tcg.owner_memberships enable row level security;
alter table tcg.owner_memberships force row level security;
create policy own_memberships on tcg.owner_memberships for select to tcg_api using(user_id=tcg.current_user_id() and active);
alter table tcg.owners enable row level security; alter table tcg.owners force row level security;
create policy own_owner on tcg.owners for select to tcg_api using(id in(select owner_id from tcg.owner_memberships));
alter table tcg.inventory_items enable row level security; alter table tcg.inventory_items force row level security;
create policy own_inventory on tcg.inventory_items for all to tcg_api
 using(owner_id in(select owner_id from tcg.owner_memberships)) with check(owner_id in(select owner_id from tcg.owner_memberships));
"""


async def check(pglite=False):
    if pglite:
        db = await PGliteConnection.open()
    else:
        dsn = os.environ["PHOTO_TEST_DSN"]
        parsed = urlsplit(dsn)
        assert parsed.hostname in {"localhost", "127.0.0.1"} and parsed.path == "/inventory_photo_test"
        db = await asyncpg.connect(dsn)
        await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), "Fresh disposable database required"
        await db.execute(SCHEMA)
        for filename in MIGRATIONS:
            await db.execute((ROOT / "database/migrations" / filename).read_text())
        owners, actors = [uuid4(), uuid4(), uuid4()], [uuid4(), uuid4(), uuid4()]
        for n, (owner, actor) in enumerate(zip(owners, actors)):
            await db.execute("insert into auth.users values($1)", actor)
            await db.execute("insert into tcg.owners(id,owner_type,founder_slot) values($1,$2,$3)", owner,
                             "FOUNDER" if n == 2 else "CONSIGNOR", 1 if n == 2 else None)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)", actor, owner,
                             "PLATFORM_ADMIN" if n == 2 else "OWNER")
        products, copies = {}, {}
        for kind in ("CARD", "COMIC", "SEALED", "FIGURE", "COLLECTION", "GRADED_CARD"):
            product = uuid4(); products[kind] = product
            await db.execute("insert into tcg.catalogue_products(id,name,language,variant,product_type) values($1,$2,'English','Base',$3)",
                             product, "Synthetic " + kind, "CARD" if kind == "GRADED_CARD" else kind)
            for n in range(2):
                inventory = uuid4(); copies[n, kind] = inventory
                await db.execute("""insert into tcg.inventory_items
                    (id,owner_id,catalogue_id,language,condition,grading_company,grade,certificate_number,seal_status)
                    values($1,$2,$3,'English','Mint',$4,$5,$6,$7)""", inventory, owners[n], product,
                    "PSA" if kind == "GRADED_CARD" else None, "10" if kind == "GRADED_CARD" else None,
                    "synthetic-certificate" if kind == "GRADED_CARD" else None, "SEALED" if kind == "SEALED" else None)
        founder_card = uuid4()
        await db.execute("""insert into tcg.inventory_items(id,owner_id,catalogue_id,language,condition)
            values($1,$2,$3,'English','Near Mint')""", founder_card, owners[2], products["CARD"])
        before = [dict(row) for row in await db.fetch("select * from tcg.inventory_items order by id")]

        @asynccontextmanager
        async def connection(_pool, actor, request_id, **_):
            async with db.transaction():
                await db.execute("set local role tcg_api")
                await db.execute("select set_config('tcg.user_id',$1,true)", str(actor))
                await db.execute("select set_config('tcg.request_id',$1,true)", request_id)
                yield db

        class Shopify:
            creates = 0; stages = 0; gets = 0; invalid_next = False; processing_next = False
            async def access_scopes(self): return {"write_files"}
            async def create_staged_image_upload(self, **_):
                self.stages += 1
                return {"url": "https://shopify-staged-uploads.storage.googleapis.com/",
                        "resourceUrl": "https://shopify-staged-uploads.storage.googleapis.com/tmp/synthetic-photo.png",
                        "parameters": [{"name": "key", "value": "tmp/synthetic-photo.png"}]}
            async def create_file_from_url(self, **_):
                self.creates += 1
                if self.invalid_next:
                    self.invalid_next = False
                    return {}
                status = "PROCESSING" if self.processing_next else "READY"
                self.processing_next = False
                return {"id": f"gid://shopify/MediaImage/{self.creates}", "fileStatus": status,
                        "image": {"url": "https://cdn.shopify.com/synthetic-photo.png"} if status == "READY" else None}
            async def get_file(self, file_id):
                self.gets += 1
                return {"id": file_id, "fileStatus": "READY", "image": {"url": "https://cdn.shopify.com/synthetic-photo.png"}}

        provider = Shopify()
        async def transfer(*_): pass
        settings = SimpleNamespace(shopify_client_secret="synthetic-local-only", shopify_shop_domain="synthetic.myshopify.com",
                                   media_physical_photo_threshold_minor=5000)
        session = {"index": 0}
        app = FastAPI(); app.state.db_pool = db; app.include_router(photos.router)
        app.dependency_overrides[photos.require_user] = lambda: SimpleNamespace(user_id=actors[session["index"]])
        app.dependency_overrides[photos.require_owner_portal_request] = lambda: {"owner_id": owners[session["index"]]}
        @app.middleware("http")
        async def request_context(request, call_next):
            request.state.request_id = "synthetic-physical-photo"
            return await call_next(request)
        image = BytesIO(); Image.new("RGB", (240, 320), "navy").save(image, format="PNG")
        image_body = image.getvalue()
        receipt_ids = {}
        with patch.object(photos, "user_connection", connection), patch.object(photos, "_shopify", return_value=provider), \
                patch.object(photos, "get_settings", return_value=settings), patch.object(photos, "_transfer_photo", transfer):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
                async def submit(inventory, *, body=image_body, request_key=None, side="FRONT", version=3, legacy=False):
                    return await client.post(f"/api/v1/owner/inventory/{inventory}/{'comic-photo' if legacy else 'photo'}/upload",
                        params={"side": side, "version": str(version), "filename": "scan.png", "rights_confirmed": "true",
                                "request_key": str(request_key or uuid4())}, content=body, headers={"content-type": "image/png"})

                for kind in products:
                    inventory, key = copies[0, kind], uuid4()
                    provider.invalid_next = kind == "FIGURE"
                    provider.processing_next = kind == "SEALED"
                    result = await submit(inventory, request_key=key, legacy=kind == "COMIC")
                    assert result.status_code == 201, (kind, result.text)
                    payload = result.json(); asset = payload["asset"]; receipt_ids[kind] = UUID(asset["id"])
                    assert payload["inventory_version"] == 3
                    assert asset["approval_status"] == asset["rights_status"] == "PENDING"
                    assert set(asset) == {"id", "version", "side", "approval_status", "rights_status", "shopify_file_status", "photo_url"}
                    actual = await db.fetchrow("select * from tcg.media_assets where id=$1", receipt_ids[kind])
                    assert actual["capture_context"] == ("SEALED_PRODUCT" if kind in {"SEALED", "COLLECTION"} else "GRADED_SLAB" if kind == "GRADED_CARD" else "RAW_UNSLEEVED")
                    assert actual["content_sha256"] == hashlib.sha256(image_body).hexdigest()
                    assert actual["rights_tier"] == "FIRST_PARTY_CAPTURE" and actual["source_type"] == "CONSIGNOR_UPLOAD"
                    if kind == "FIGURE":
                        assert actual["shopify_file_status"] == "NOT_UPLOADED" and actual["shopify_error"] == photos.PHOTO_PROCESSING_ERROR
                    creates, stages = provider.creates, provider.stages
                    replay = await submit(inventory, request_key=key, legacy=kind == "COMIC")
                    assert replay.status_code == 201 and replay.json()["replayed"]
                    assert replay.json()["asset"]["id"] == asset["id"]
                    assert (provider.creates, provider.stages) == (creates, stages)
                    # A valid but different image must not reuse that receipt.
                    changed = BytesIO(); Image.new("RGB", (240, 320), "white").save(changed, format="PNG")
                    conflict = await submit(inventory, request_key=key, body=changed.getvalue(), legacy=kind == "COMIC")
                    assert conflict.status_code == 409
                    refresh = await client.post(f"/api/v1/owner/inventory/{inventory}/photos/refresh", json={})
                    assert refresh.status_code == 200, refresh.text
                    assert not refresh.json()["partial"]
                    assert refresh.json()["items"][0]["shopify_file_status"] == "READY"
                    assert refresh.json()["items"][0]["approval_status"] == refresh.json()["items"][0]["rights_status"] == "PENDING"
                    assert refresh.json()["inventory_version"] == 3
                    read = await client.get(f"/api/v1/owner/inventory/{inventory}/photos")
                    assert read.status_code == 200 and read.json()["items"][0]["photo_url"].startswith("https://cdn.shopify.com/")
                    media = dict(await db.fetchrow("select * from tcg.media_assets where id=$1", receipt_ids[kind]))
                    item = dict(await db.fetchrow("""select i.*,p.product_type,p.name,p.variant from tcg.inventory_items i
                        join tcg.catalogue_products p on p.id=i.catalogue_id where i.id=$1""", inventory))
                    assert not resolve_storefront_media(item, [media])["complete"], "Pending scans must not satisfy publication"
                    # Model a later human decision in memory only: the exact
                    # saved receipt must be usable by the production resolver.
                    reviewed = {**media, "approval_status": "APPROVED", "rights_status": "VERIFIED"}
                    front_and_back = [reviewed, {**reviewed, "side": "BACK"}]
                    resolution = resolve_storefront_media(item, front_and_back)
                    assert resolution["complete"] and resolution["resolutionSource"] == "FIRST_PARTY_CAPTURE", (kind, resolution)
                assert provider.creates == 7 and provider.gets == 1
                assert before == [dict(row) for row in await db.fetch("select * from tcg.inventory_items order by id")], "Photo writes must not mutate inventory"
                assert await db.fetchval("select count(*) from tcg.media_assets") == 6
                assert await db.fetchval("select count(*) from tcg.audit_events where action='INSERT'") == 6
                assert not await db.fetchval("select exists(select 1 from tcg.media_assets where approval_status<>'PENDING' or rights_status<>'PENDING')")

                # Real database ownership remains enforced even with API access
                # resolution stubbed to a different authenticated member.
                session["index"] = 1
                for method, suffix in (("get", "photos"), ("post", "photos/refresh")):
                    response = await getattr(client, method)(f"/api/v1/owner/inventory/{copies[0, 'CARD']}/{suffix}")
                    assert response.status_code == 404, response.text
                assert (await submit(copies[0, "CARD"], side="BACK")).status_code == 404
                session["index"] = 0
                for status in ("SOLD", "RESERVED", "WITHDRAWN"):
                    await db.execute("update tcg.inventory_items set status=$2 where id=$1", copies[0, "CARD"], status)
                    assert (await submit(copies[0, "CARD"], side="BACK")).status_code == 409
                    response = await client.post(f"/api/v1/owner/inventory/{copies[0, 'CARD']}/photos/refresh")
                    assert response.status_code == 409
                assert provider.creates == 7, "Denied calls must not contact Shopify"

        # Real queue SQL must include product_type. Otherwise the policy thinks
        # every selected card is an unrelated product and silently empties it.
        with patch.object(condition_review, "user_connection", connection), patch.object(condition_review, "get_settings", return_value=settings):
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=db)),
                                      state=SimpleNamespace(request_id="founder-condition-queue"))
            queue = await condition_review.condition_review_queue(request, SimpleNamespace(user_id=actors[2]))
            assert [row["id"] for row in queue["items"]] == [str(founder_card)]
            assert queue["items"][0]["product_type"] == "CARD" and not queue["items"][0]["photo_ready"]

        async with connection(db, actors[1], "foreign-rls") as c:
            assert await c.fetchval("select count(*) from tcg.media_assets") == 0
            assert not await c.fetch("update tcg.media_assets set alt_text='forbidden' where id=$1 returning id", receipt_ids["COMIC"])
        try:
            async with connection(db, actors[1], "foreign-insert") as c:
                await c.execute("""insert into tcg.media_assets(owner_id,inventory_id,scope,side,source_type,source_reference,created_by_user_id)
                    values($1,$2,'INVENTORY_ITEM','BACK','CONSIGNOR_UPLOAD','forbidden',$3)""", owners[0], copies[0, "COMIC"], actors[1])
            raise AssertionError("Foreign owner insert bypassed real RLS")
        except (asyncpg.InsufficientPrivilegeError, RuntimeError) as exc:
            assert "row-level security" in str(exc), str(exc)
        try:
            async with connection(db, actors[0], "immutable-identity") as c:
                await c.execute("update tcg.media_assets set inventory_id=$2 where id=$1", receipt_ids["COMIC"], copies[0, "FIGURE"])
            raise AssertionError("Physical identity reassignment bypassed actual trigger")
        except (asyncpg.RaiseError, RuntimeError) as exc:
            assert "cannot be reassigned" in str(exc), str(exc)
        await db.execute("update tcg.owner_memberships set active=false where user_id=$1", actors[0])
        async with connection(db, actors[0], "revoked-member") as c:
            assert await c.fetchval("select count(*) from tcg.media_assets") == 0
        print("PASS: six real media migrations; CARD/COMIC/SEALED/FIGURE/COLLECTION and graded-card pending receipts; exact-byte replay; legacy comic recovery; invalid FileCreate recovery; processing poll without duplicate; unchanged inventory versions; native audit, ownership/revocation RLS and immutable physical-identity trigger; inactive-item denial; no approvals or product writes")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pglite", action="store_true")
    asyncio.run(check(parser.parse_args().pglite))
