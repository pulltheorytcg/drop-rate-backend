"""Real image validation and owner-bound, retry-safe comic photo relay."""
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image

from app import comic_listing_preparation as photos
from app.shopify_client import ShopifyApiError


def image_bytes(fmt="PNG", color="navy"):
    out = BytesIO()
    Image.new("RGB", (240, 320), color).save(out, format=fmt)
    return out.getvalue()


class UploadRequest:
    def __init__(self, body, mime="image/png", *, headers=None):
        self.body = body
        self.headers = {"content-type": mime, "content-length": str(len(body)), **(headers or {})}
        self.app = SimpleNamespace(state=SimpleNamespace(db_pool=object()))
        self.state = SimpleNamespace(request_id="photo-relay-test")

    async def stream(self):
        yield self.body


@pytest.fixture
def relay(monkeypatch):
    owner, inventory, user = uuid4(), uuid4(), uuid4()
    item = {"id": inventory, "catalogue_id": uuid4(), "version": 3, "status": "INSPECTION",
            "product_type": "COMIC", "owner_type": "CONSIGNOR", "language": "English",
            "condition": "Mint", "grading_company": None, "grade": None,
            "acquisition_cost_minor": None, "source_record": {},
            "name": "Deadpool / Batman #1", "variant": "First printing"}
    records, writes = {}, []

    class Connection:
        async def fetchrow(self, sql, *args):
            if "from tcg.inventory_items i" in sql:
                return dict(item) if args == (inventory, owner) else None
            if "from tcg.media_assets" in sql:
                assert args[:2] == (owner, inventory)
                if "provider_asset_id=$3" in sql:
                    return records.get(args[2])
                return next((r for r in records.values() if r["side"] == args[2]
                    and r["approval_status"] != "REJECTED" and r["shopify_file_status"] != "FAILED"
                    and r["source_status"] != "REVOKED"), None)
            if "insert into tcg.media_assets" in sql:
                assert args[:2] == (owner, inventory)
                assert "APPROVED" not in sql and "VERIFIED" not in sql
                writes.append(sql)
                record = {"id": uuid4(), "version": 1, "side": args[2],
                    "provider_asset_id": args[4], "source_reference": args[5],
                    "content_sha256": args[13], "approval_status": "PENDING",
                    "rights_status": "PENDING", "source_status": "ACTIVE",
                    "shopify_file_status": "NOT_UPLOADED"}
                records[args[4]] = record
                return dict(record)
            if "update tcg.media_assets" in sql:
                assert args[1] == owner
                writes.append(sql)
                record = next(r for r in records.values() if r["id"] == args[0])
                record.update(version=2, shopify_file_status=args[3])
                return dict(record)
            raise AssertionError(sql)

        async def fetchval(self, sql, *args):
            assert args[:2] == (owner, inventory)
            return args[2] in records

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    target = {"url": "https://shopify-staged-uploads.storage.googleapis.com/",
              "resourceUrl": "https://shopify-staged-uploads.storage.googleapis.com/tmp/example/front.png",
              "parameters": [{"name": "key", "value": "tmp/example/front.png"}]}
    client = SimpleNamespace(access_scopes=AsyncMock(return_value={"write_files"}),
        create_staged_image_upload=AsyncMock(return_value=target),
        create_file_from_url=AsyncMock(return_value={"id": "gid://shopify/MediaImage/1",
            "fileStatus": "READY", "image": {"url": "https://cdn.shopify.com/front.png"}}))
    transfer = AsyncMock()
    monkeypatch.setattr(photos, "user_connection", connection)
    monkeypatch.setattr(photos, "_shopify", lambda: client)
    monkeypatch.setattr(photos, "get_settings", lambda: SimpleNamespace(shopify_client_secret="synthetic-test-secret"))
    monkeypatch.setattr(photos, "_transfer_photo", transfer)
    return SimpleNamespace(owner=owner, inventory=inventory, user=user, item=item, records=records,
                           writes=writes, client=client, transfer=transfer, target=target)


