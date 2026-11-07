"""Staff approval follows the existing card/book/figure/sealed type contract."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import api
from app.schemas import InventoryApproval


@pytest.fixture
def approval(monkeypatch):
    inventory, owner = uuid4(), uuid4()
    item = {"id": inventory, "owner_id": owner, "product_type": "COMIC", "version": 2,
            "status": "INSPECTION", "condition": "Mint", "seal_status": None,
            "grading_company": None, "grade": None, "certificate_number": None,
            "acquisition_cost_minor": 500, "storage_location_id": uuid4(),
            "store_price_minor": 1000, "language": "English", "identity_confirmed": True}
    writes = []
    class Connection:
        async def fetchrow(self, sql, *args):
            assert args[:2] == (inventory, owner)
            if "update tcg.inventory_items" in sql:
                writes.append(sql)
                return dict(item, status="APPROVED", version=3)
            return dict(item)
    @asynccontextmanager
    async def connection(*args): yield Connection()
    async def current_owner(connection): return {"id": owner}
    monkeypatch.setattr(api, "user_connection", connection)
    monkeypatch.setattr(api, "_owner", current_owner)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id="book-approval-test"))
    async def run():
        return await api.approve_inventory(inventory, InventoryApproval(version=2), request,
                                          SimpleNamespace(user_id=uuid4()))
    return SimpleNamespace(item=item, writes=writes, run=run)


@pytest.mark.asyncio
@pytest.mark.parametrize("cost", [None, 0, 500])
@pytest.mark.parametrize("kind,condition,company,grade,seal", [
    ("COMIC", "Mint", None, None, None),
    ("COMIC", None, "CGC", "9.8", None),
    ("CARD", "Near Mint", None, None, None),
    ("FIGURE", "Like New", None, None, None),
    ("FIGURE", "New", None, None, "SEALED"),
    ("SEALED", None, None, None, "SEALED"),
])
async def test_ready_stock_uses_the_right_condition_or_seal_contract(approval, kind, condition, company, grade, seal, cost):
    approval.item.update(product_type=kind, condition=condition, grading_company=company,
                         grade=grade, seal_status=seal, acquisition_cost_minor=cost)
    result = await approval.run()
    assert result["status"] == "APPROVED"
    assert len(approval.writes) == 1
    assert approval.item["acquisition_cost_minor"] == cost
    assert "acquisition_cost_minor" not in approval.writes[0], "Approval must not invent or overwrite purchase cost"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,missing", [
    ("storage_location_id", None, "registered storage location"),
    ("identity_confirmed", False, "identity confirmation"),
    ("language", None, "language"),
    ("store_price_minor", None, "store price"),
    ("condition", None, "book condition"),
])
async def test_comics_keep_every_existing_intake_and_identity_gate(approval, field, value, missing):
    approval.item[field] = value
    with pytest.raises(HTTPException) as exc: await approval.run()
    assert exc.value.status_code == 422
    assert missing in exc.value.detail["missing"]
    assert "seal status" not in exc.value.detail["missing"]
    assert not approval.writes


@pytest.mark.asyncio
async def test_book_seal_and_mixed_raw_graded_state_still_fail(approval):
    for changes in ({"seal_status": "SEALED"}, {"seal_status": None, "grading_company": "CGC", "grade": "9.8"}):
        approval.item.update(changes)
        with pytest.raises(HTTPException) as exc: await approval.run()
        assert exc.value.status_code == 422
    assert not approval.writes
