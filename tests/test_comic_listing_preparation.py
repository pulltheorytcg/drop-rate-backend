"""Comic listing preparation does not bypass ownership or publication gates."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import comic_listing_preparation as preparation
from app import comic_photo_review as review


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                           state=SimpleNamespace(request_id="comic-review-test"))


def comic(owner, *, status="INSPECTION", version=3, owner_type="CONSIGNOR"):
    return {"id": uuid4(), "version": version, "status": status, "language": "English",
            "grading_company": None, "grade": None, "acquisition_cost_minor": None,
            "source_record": {}, "name": "Deadpool / Batman #1", "variant": "",
            "product_type": "COMIC", "owner_type": owner_type}


def settings():
    return SimpleNamespace(shopify_shop_domain="example.myshopify.com",shopify_client_id="test-app",
                           shopify_client_secret="test-server-secret",shopify_api_version="2026-10")


def test_signed_photo_ticket_is_owner_and_expiry_bound(monkeypatch):
    monkeypatch.setattr(preparation, "get_settings", settings)
    owner, inventory = uuid4(), uuid4()
    claims = {"owner": str(owner), "inventory": str(inventory), "side": "FRONT",
              "mime": "image/jpeg", "size": 100, "resource_url": "https://example.test/file",
              "filename": "front.jpg", "exp": int(preparation.time.time()) + 120}
    ticket = preparation._sign_ticket(claims)
    assert preparation._verify_ticket(ticket, owner_id=owner, inventory_id=inventory) == claims
    for candidate, other_owner in [(ticket + "x", owner), (ticket, uuid4())]:
        with pytest.raises(HTTPException) as exc:
            preparation._verify_ticket(candidate, owner_id=other_owner, inventory_id=inventory)
        assert exc.value.status_code == 422
    claims["exp"] = int(preparation.time.time()) - 5
    with pytest.raises(HTTPException, match="expired"):
        preparation._verify_ticket(preparation._sign_ticket(claims), owner_id=owner, inventory_id=inventory)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,expected", [("allowed", 200), ("foreign", 404),
    ("inactive", 409), ("duplicate", 409)])
async def test_seller_photo_stage_is_exact_owner_scoped_and_refuses_duplicates(monkeypatch, scenario, expected):
    owner, inventory_id, user_id = uuid4(), uuid4(), uuid4()
    record = comic(owner, status="SOLD" if scenario == "inactive" else "INSPECTION")
    class Connection:
        async def fetchrow(self, sql, *args):
            assert args == (inventory_id, owner) or args == (owner, inventory_id, "FRONT")
            if "from tcg.inventory_items i" in sql:
                return None if scenario == "foreign" else record
            return {"id": uuid4()} if scenario == "duplicate" else None
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(preparation, "user_connection", connection)
    monkeypatch.setattr(preparation, "get_settings", settings)
    client = SimpleNamespace(access_scopes=AsyncMock(return_value={"write_files"}),
        create_staged_image_upload=AsyncMock(return_value={"url":"https://upload.test",
            "resourceUrl":"https://stage.test/image", "parameters":[]}))
    monkeypatch.setattr(preparation, "_shopify", lambda: client)
    args = (inventory_id, preparation.ComicPhotoStage(side="FRONT",filename="cover.jpg",
        mime_type="image/jpeg",file_size=5200),request(),SimpleNamespace(user_id=user_id),{"owner_id":owner})
    if expected == 200:
        result = await preparation.comic_photo_upload_target(*args)
        assert "ticket" in result and result["expires_in_seconds"] == 900
        client.create_staged_image_upload.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as exc: await preparation.comic_photo_upload_target(*args)
        assert exc.value.status_code == expected
        client.create_staged_image_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_photo_only_creates_pending_rights_review_and_is_idempotent(monkeypatch):
    owner, inventory_id, user_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(preparation, "get_settings", settings)
    claims = {"owner": str(owner), "inventory": str(inventory_id), "side": "FRONT",
              "mime": "image/jpeg", "size": 2000, "resource_url": "https://stage.test/file",
              "filename": "my-comic.jpg", "exp": int(preparation.time.time()) + 90}
    ticket = preparation._sign_ticket(claims)
    insert_calls, rows = [], []
    class Connection:
        async def fetchrow(self, sql, *args):
            if "from tcg.inventory_items i" in sql:
                assert args == (inventory_id, owner)
                return comic(owner)
            if "from tcg.media_assets where" in sql:
                return rows[-1] if rows else None
            if "insert into tcg.media_assets" in sql:
                insert_calls.append((sql,args))
                item = {"id":uuid4(),"version":1,"side":"FRONT","approval_status":"PENDING",
                        "rights_status":"PENDING","shopify_file_status":"NOT_UPLOADED",
                        "provider_asset_id":preparation.hashlib.sha256(ticket.encode()).hexdigest()}
                rows.append(item);return item
            if "update tcg.media_assets set" in sql:
                return {**rows[-1],"version":2,"shopify_file_status":"READY"}
            raise AssertionError(sql[:90])
        async def fetchval(self, sql, *args):
            assert "provider_asset_id" in sql
            return False
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(preparation,"user_connection",connection)
    client = SimpleNamespace(create_file_from_url=AsyncMock(return_value={"id":"gid://shopify/MediaImage/1",
        "fileStatus":"READY", "image":{"url":"https://cdn.shopify.com/photo.jpg"}}))
    monkeypatch.setattr(preparation,"_shopify",lambda:client)
    args=(inventory_id,preparation.ComicPhotoComplete(ticket=ticket,rights_confirmed=True),request(),
          SimpleNamespace(user_id=user_id),{"owner_id":owner})
    result=await preparation.complete_comic_photo(*args)
    assert result["asset"]["approval_status"]=="PENDING" and result["asset"]["rights_status"]=="PENDING"
    assert len(insert_calls)==1
    assert "CONSIGNOR_UPLOAD" in insert_calls[0][1]
    result2=await preparation.complete_comic_photo(*args)
    assert result2["replayed"] is True and len(insert_calls)==1
    client.create_file_from_url.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,ready,status", [("APPROVE",False,422),
    ("APPROVE",True,200), ("RETAKE",False,200)])
async def test_staff_rejection_exposes_retake_and_approval_requires_ready_photo(monkeypatch,decision,ready,status):
    user_id, owner, asset_id = uuid4(),uuid4(),uuid4()
    row={"id":asset_id,"owner_id":owner,"version":5,"approval_status":"PENDING",
         "source_status":"ACTIVE","inventory_status":"INSPECTION","grading_company":None,"grade":None,
         "capture_context":"RAW_UNSLEEVED","shopify_file_status":"READY" if ready else "PROCESSING",
         "shopify_cdn_url":"https://cdn.shopify.com/photo.jpg" if ready else None,
         "rights_basis":"Seller copyright confirmation","alt_text":"Cover photo"}
    writes=[]
    class Connection:
        async def fetchrow(self,sql,*args):
            if "from tcg.media_assets m" in sql:
                assert args == (asset_id,)
                return row
            writes.append((sql,args))
            return {"id":asset_id,"version":6,"approval_status":"REJECTED" if decision=="RETAKE" else "APPROVED","side":"FRONT"}
    @asynccontextmanager
    async def connection(*args):yield Connection()
    monkeypatch.setattr(review,"user_connection",connection)
    wake=Mock()
    monkeypatch.setattr(review,"request_shopify_sync",wake)
    payload=review.ReviewDecision(version=5,decision=decision,reason="Glare on issue number")
    args=(asset_id,payload,request(),SimpleNamespace(user_id=user_id))
    if status==200:
        result=await review.review_comic_photo(*args)
        assert len(writes)==1
        assert result["asset"]["approval_status"] == ("REJECTED" if decision=="RETAKE" else "APPROVED")
        if decision == "RETAKE":
            assert "revocation_reason" in writes[0][0]
            assert "Glare on issue number" in writes[0][1]
        else:
            assert "rights_status='VERIFIED'" in writes[0][0]
    else:
        with pytest.raises(HTTPException) as exc: await review.review_comic_photo(*args)
        assert exc.value.status_code==status and not writes


def test_review_route_and_migration_are_explicitly_admin_and_comic_only():
    from pathlib import Path
    assert any(dependency.dependency is not None and dependency.dependency.__name__ == "require_platform_admin_request"
               for dependency in review.router.dependencies)
    migration=Path(__file__).resolve().parents[1]/"database/migrations/20261101194856_platform_comic_photo_review.sql"
    sql=migration.read_text()
    for proof in ("tcg.is_platform_admin()", "source_type='CONSIGNOR_UPLOAD'",
                  "p.product_type='COMIC'", "o.owner_type='CONSIGNOR'", "with check",
                  "media_asset_identity_immutable"):
        assert proof in sql