async def upload(relay, *, body=None, mime="image/png", key=None, version=None,
                 side="FRONT", filename="front.png", owner=None, rights="true", headers=None):
    return await photos.upload_comic_photo(relay.inventory,
        UploadRequest(image_bytes() if body is None else body, mime, headers=headers),
        SimpleNamespace(user_id=relay.user), {"owner_id": owner or relay.owner},
        side, relay.item["version"] if version is None else version, filename,
        rights, key or uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
async def test_valid_photos_create_unapproved_exact_copy_receipts(relay, fmt, mime):
    result = await upload(relay, body=image_bytes(fmt), mime=mime)
    assert result["asset"]["approval_status"] == "PENDING"
    assert result["asset"]["rights_status"] == "PENDING"
    assert result["asset"]["shopify_file_status"] == "READY"
    assert not result["replayed"]
    assert len(relay.records) == 1
    assert relay.item["status"] == "INSPECTION"
    assert all("tcg.media_assets" in sql for sql in relay.writes)
    relay.client.create_file_from_url.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_response_replays_before_new_write_version_check(relay):
    key = uuid4()
    first = await upload(relay, key=key)
    relay.item["version"] += 1
    replay = await upload(relay, key=key, version=3)
    assert replay["replayed"]
    assert replay["asset"]["id"] == first["asset"]["id"]
    assert len(relay.records) == 1
    relay.client.create_staged_image_upload.assert_awaited_once()
    relay.client.create_file_from_url.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "filename", "side", "identity"])
async def test_request_key_cannot_be_reused_for_a_different_photo_or_identity(relay, change):
    key = uuid4()
    await upload(relay, key=key)
    options = {"body": image_bytes(color="red")} if change == "body" else {}
    if change == "filename": options["filename"] = "different.png"
    if change == "side": options["side"] = "BACK"
    if change == "identity": relay.item["variant"] = "Second printing"
    with pytest.raises(HTTPException) as exc:
        await upload(relay, key=key, **options)
    assert exc.value.status_code == 409
    assert len(relay.records) == 1
    relay.client.create_staged_image_upload.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status", [("foreign",404),("stale",409),("inactive",409),
    ("rights",422),("html",422),("mime",422),("large",413),("filename",422)])
async def test_rejected_uploads_make_no_shopify_or_database_changes(relay, case, status):
    options = {}
    if case == "foreign": options["owner"] = uuid4()
    if case == "stale": options["version"] = 2
    if case == "inactive": relay.item["status"] = "SOLD"
    if case == "rights": options["rights"] = "false"
    if case == "html": options["body"] = b"<html>not a photograph</html>"
    if case == "mime": options["mime"] = "image/jpeg"
    if case == "large": options["headers"] = {"content-length": str(photos.MAX_PHOTO_BYTES+1)}
    if case == "filename": options["filename"] = "../front.png"
    with pytest.raises(HTTPException) as exc: await upload(relay, **options)
    assert exc.value.status_code == status
    assert not relay.writes
    relay.client.create_staged_image_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_transfer_can_retry_without_duplicate_receipt(relay):
    key = uuid4()
    relay.transfer.side_effect = HTTPException(502, "Photo transfer was interrupted")
    with pytest.raises(HTTPException): await upload(relay, key=key)
    assert not relay.records
    relay.client.create_file_from_url.assert_not_awaited()
    relay.transfer.side_effect = None
    result = await upload(relay, key=key)
    assert result["asset"]["approval_status"] == "PENDING"
    assert len(relay.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "identity"])
