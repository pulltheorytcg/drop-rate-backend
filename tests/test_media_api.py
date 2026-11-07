"""Read-only media API is scoped to the active inventory owner and never publishes."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import media_api
from test_universal_media_resolver import physical
from test_media_resolver import _asset


OWNER = UUID("11111111-1111-4111-8111-111111111111")
OTHER_OWNER = UUID("22222222-2222-4222-8222-222222222222")
ITEM = UUID("33333333-3333-4333-8333-333333333333")
CATALOGUE = UUID("44444444-4444-4444-8444-444444444444")


@pytest.fixture
def scope(monkeypatch):
    calls = []

    class Connection:
        deny = False

        async def fetchrow(self, sql, *args):
            calls.append(("inventory", sql, args))
            assert "i.id=$1 and i.owner_id=$2" in sql
            assert args == (ITEM, OWNER)
            if self.deny:
                return None
            return {
                "id": ITEM, "owner_id": OWNER, "inventory_code": "INV-TEST-0001",
                "catalogue_id": CATALOGUE, "product_type": "CARD",
                "game": "Pokemon", "name": "Fixture",
                "set_name": "Example", "card_number": "1/10", "variant": "Normal",
                "language": "English", "catalogue_language": "English",
                "condition": "Near Mint", "grading_company": None, "grade": None,
                "status": "APPROVED", "store_price_minor": 500,
                "identity_confirmed": True,
            }

        async def fetch(self, sql, *args):
            calls.append(("media", sql, args))
            assert "scope='INVENTORY_ITEM' and inventory_id=$1 and owner_id=$2" in sql
            assert "scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')" in sql
            assert args == (ITEM, OWNER, CATALOGUE)
            canonical = _asset()
            canonical["catalogue_id"] = CATALOGUE
            owned_front = physical(owner=str(OWNER), inventory=str(ITEM))
            owned_back = physical(side="BACK", asset_id="back",
                                  owner=str(OWNER), inventory=str(ITEM))
            # This foreign photo is a sentinel: owner-scoped SQL must never
            # return it; if it did, the EBAY resolver must reject it.
            return [canonical, owned_front, owned_back]

        async def execute(self, *args, **kwargs):
            raise AssertionError("Read-only endpoint attempted to write")

    conn = Connection()

    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert user_id == OWNER and request_id == "dr106-test"
        yield conn

    async def owner(connection):
        assert connection is conn
        return {"id": OWNER}

    monkeypatch.setattr(media_api, "user_connection", connection)
    monkeypatch.setattr(media_api, "current_owner", owner)
    monkeypatch.setattr(media_api, "get_settings", lambda: SimpleNamespace(
        media_physical_photo_threshold_minor=5000
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="dr106-test"),
    )
    return conn, request, SimpleNamespace(user_id=OWNER), calls


@pytest.mark.asyncio
async def test_owner_gets_all_four_consistent_channel_decisions_without_writes(scope):
    conn, request, user, calls = scope
    result = await media_api.owner_media_decisions(ITEM, request, user)
    assert result["inventory_id"] == str(ITEM)
    assert result["mutated"] is False
    assert set(result["channels"]) == {"DROP_RATE", "SHOPIFY", "EBAY", "WHATNOT"}
    assert result["channels"]["DROP_RATE"]["selectedMedia"][0]["id"] == "photo"
    assert result["channels"]["SHOPIFY"]["publishReady"] is True
    assert result["channels"]["EBAY"]["publishReady"] is True
    assert len(result["channels"]["EBAY"]["imageUrls"]) == 2
    assert result["channels"]["WHATNOT"]["publishReady"] is False
    assert [name for name, *_ in calls] == ["inventory", "media"]


@pytest.mark.asyncio
async def test_owner_cannot_request_a_missing_or_foreign_inventory_item(scope):
    conn, request, user, calls = scope
    conn.deny = True
    with pytest.raises(HTTPException) as exc:
        await media_api.owner_media_decisions(ITEM, request, user)
    assert exc.value.status_code == 404
    assert [name for name, *_ in calls] == ["inventory"]


def test_signed_in_ui_consumes_only_read_only_media_preview():
    js = (Path(__file__).resolve().parents[1] /
          "backend/app/static/owner-inventory.js").read_text(encoding="utf-8")
    assert "/api/v1/media/resolve/" in js
    assert 'selected?.id!==previewItemId' in js
    assert 'alive(previewRevision,previewOwner)' in js
    assert '"WHATNOT","Whatnot"' in js
    assert "Image selection is separate from listing approval" in js
    assert "/api/v1/media/publish" not in js
