"""Offline Python FastAPI -> Worker HMAC transport contract tests.

Never sends real Cloudflare requests, obtains Supabase credentials or creates
live routes. All actors and inventory use synthetic canonical UUIDs.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime,timezone,timedelta
import hashlib
import hmac
import json
from uuid import UUID

import httpx
import pytest

from app.d1_private_read_client import (
    D1PrivateReadGuard, signed_owner_inventory_request,
    fetch_verified_owner_inventory, validate_internal_endpoint,
    validate_private_inventory_response,
)

KEY = "a1"*32
ENDPOINT = "https://private-read.example.workers.dev/internal/v1/owner-inventory"
USER = UUID("11111111-1111-4111-8111-111111111111")
OWNER = UUID("33333333-3333-4333-8333-333333333333")
ITEM = UUID("55555555-5555-4555-8555-555555555551")
NOW = datetime(2026,11,9,11,0,tzinfo=timezone.utc)


def inventory(*, owner=None, item=None, amount=321, version=4):
    return {
        "id":str(item or ITEM),
        "inventory_code":"INV-PKM-000123",
        "catalogue_id":str(USER),
        "owner_id":str(owner or OWNER),
        "condition":"Near Mint",
        "grade":None,
        "language":"English",
        "status":"APPROVED",
        "version":version,
        "acquisition_cost_minor":amount,
        "market_value_minor":500,
        "store_price_minor":600,
        "currency":"GBP",
    }


def page(*, items=None, cursor=None, owner=None):
    return {
        "status":"VERIFIED_READ_ONLY",
        "owner_id":str(owner or OWNER),
        "owner_type":"FOUNDER",
        "founder_hq_allowed":False,
        "business_allowed":False,
        "inventory":items if items is not None else [inventory()],
        "next_cursor":cursor,
    }


def test_exact_hmac_contract_matches_worker_semantics_without_body_rewriting():
    url,body,headers=signed_owner_inventory_request(
        endpoint=ENDPOINT,secret_hex=KEY,
        verified_legacy_user_id=USER,
        cursor=None,limit=1,now=NOW,
    )
    assert url==ENDPOINT
    assert json.loads(body)=={
        "legacy_user_id":str(USER),"cursor":None,"limit":1,
    }
    assert headers["X-DR-Timestamp"]==str(int(NOW.timestamp()))
    envelope=("POST\n/internal/v1/owner-inventory\n"+
              headers["X-DR-Timestamp"]+"\n").encode()+body
    expected=hmac.new(bytes.fromhex(KEY),envelope,hashlib.sha256).hexdigest()
    assert headers["X-DR-Signature"]=="sha256="+expected
    assert headers["Content-Type"]=="application/json"
    assert str(USER).encode() in body
    assert str(OWNER).encode() not in body
    assert b"role" not in body and b"owner_id" not in body


@pytest.mark.asyncio
async def test_safe_read_round_trip_uses_exact_verified_legacy_user_id():
    observed=[]
    async def handler(request):
        assert request.method=="POST"
        assert str(request.url)==ENDPOINT
        assert request.headers["X-DR-Timestamp"]==str(int(NOW.timestamp()))
        assert "role" not in request.content.decode()
        assert "owner_id" not in request.content.decode()
        observed.append(request)
        return httpx.Response(200,json=page(items=[inventory()],cursor=str(ITEM)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await fetch_verified_owner_inventory(
            client=client,endpoint=ENDPOINT,secret_hex=KEY,
            verified_legacy_user_id=USER,limit=1,now=NOW,
        )
    assert result.owner_id==OWNER
    assert result.next_cursor==ITEM
    assert len(result.items)==1
    assert result.items[0]["acquisition_cost_minor"]==321
    assert len(observed)==1


@pytest.mark.parametrize("url",[
    "http://private-read.example.workers.dev/internal/v1/owner-inventory",
    "https://127.0.0.1/internal/v1/owner-inventory",
    "https://localhost/internal/v1/owner-inventory",
    "https://private-read.example.workers.dev:8443/internal/v1/owner-inventory",
    "https://evil@private-read.example.workers.dev/internal/v1/owner-inventory",
    "https://private-read.example.workers.dev/internal/v1/owner-inventory?x=1",
    "https://private-read.example.workers.dev/other",
    "https://private-read.example.workers.dev/internal/v1/owner-inventory#fragment",
])
def test_cannot_sign_ssrf_or_noncanonical_internal_worker_url(url):
    with pytest.raises(D1PrivateReadGuard):
        validate_internal_endpoint(url)


@pytest.mark.parametrize("bad",[
    {"verified_legacy_user_id":str(USER)},
    {"cursor":str(ITEM)},
    {"limit":0},{"limit":51},{"limit":True},
    {"secret_hex":"x"*64},
    {"now":datetime(2026,11,9,11,0)},
])
def test_rejects_unverified_user_or_cursor_and_bad_signature_config(bad):
    kwargs={
        "endpoint":ENDPOINT,"secret_hex":KEY,
        "verified_legacy_user_id":USER,"cursor":None,
        "limit":50,"now":NOW,
    }
    kwargs.update(bad)
    with pytest.raises(D1PrivateReadGuard):
        signed_owner_inventory_request(**kwargs)


@pytest.mark.parametrize("bad_page",[
    page(items=[inventory(owner=UUID(int=9))]),
    page(items=[inventory(version=0)]),
    page(items=[inventory(amount=-1)]),
    page(items=[inventory(amount=True)]),
    page(items=[inventory(item=UUID(int=1)),inventory(item=UUID(int=1))]),
    {**page(),"founder_hq_allowed":True},
    {**page(),"business_allowed":"false"},
    {**page(),"status":"UNVERIFIED"},
    {**page(),"extra_internal_record":"secret"},
])
def test_cross_owner_or_invalid_d1_row_is_never_returned(bad_page):
    with pytest.raises(D1PrivateReadGuard):
        validate_private_inventory_response(bad_page,page_limit=2,cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301,302,403,409,429,500,503])
async def test_bad_worker_status_never_triggers_redirects_or_fallback(code):
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(code,headers={"Location":"https://attacker.example/"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(D1PrivateReadGuard,match="rejected"):
            await fetch_verified_owner_inventory(
                client=client,endpoint=ENDPOINT,secret_hex=KEY,
                verified_legacy_user_id=USER,limit=2,now=NOW,
            )
    assert len(seen)==1


@pytest.mark.asyncio
async def test_transport_errors_do_not_reveal_secret_or_server_body():
    def handler(req):
        raise httpx.ConnectError("PRIVATE_SECRET 11111111 source item",request=req)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(D1PrivateReadGuard) as err:
            await fetch_verified_owner_inventory(
                client=client,endpoint=ENDPOINT,secret_hex=KEY,
                verified_legacy_user_id=USER,limit=2,now=NOW,
            )
    for forbidden in ["PRIVATE_SECRET","source item",KEY,str(USER)]:
        assert forbidden not in str(err.value)