async def test_item_changed_during_transfer_never_records_or_imports_photo(relay, change):
    async def changed(*args):
        if change == "version": relay.item["version"] += 1
        else: relay.item["variant"] = "Second printing"
    relay.transfer.side_effect = changed
    with pytest.raises(HTTPException) as exc: await upload(relay)
    assert exc.value.status_code == 409
    assert not relay.records
    relay.client.create_file_from_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_import_failure_keeps_one_pending_receipt_for_staff_recovery(relay):
    key = uuid4()
    relay.client.create_file_from_url.side_effect = ShopifyApiError("Provider unavailable")
    result = await upload(relay, key=key)
    assert result["asset"]["approval_status"] == "PENDING"
    assert result["asset"]["rights_status"] == "PENDING"
    assert result["asset"]["shopify_file_status"] == "NOT_UPLOADED"
    assert "staff attention" in result["message"]
    replay = await upload(relay, key=key)
    assert replay["replayed"]
    assert "staff attention" in replay["message"]
    assert len(relay.records) == 1
    relay.client.create_file_from_url.assert_awaited_once()


@pytest.mark.asyncio
async def test_raw_http_route_accepts_the_ui_query_contract_and_rejects_missing_consent(relay):
    from fastapi import FastAPI
    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(photos.router)
    app.dependency_overrides[photos.require_user] = lambda: SimpleNamespace(user_id=relay.user)
    app.dependency_overrides[photos.require_owner_portal_request] = lambda: {"owner_id": relay.owner}

    @app.middleware("http")
    async def add_request_id(request, call_next):
        request.state.request_id = "raw-photo-route-test"
        return await call_next(request)

    params = {"side": "FRONT", "version": "3", "filename": "front.png",
              "rights_confirmed": "true", "request_key": str(uuid4())}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/owner/inventory/{relay.inventory}/comic-photo/upload",
            params=params, content=image_bytes(), headers={"Content-Type": "image/png"})
        assert response.status_code == 201, response.text
        assert response.json()["asset"]["approval_status"] == "PENDING"
        params.pop("rights_confirmed")
        denied = await client.post(f"/api/v1/owner/inventory/{relay.inventory}/comic-photo/upload",
            params=params, content=image_bytes(), headers={"Content-Type": "image/png"})
        assert denied.status_code == 422
    assert len(relay.records) == 1


def test_only_the_configured_shop_can_supply_its_temporary_upload_path(monkeypatch):
    monkeypatch.setattr(photos, "get_settings", lambda: SimpleNamespace(shopify_shop_domain="drop-rate.myshopify.com"))
    assert photos._allowed_staged_url("https://drop-rate.myshopify.com/admin/tmp/files")
    assert not photos._allowed_staged_url("https://another-shop.myshopify.com/admin/tmp/files")
    assert not photos._allowed_staged_url("https://drop-rate.myshopify.com/admin/products")
    assert not photos._allowed_staged_url("https://drop-rate.myshopify.com.evil.test/admin/tmp/files")


@pytest.mark.parametrize("url", ["http://shopify-staged-uploads.storage.googleapis.com/",
    "https://shopify-staged-uploads.storage.googleapis.com.evil.test/",
    "https://user@shopify-staged-uploads.storage.googleapis.com/",
    "https://127.0.0.1/", "https://169.254.169.254/latest/meta-data/",
    "https://storage.googleapis.com/some-other-bucket/file",
    "https://shopify-staged-uploads.storage.googleapis.com:8443/"])
def test_upload_destinations_are_strictly_allowlisted(url):
    assert not photos._allowed_staged_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 302, 403])
async def test_transfer_posts_multipart_file_last_without_following_redirects(monkeypatch, status):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, headers={"location": "http://169.254.169.254/"})
    original = httpx.AsyncClient
    monkeypatch.setattr(photos.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    target = {"url": "https://shopify-staged-uploads.storage.googleapis.com/",
              "resourceUrl": "https://shopify-staged-uploads.storage.googleapis.com/tmp/image.png",
              "parameters": [{"name": "key", "value": "tmp/image.png"}, {"name": "policy", "value": "synthetic"}]}
    call = photos._transfer_photo(target, image_bytes(), "front.png", "image/png")
    if status == 201: await call
    else:
        with pytest.raises(HTTPException) as exc: await call
        assert exc.value.status_code == 502
    assert len(seen) == 1
    body = seen[0].content
    assert body.index(b'name="key"') < body.index(b'name="policy"') < body.index(b'name="file"')
    assert "authorization" not in seen[0].headers
