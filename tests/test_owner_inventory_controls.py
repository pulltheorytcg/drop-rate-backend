from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import owner_inventory as api
from app.access_control import require_owner_portal_request


@pytest.fixture
def harness(monkeypatch):
    owner, actor, item_id = uuid4(), uuid4(), uuid4()
    state = {"item": {"id": item_id, "owner_id": owner, "catalogue_id": uuid4(), "version": 3,
                     "inventory_code": "INV-ONE", "status": "DRAFT", "sale_intent": "PERSONAL_COLLECTION",
                     "language": "Japanese", "condition": None, "seal_status": "SEALED",
                     "grading_company": None, "grade": None, "certificate_number": None},
             "receipts": {}, "added": [], "writes": []}
    class Connection:
        async def execute(self, sql, *args):
            state["writes"].append((sql, args))
            if "insert into tcg.request_receipts" in sql:
                state["receipts"][args[1]] = {"payload_hash": args[2], "response": args[3]}
            if "status='WITHDRAWN'" in sql:
                state["item"]["status"] = "WITHDRAWN"
        async def fetchrow(self, sql, *args):
            if "from tcg.request_receipts" in sql:
                assert args[0] == owner
                return state["receipts"].get(args[1])
            if "select * from tcg.inventory_items" in sql:
                assert "owner_id=$2" in sql and args[1] == owner
                return deepcopy(state["item"]) if args[0] == item_id else None
            if "insert into tcg.inventory_items" in sql:
                assert args[2] == owner and "'DRAFT','PERSONAL_COLLECTION',false" in sql
                row = {"id": args[0], "inventory_code": args[1], "status": "DRAFT", "sale_intent": "PERSONAL_COLLECTION", "version": 1}
                state["added"].append(row)
                return row
            if "update tcg.inventory_items" in sql:
                assert "owner_id=$2 and version=$3" in sql and args[1] == owner
                state["item"].update(store_price_minor=args[3], status=args[4], sale_intent=args[5], version=args[2]+1)
                return {k:state["item"][k] for k in ("id","inventory_code","version","status","sale_intent","store_price_minor")}
            raise AssertionError(sql)
    @asynccontextmanager
    async def connection(*args):
        before = deepcopy(state)
        try:
            yield Connection()
        except Exception:
            state.clear(); state.update(before); raise
    monkeypatch.setattr(api, "user_connection", connection)
    wake = []
    monkeypatch.setattr(api, "request_shopify_sync", lambda request: wake.append(True))
    async def protect(*args):
        state["item"].update(sale_intent="PERSONAL_COLLECTION", version=state["item"]["version"]+1)
    withdrawal = AsyncMock(side_effect=protect)
    monkeypatch.setattr(api, "change_inventory_sale_intent", withdrawal)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())), state=SimpleNamespace(request_id="fixture"))
    return SimpleNamespace(state=state,id=item_id,owner=owner,request=request,user=SimpleNamespace(user_id=actor),
                           access={"owner_id":owner},wake=wake,withdrawal=withdrawal)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["selling_price", "approval_request", "add_copy", "withdraw_copy"])
@pytest.mark.parametrize("failure", ["foreign", "stale", "SOLD", "RESERVED", "WITHDRAWN"])
async def test_mutations_reject_foreign_stale_and_locked_copies(harness, route, failure):
    h=harness
    if failure in {"SOLD","RESERVED","WITHDRAWN"}: h.state["item"]["status"]=failure
    if route=="withdraw_copy" and failure=="WITHDRAWN":
        result=await api.withdraw_copy(h.id,api.VersionRequest(version=3),h.request,h.user,h.access)
        assert result["replayed"] and not h.withdrawal.called
        return
    item_id=uuid4() if failure=="foreign" else h.id
    version=2 if failure=="stale" else 3
    payload=(api.AddCopy(version=version,confirmed=True) if route=="add_copy" else
             api.VersionRequest(version=version) if route=="withdraw_copy" else api.SellingPrice(version=version,store_price_minor=1000))
    args=[item_id,payload,h.request,h.user,h.access]
    if route=="add_copy":args.append(uuid4())
    with pytest.raises(HTTPException) as error: await getattr(api,route)(*args)
    assert error.value.status_code==(404 if failure=="foreign" else 409)
    assert not h.state["added"] and not h.wake and not h.withdrawal.called


