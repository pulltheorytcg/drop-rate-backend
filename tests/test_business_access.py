"""Pure guard tests; JWT/PostgreSQL and browser acceptance run separately."""
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.access_control import require_business_founder, current_access_context
from app import founder_accounts
from app.auth import require_user


class Connection:
    def __init__(self, role='PLATFORM_ADMIN', authorized=True, slot=1, kind='FOUNDER'):
        self.row = dict(user_id=uuid4(),owner_id=uuid4(),role=role,founder_authorized=authorized,
                        founder_slot=slot,owner_type=kind,display_name='Synthetic account')
        self.data_queries = []
    async def fetch(self, sql, *args):
        if 'from tcg.owner_memberships m' in sql:
            return [self.row]
        self.data_queries.append((sql, args))
        return []
    async def fetchval(self, sql, *args):
        self.data_queries.append((sql, args))
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize('slot', [1,2,3])
async def test_three_registered_slots_allowed(slot):
    assert (await require_business_founder(Connection(slot=slot)))['business_allowed'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [dict(role='OWNER'),dict(authorized=False),dict(slot=4),dict(slot=None),dict(kind='CONSIGNOR')])
async def test_business_cannot_be_granted_by_owner_type_or_generic_role(changes):
    with pytest.raises(HTTPException) as error:
        await require_business_founder(Connection(**changes))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_ordinary_owner_gets_false_capability():
    result=await current_access_context(Connection(role='OWNER',authorized=False,slot=None,kind='CONSIGNOR'))
    assert result['business_allowed'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['', '/inventory', '/activity'])
async def test_unregistered_admin_is_rejected_before_business_data(monkeypatch,path):
    connection=Connection(authorized=False)
    @asynccontextmanager
    async def pool(*args):
        yield connection
    monkeypatch.setattr(founder_accounts,'user_connection',pool)
    app=FastAPI();app.state.db_pool=object()
    app.dependency_overrides[require_user]=lambda:SimpleNamespace(user_id=uuid4())
    @app.middleware('http')
    async def request_id(request,call_next):
        request.state.request_id='business-unit';return await call_next(request)
    app.include_router(founder_accounts.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        response=await client.get('/api/v1/founder/accounts'+path)
        assert response.status_code==403
        assert connection.data_queries==[]
