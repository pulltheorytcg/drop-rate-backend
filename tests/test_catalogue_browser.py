from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from app import catalogue_browser as browser
from app.auth import require_user


@pytest.mark.parametrize('role,roster,status', [('OWNER',False,200),('PLATFORM_ADMIN',True,200),('PLATFORM_ADMIN',False,403),(None,False,403)])
@pytest.mark.parametrize('path', ['/games','/sets?system_code=ONE_PIECE_CARD_GAME','/products?q=Luffy'])
@pytest.mark.asyncio
async def test_browse_access_and_own_counts(monkeypatch, role, roster, status, path):
    owner_id=uuid4(); user_id=uuid4(); queries=[]
    class Connection:
        async def fetch(self, sql, *args):
            if 'from tcg.owner_memberships m' in sql:
                return [] if role is None else [{'user_id':user_id,'owner_id':owner_id,'role':role,'founder_authorized':roster,
                    'display_name':'Test','owner_type':'FOUNDER' if roster else 'CONSIGNOR','founder_slot':1 if roster else None}]
            queries.append((sql,args)); return []
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(browser,'user_connection',connection)
    app=FastAPI(); app.state.db_pool=object(); app.include_router(browser.router)
    app.dependency_overrides[require_user]=lambda:SimpleNamespace(user_id=user_id)
    @app.middleware('http')
    async def request_id(request,call_next): request.state.request_id='test';return await call_next(request)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/api/v1/catalogue-browser'+path)
        assert response.status_code==status
    if status==403: assert not queries
    else:
        assert queries and all(args[0]==owner_id for _,args in queries)
        assert all('i.owner_id=$1' in sql for sql,_ in queries)


def test_query_is_parameterized_and_unknown_values_sort_last():
    attack="%' OR true --"
    sql,params=browser.product_query(owner_id=uuid4(),q=attack,system_code='ONE_PIECE_CARD_GAME',owned='owned',sort='value_desc')
    assert attack not in sql
    assert attack.split() in params
    assert 'coalesce(o.quantity,0)>0' in sql
    assert 'v.market_value_minor desc nulls last' in sql
    assert 'order by page.ordinal' in sql
    assert 'strpos' in sql
    assert 'i.owner_id=$1' in sql


def test_watchlist_empty_does_not_return_whole_catalogue():
    sql,params=browser.product_query(owner_id=uuid4(),keys=[])
    assert [] in params and 'e.key=any(' in sql


@pytest.mark.parametrize('extra', [{'owner_id':str(uuid4())},{'identity_confirmed':True},{'price':100},{'grading_company':'PSA'}])
def test_browse_intake_rejects_authority_and_price_fields(extra):
    with pytest.raises(ValidationError):
        browser.BrowseIntake(key='c:123',condition='Near Mint',confirmed=True,**extra)


def test_browse_intake_needs_human_and_consistent_physical_details():
    for payload in [{'confirmed':False,'condition':'Near Mint'}, {'confirmed':True},
                    {'confirmed':True,'condition':'Near Mint','seal_status':'SEALED'}]:
        with pytest.raises(ValidationError): browser.BrowseIntake(key='c:123',**payload)


def test_reference_creates_only_server_facts_and_unconfirmed_draft():
    payload=browser.BrowseIntake(key='r:123',condition='Near Mint',confirmed=True)
    record={'catalogue_id':None,'product_type':'CARD','game':'One Piece','name':'Luffy','set_name':'Set',
            'card_number':'OP11-118','provider_id':'OP11-118_p1','rarity':None,'language':'Japanese'}
    result=browser.intake_payload(record,payload)
    assert result.identity_confirmed is False
    assert result.new_catalogue.variant=='OP11-118_p1'
    assert result.new_catalogue.language=='Japanese'
    assert result.condition=='Near Mint'
    assert result.acquisition_cost_minor is None
    assert result.notes==browser.browse_note(payload)
    assert not hasattr(result,'owner_id')


def test_sealed_intake_cannot_become_raw_or_graded():
    record={'catalogue_id':uuid4(),'product_type':'SEALED'}
    result=browser.intake_payload(record,browser.BrowseIntake(key='c:123',seal_status='SEALED',confirmed=True))
    assert result.condition is None and result.grading_company is None and result.seal_status=='SEALED'
    with pytest.raises(HTTPException):
        browser.intake_payload(record,browser.BrowseIntake(key='c:123',condition='Near Mint',confirmed=True))


def test_incomplete_reference_requires_review_instead_of_server_error():
    record={'catalogue_id':None,'product_type':'CARD','game':'One Piece','name':'Luffy','set_name':'Set',
            'card_number':None,'provider_id':'unresolved-printing','rarity':None,'language':'Japanese'}
    with pytest.raises(HTTPException) as error:
        browser.intake_payload(record,browser.BrowseIntake(key='r:123',condition='Near Mint',confirmed=True))
    assert error.value.status_code==422
    assert 'catalogue review' in error.value.detail


@pytest.mark.asyncio
async def test_committed_intake_replays_before_reading_changed_reference(monkeypatch):
    owner_id=uuid4();request_key=uuid4()
    payload=browser.BrowseIntake(key='r:123',condition='Near Mint',confirmed=True)
    response={'inventory':{'inventory_code':'INV-EXISTING','notes':browser.browse_note(payload)},'replayed':False}
    class Connection:
        async def fetchrow(self,sql,*args):
            assert 'request_receipts' in sql
            assert args==(owner_id,request_key)
            return {'response':response}
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(browser,'user_connection',connection)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),state=SimpleNamespace(request_id='test'))
    result=await browser.intake(payload,request,SimpleNamespace(user_id=uuid4()),{'owner_id':owner_id},str(request_key))
    assert result['replayed'] is True and result['inventory']['inventory_code']=='INV-EXISTING'
    changed=payload.model_copy(update={'condition':'Lightly Played'})
    with pytest.raises(HTTPException) as error:
        await browser.intake(changed,request,SimpleNamespace(user_id=uuid4()),{'owner_id':owner_id},str(request_key))
    assert error.value.status_code==409
