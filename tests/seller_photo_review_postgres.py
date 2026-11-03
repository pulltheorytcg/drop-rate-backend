"""Real restricted-role SQL and HTTP decisions for submitted seller photos.

All actors, images and inventory are synthetic. Only Shopify is mocked. The
production founder-roster function, six media migrations and proposed scoped
review policies run in disposable PostgreSQL. No remote credentials accepted.
"""
import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import FastAPI
from PIL import Image

from app import access_control, comic_listing_preparation as photos, comic_photo_review as review
from app.db import _init_connection
from app.media_resolver import resolve_storefront_media
from catalogue_r2_cache_postgres import PGliteConnection
from inventory_photo_postgres import SCHEMA, MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
REVIEW_MIGRATION = "20261103191403_platform_seller_photo_review.sql"


async def check(pglite=False):
    if pglite:
        db = await PGliteConnection.open()
    else:
        dsn = os.environ["PHOTO_REVIEW_TEST_DSN"]
        parsed = urlsplit(dsn)
        assert parsed.hostname in {"localhost", "127.0.0.1"} and parsed.path == "/seller_photo_review_test"
        db = await asyncpg.connect(dsn); await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute(SCHEMA)
        await db.execute("alter table auth.users add column email_confirmed_at timestamptz")
        for name in MIGRATIONS:
            await db.execute((ROOT / "database/migrations" / name).read_text())
        owners, actors = [uuid4() for _ in range(4)], [uuid4() for _ in range(4)]
        for n in range(3):
            await db.execute("insert into auth.users values($1,now())", actors[n])
            await db.execute("insert into tcg.owners(id,owner_type,founder_slot) values($1,$2,$3)", owners[n],
                             "FOUNDER" if n == 2 else "CONSIGNOR", 1 if n == 2 else None)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)", actors[n], owners[n],
                             "PLATFORM_ADMIN" if n == 2 else "OWNER")
        await db.execute((ROOT / "database/migrations/20261002024856_unified_founder_app_access.sql").read_text())
        # A role claim without the actual enrolled founder roster must fail.
        await db.execute("insert into auth.users values($1,now())", actors[3])
        await db.execute("insert into tcg.owners(id,owner_type,founder_slot) values($1,'FOUNDER',2)", owners[3])
        await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'PLATFORM_ADMIN')", actors[3], owners[3])
        # These are the existing production base policies, verified read-only
        # from pg_policies. The proposed migration does not change either one.
        await db.execute("""drop policy own_owner on tcg.owners;
            create policy owner_read on tcg.owners for select to tcg_api using(active and
              (tcg.is_platform_admin() or exists(select 1 from tcg.owner_memberships m
                where m.owner_id=owners.id and m.user_id=tcg.current_user_id() and m.active)));
            drop policy own_inventory on tcg.inventory_items;
            create policy own_records on tcg.inventory_items for all to tcg_api
              using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));""")

        @asynccontextmanager
        async def connection(_pool, actor, request_id, **_):
            async with db.transaction():
                await db.execute("set local role tcg_api")
                await db.execute("select set_config('tcg.user_id',$1,true)", str(actor))
                await db.execute("select set_config('tcg.request_id',$1,true)", request_id)
                yield db

        items, products = {}, {}
        for name in ("CARD", "COMIC", "SEALED", "FIGURE", "COLLECTION", "GRADED_CARD", "RETAKE", "REFRESH"):
            kind = "CARD" if name in {"GRADED_CARD", "RETAKE", "REFRESH"} else name
            products[name], items[name] = uuid4(), uuid4()
            await db.execute("""insert into tcg.catalogue_products(id,name,language,variant,product_type)
                values($1,$2,'English','Base',$3)""", products[name], "Synthetic " + name, kind)
            await db.execute("""insert into tcg.inventory_items(id,owner_id,catalogue_id,language,condition,grading_company,grade,certificate_number,seal_status)
                values($1,$2,$3,'English',$4,$5,$6,$7,$8)""", items[name], owners[0], products[name],
                None if name in {"CARD", "GRADED_CARD"} else "Near Mint",
                "PSA" if name == "GRADED_CARD" else None, "10" if name == "GRADED_CARD" else None,
                "synthetic-certificate" if name == "GRADED_CARD" else None, "SEALED" if name == "SEALED" else None)

        class Provider:
            creates = 0; invalid = False
            async def access_scopes(self): return {"write_files"}
            async def create_staged_image_upload(self, **_):
                return {"url": "https://shopify-staged-uploads.storage.googleapis.com/",
                        "resourceUrl": "https://shopify-staged-uploads.storage.googleapis.com/tmp/synthetic.png", "parameters": []}
            async def create_file_from_url(self, **_):
                self.creates += 1
                if self.invalid: return {}
                return {"id": f"gid://shopify/MediaImage/{self.creates}", "fileStatus": "READY",
                        "image": {"url": "https://cdn.shopify.com/synthetic.png"}}
        provider = Provider()
        async def transfer(*_): pass
        image = BytesIO(); Image.new("RGB", (240, 320), "navy").save(image, format="PNG")
        settings = SimpleNamespace(shopify_client_secret="synthetic-only", shopify_shop_domain="synthetic.myshopify.com")
        app = FastAPI(); app.state.db_pool = db; app.include_router(photos.router); app.include_router(review.router)
        session = {"actor": actors[0]}
        app.dependency_overrides[photos.require_user] = lambda: SimpleNamespace(user_id=session["actor"])
        @app.middleware("http")
        async def request_id(request, call_next):
            request.state.request_id = "synthetic-seller-photo-review"
            return await call_next(request)
        wake = Mock(side_effect=AssertionError("General photo review must not start publication"))
        with patch.object(photos, "user_connection", connection), patch.object(review, "user_connection", connection), \
                patch.object(access_control, "user_connection", connection), patch.object(photos, "get_settings", return_value=settings), \
                patch.object(photos, "_shopify", return_value=provider), patch.object(photos, "_transfer_photo", transfer), \
                patch.object(review, "request_shopify_sync", wake):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
                receipts = {}
                for name, inventory in items.items():
                    provider.invalid = name == "REFRESH"
                    response = await client.post(f"/api/v1/owner/inventory/{inventory}/photo/upload", params={
                        "side": "FRONT", "version": 3, "filename": "scan.png", "rights_confirmed": "true", "request_key": str(uuid4())},
                        headers={"content-type": "image/png"}, content=image.getvalue())
                    assert response.status_code == 201, response.text
                    receipts[name] = response.json()["asset"]
                provider.invalid = False
                excluded = []
                for case in ("unsupported", "other_source", "other_provider", "withdrawn", "wrong_owner", "inactive_owner", "other_rights"):
                    product, inventory = uuid4(), uuid4()
                    inventory_owner = owners[1] if case in {"wrong_owner", "inactive_owner"} else owners[0]
                    media_owner = owners[1] if case == "inactive_owner" else owners[0]
                    await db.execute("""insert into tcg.catalogue_products(id,name,language,variant,product_type)
                        values($1,$2,'English','Base',$3)""", product, "Excluded " + case, "ACCESSORY" if case == "unsupported" else "CARD")
                    await db.execute("""insert into tcg.inventory_items(id,owner_id,catalogue_id,status)
                        values($1,$2,$3,$4)""", inventory, inventory_owner, product, "WITHDRAWN" if case == "withdrawn" else "INSPECTION")
                    excluded.append(await db.fetchval("""insert into tcg.media_assets
                        (owner_id,inventory_id,scope,side,source_type,source_reference,rights_tier,source_provider,created_by_user_id)
                        values($1,$2,'INVENTORY_ITEM','FRONT',$3,'Synthetic excluded asset',$4,$5,$6) returning id""",
                        media_owner, inventory, "FOUNDER_UPLOAD" if case == "other_source" else "CONSIGNOR_UPLOAD",
                        "INTERNAL_REFERENCE_ONLY" if case == "other_rights" else "FIRST_PARTY_CAPTURE",
                        "Unrelated source" if case == "other_provider" else "Drop Rate", actors[0]))
                await db.execute("update tcg.owners set active=false where id=$1", owners[1])
                # Actual assessment after capture: physical identity is stable,
                # and this does not confer reviewed condition or approval.
                await db.execute("update tcg.inventory_items set condition='Near Mint',version=version+1 where id=$1", items["CARD"])
                snapshot = [dict(row) for row in await db.fetch("select * from tcg.inventory_items order by id")]
                session["actor"] = actors[2]
                async with connection(db, actors[2], "old-policy") as c:
                    assert await c.fetchval("select count(*) from tcg.media_assets") == 1, "Old staff policy is comic-only"
                await db.execute((ROOT / "database/migrations" / REVIEW_MIGRATION).read_text())
                async with connection(db, actors[2], "bounded-review-policy") as c:
                    assert not await c.fetch("select id from tcg.media_assets where id=any($1::uuid[])", excluded)
                    assert not await c.fetch("update tcg.media_assets set alt_text='forbidden' where id=any($1::uuid[]) returning id", excluded)
                try:
                    async with connection(db, actors[2], "no-staff-insert-grant") as c:
                        await c.execute("""insert into tcg.media_assets
                            (owner_id,inventory_id,scope,side,source_type,source_reference,rights_tier,source_provider,created_by_user_id)
                            values($1,$2,'INVENTORY_ITEM','BACK','CONSIGNOR_UPLOAD','Forbidden staff insert','FIRST_PARTY_CAPTURE','Drop Rate',$3)""",
                            owners[0], items["CARD"], actors[2])
                    raise AssertionError("Review permission unexpectedly granted staff insert")
                except (asyncpg.InsufficientPrivilegeError, RuntimeError) as exc:
                    assert "row-level security" in str(exc), str(exc)
                queue = await client.get("/api/v1/shopify/photo-review/queue")
                assert queue.status_code == 200, queue.text
                assert len(queue.json()["items"]) == 8
                assert all(row["identity_matches"] for row in queue.json()["items"]), queue.text
                legacy = await client.get("/api/v1/shopify/comic-review/queue")
                assert {row["id"] for row in legacy.json()["items"]} == {receipts["COMIC"]["id"]}
                legacy_card = await client.post(f"/api/v1/shopify/comic-review/{receipts['CARD']['id']}/decision",
                    json={"version": receipts["CARD"]["version"], "decision": "APPROVE"})
                assert legacy_card.status_code == 404, "The legacy comic alias must remain comic-only"

                async def decide(name, *, version=None, decision="APPROVE", reason="Reviewed exact physical item and rights"):
                    return await client.post(f"/api/v1/shopify/photo-review/{receipts[name]['id']}/decision", json={
                        "version": receipts[name]["version"] if version is None else version, "decision": decision, "reason": reason})

                for actor in (actors[0], actors[1], actors[3]):
                    session["actor"] = actor
                    assert (await client.get("/api/v1/shopify/photo-review/queue")).status_code == 403
                    assert (await decide("CARD")).status_code == 403
                session["actor"] = actors[2]
                # Identity changes must still fail closed even if media is READY.
                for column, value in (("catalogue_id", products["RETAKE"]), ("grade", "9"), ("certificate_number", "different-cert")):
                    async with db.transaction():
                        original = await db.fetchval(f"select {column} from tcg.inventory_items where id=$1", items["GRADED_CARD"])
                        await db.execute(f"update tcg.inventory_items set {column}=$2 where id=$1", items["GRADED_CARD"], value)
                        assert (await decide("GRADED_CARD")).status_code == 409
                        await db.execute(f"update tcg.inventory_items set {column}=$2 where id=$1", items["GRADED_CARD"], original)
                await db.execute("update tcg.media_assets set shopify_cdn_url='https://untrusted.invalid/image.png' where id=$1", UUID(receipts["FIGURE"]["id"]))
                assert (await decide("FIGURE")).status_code == 422
                await db.execute("update tcg.media_assets set shopify_cdn_url='https://cdn.shopify.com/synthetic.png' where id=$1", UUID(receipts["FIGURE"]["id"]))
                assert (await decide("CARD", version=1)).status_code == 409
                assert (await decide("REFRESH")).status_code == 422
                refreshed = await client.post(f"/api/v1/shopify/photo-review/{receipts['REFRESH']['id']}/refresh-file",
                                              json={"version": receipts["REFRESH"]["version"]})
                assert refreshed.status_code == 200 and refreshed.json()["asset"]["shopify_file_status"] == "READY", refreshed.text
                receipts["REFRESH"] = refreshed.json()["asset"]
                for name in ("CARD", "COMIC", "SEALED", "FIGURE", "COLLECTION", "GRADED_CARD", "REFRESH"):
                    response = await decide(name)
                    assert response.status_code == 200, (name, response.text)
                    media = dict(await db.fetchrow("select * from tcg.media_assets where id=$1", UUID(receipts[name]["id"])))
                    assert media["approval_status"] == "APPROVED" and media["rights_status"] == "VERIFIED"
                    assert str(media["approved_by_user_id"]) == str(actors[2])
                    item = dict(await db.fetchrow("""select i.*,p.product_type,p.variant from tcg.inventory_items i
                        join tcg.catalogue_products p on p.id=i.catalogue_id where i.id=$1""", items[name]))
                    # Front capture is usable; card policy can still require a
                    # separately captured/reviewed back and condition decision.
                    resolution = resolve_storefront_media(item, [media, {**media, "side": "BACK"}])
                    assert resolution["complete"], (name, resolution)
                assert (await decide("RETAKE", decision="RETAKE", reason="")).status_code == 422
                response = await decide("RETAKE", decision="RETAKE", reason="The edition label is obscured")
                assert response.status_code == 200, response.text
                retake = await db.fetchrow("select approval_status,rights_status,source_status,revocation_reason from tcg.media_assets where id=$1", UUID(receipts["RETAKE"]["id"]))
                assert retake["source_status"] == "REVOKED" and retake["revocation_reason"] == "The edition label is obscured"
                assert snapshot == [dict(row) for row in await db.fetch("select * from tcg.inventory_items order by id")]
                assert await db.fetchval("select count(*) from tcg.condition_review_events") == 0
                assert not await db.fetchval("select exists(select 1 from tcg.inventory_items where condition_review_status<>'NOT_REVIEWED')")
                wake.assert_not_called()
                assert await db.fetchval("select count(*) from tcg.audit_events where actor=$1 and action='UPDATE' and entity_type='media_assets'", str(actors[2])) == 9
                # Retake, approval and refresh all use the actual immutable guard.
                try:
                    async with connection(db, actors[2], "immutable") as c:
                        await c.execute("update tcg.media_assets set inventory_id=$2 where id=$1", UUID(receipts["CARD"]["id"]), items["FIGURE"])
                    raise AssertionError("Media reassignment was allowed")
                except (asyncpg.RaiseError, RuntimeError) as exc:
                    assert "cannot be reassigned" in str(exc), str(exc)
                await db.execute("update tcg.founder_app_accounts set active=false where user_id=$1", actors[2])
                assert (await client.get("/api/v1/shopify/photo-review/queue")).status_code == 403
                async with connection(db, actors[2], "revoked-roster") as c:
                    assert await c.fetchval("select count(*) from tcg.media_assets") == 0
        print("PASS: real founder-roster guard and media RLS; owner/unregistered/revoked admin denial; legacy comic-only alias; explicit review across five types plus graded card; condition filled after capture retained; changed catalogue/grade/certificate rejected; version/CDN/processing gates; reasoned retake; audited immutable identity; inventory, condition and publication unchanged")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--pglite", action="store_true")
    asyncio.run(check(parser.parse_args().pglite))