@pytest.mark.asyncio
async def test_seller_approval_requests_inspection_and_never_approves_identity(harness):
    h=harness;h.state["item"].update(identity_confirmed=False,acquisition_cost_minor=None,storage_location_id=None)
    result=await api.approval_request(h.id,api.SellingPrice(version=3,store_price_minor=1234),h.request,h.user,h.access)
    assert result["item"]["status"]=="INSPECTION" and result["item"]["sale_intent"]=="FOR_SALE"
    assert result["item"]["store_price_minor"]==1234 and h.wake==[True]
    assert h.state["item"]["identity_confirmed"] is False
    assert "acquisition_cost_minor" not in result["item"]


@pytest.mark.asyncio
async def test_selling_price_preserves_status_intent_and_market_value(harness):
    h=harness;h.state["item"].update(status="APPROVED",market_value_minor=888)
    await api.selling_price(h.id,api.SellingPrice(version=3,store_price_minor=1500),h.request,h.user,h.access)
    assert h.state["item"]["market_value_minor"]==888
    assert h.state["item"]["status"]=="APPROVED" and h.state["item"]["sale_intent"]=="PERSONAL_COLLECTION"


@pytest.mark.asyncio
async def test_add_copy_replay_survives_parent_change_without_duplicate(harness):
    h=harness;key=uuid4();payload=api.AddCopy(version=3,confirmed=True)
    first=await api.add_copy(h.id,payload,h.request,h.user,h.access,key)
    h.state["item"]["version"]=4
    replay=await api.add_copy(h.id,payload,h.request,h.user,h.access,key)
    assert replay["replayed"] and replay["item"]==first["item"] and len(h.state["added"])==1
    assert first["item"]["status"]=="DRAFT" and first["item"]["sale_intent"]=="PERSONAL_COLLECTION"
    with pytest.raises(HTTPException) as error:
        await api.add_copy(h.id,api.AddCopy(version=4,confirmed=True),h.request,h.user,h.access,key)
    assert error.value.status_code==409


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["grading_company", "grade", "certificate_number"])
async def test_quantity_never_duplicates_a_slab_certificate(harness, field):
    h=harness;h.state["item"][field]="10"
    with pytest.raises(HTTPException) as error:
        await api.add_copy(h.id,api.AddCopy(version=3,confirmed=True),h.request,h.user,h.access,uuid4())
    assert error.value.status_code==422 and not h.state["added"]


@pytest.mark.asyncio
async def test_remote_withdrawal_failure_keeps_history_and_local_protection(harness):
    h=harness
    async def failed(*args):
        h.state["item"].update(sale_intent="PERSONAL_COLLECTION",version=4)
        raise HTTPException(502,"Channel withdrawal needs retry")
    h.withdrawal.side_effect=failed
    with pytest.raises(HTTPException) as error: await api.withdraw_copy(h.id,api.VersionRequest(version=3),h.request,h.user,h.access)
    assert error.value.status_code==502 and h.state["item"]["status"]=="DRAFT"
    assert h.state["item"]["sale_intent"]=="PERSONAL_COLLECTION"
    assert not any("status='WITHDRAWN'" in sql for sql,_ in h.state["writes"])


@pytest.mark.asyncio
async def test_successful_withdrawal_protects_channels_before_lowering_active_stock(harness):
    h=harness
    await api.withdraw_copy(h.id,api.VersionRequest(version=3),h.request,h.user,h.access)
    assert h.withdrawal.await_count==1 and h.state["item"]["status"]=="WITHDRAWN"
    assert not any("delete" in sql.lower() for sql,_ in h.state["writes"])


@pytest.mark.parametrize("payload", [{"version":1,"store_price_minor":99},{"version":1,"store_price_minor":123.4},
    {"version":1,"store_price_minor":100,"owner_id":"foreign"},{"version":1,"store_price_minor":100,"identity_confirmed":True},
    {"version":1,"store_price_minor":100,"status":"APPROVED"}])
def test_seller_input_cannot_expand_authority_or_bypass_price_floor(payload):
    with pytest.raises(ValidationError):api.SellingPrice(**payload)


def test_every_inventory_control_requires_owner_portal_access():
    for route in api.router.routes:
        assert require_owner_portal_request in [dependency.call for dependency in route.dependant.dependencies]


@pytest.mark.asyncio
async def test_ambiguous_or_unsafe_artwork_is_not_guessed():
    catalogue=uuid4();item={"id":uuid4(),"catalogue_id":catalogue}
    for urls in [["https://www.onepiece-cardgame.com/a.png","https://www.onepiece-cardgame.com/b.png"],
                 ["http://127.0.0.1/private"],[]]:
        connection=SimpleNamespace(fetch=AsyncMock(return_value=[{"id":catalogue,"urls":urls}]))
        assert "reference_image_url" not in (await api.add_reference_artwork(connection,[dict(item)]))[0]
