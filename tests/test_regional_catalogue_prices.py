from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx
import pytest
from app import regional_catalogue_prices as regional

NOW=datetime.now(timezone.utc)
KEY='r:'+'a'*32
REF={'key':KEY,'provider':'TCGdex','system_code':'POKEMON_TCG','provider_id':'me02-011',
     'set_id':'me02','set_name':'Phantasmal Flames','name':'Charmander','card_number':'011','language':'English'}
def quote():
    return {'source':'TCGDEX_CARDMARKET','variant_id':'normal','product_id':'123','finish':'Normal',
        'observed_at':NOW.isoformat(),'price_gbp_minor':99,
        'regional_sale':{'source_field':'avg7','region':'EU','price_gbp_minor':15,'original_minor':20,
            'fx_rate_to_gbp':'.75','fx_source':'ECB','fx_effective_at':(NOW-timedelta(hours=1)).isoformat(),
            'physical_valuation_eligible':False}}

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(regional,'display_permissions',lambda:{'TCGDEX_CARDMARKET'})
    monkeypatch.setenv('DROP_RATE_REGIONAL_TCGDEX_DAILY_LIMIT','2')

def test_unverified_downstream_rights_block_all_context():
    assert regional.eligible_quotes([quote()],NOW)==[]
    rows=[dict(REF,source_kind='REFERENCE',market_quotes=[quote()])]
    regional.attach_cached_regional_prices(rows)
    assert rows[0]['regional_context_permission'] is False
    assert rows[0]['regional_quotes']==[]

@pytest.mark.asyncio
async def test_disabled_sources_make_no_database_or_provider_requests(monkeypatch):
    forbidden=AsyncMock(side_effect=AssertionError('No disabled-feed request'))
    monkeypatch.setattr(regional,'fetch_quotes',forbidden)
    monkeypatch.setattr(regional,'_claim',forbidden)
    result=await regional.regional_prices_for_reference(None,uuid4(),'test',KEY)
    assert result['status']=='SOURCE_PERMISSION_UNVERIFIED'
    assert result['quotes']==[]
    assert result['blocked_sources']['TCGDEX_TCGPLAYER']=='TCGPLAYER_COMMERCIAL_REDISTRIBUTION_RESTRICTED'
    forbidden.assert_not_awaited()

@pytest.mark.asyncio
async def test_permitted_context_uses_its_own_cache_and_never_shared_price_writer(monkeypatch,enabled):
    c=AsyncMock();c.fetch.return_value=[REF]
    @asynccontextmanager
    async def session(*args):yield c
    token=uuid4();finish=AsyncMock(return_value=True)
    monkeypatch.setattr(regional,'user_connection',session)
    monkeypatch.setattr(regional,'_claim',AsyncMock(return_value=([],token,None)))
    monkeypatch.setattr(regional,'_finish',finish)
    monkeypatch.setattr(regional,'fetch_quotes',AsyncMock(return_value=[quote()]))
    result=await regional.regional_prices_for_reference(None,uuid4(),'test',KEY)
    assert result['status']=='AVAILABLE_CONTEXT'
    assert result['quotes'][0]['physical_valuation_eligible'] is False
    assert result['quotes'][0]['valuation_role']=='REGIONAL_CATALOGUE_CONTEXT_ONLY'
    assert finish.await_args.args[4]==token
    c.execute.assert_not_awaited() # Reference lookup cannot invoke any shared price writer.
    assert not hasattr(regional,'WRITE_SQL')

@pytest.mark.asyncio
async def test_429_propagates_durable_global_backoff_and_no_new_quote(monkeypatch,enabled):
    c=AsyncMock();c.fetch.return_value=[REF]
    @asynccontextmanager
    async def session(*args):yield c
    response=httpx.Response(429,headers={'retry-after':'7200'},request=httpx.Request('GET','https://api.tcgdex.net/test'))
    finish=AsyncMock(return_value=True)
    monkeypatch.setattr(regional,'user_connection',session)
    monkeypatch.setattr(regional,'_claim',AsyncMock(return_value=([],uuid4(),None)))
    monkeypatch.setattr(regional,'_finish',finish)
    monkeypatch.setattr(regional,'fetch_quotes',AsyncMock(side_effect=httpx.HTTPStatusError('rate limited',request=response.request,response=response)))
    result=await regional.regional_prices_for_reference(None,uuid4(),'test',KEY)
    assert result=={'quotes':[],'status':'PROVIDER_BACKOFF'}
    assert finish.await_args.kwargs=={'backoff':7200,'rate_limited':True}
    assert finish.await_args.args[-1]==[]

@pytest.mark.parametrize('change',[
    {'observed_at':(NOW-timedelta(days=8)).isoformat()},
    {'variant_id':None},{'product_id':None},
    {'regional_sale':dict(quote()['regional_sale'],source_field='low')},
    {'regional_sale':dict(quote()['regional_sale'],fx_effective_at=(NOW+timedelta(hours=1)).isoformat())},
    {'regional_sale':dict(quote()['regional_sale'],fx_rate_to_gbp='NaN')},
    {'regional_sale':dict(quote()['regional_sale'],price_gbp_minor=True)},
])
def test_invalid_or_stale_context_is_rejected(change,enabled):
    assert regional.eligible_quotes([dict(quote(),**change)],NOW)==[]

@pytest.mark.parametrize('change',[{'language':'Japanese'},{'card_number':'012'},{'name':'Charmeleon'},{'set_id':'other'}])
def test_cache_identity_cannot_cross_printing_or_language(change):
    assert regional._identity_hash(dict(REF,**change))!=regional._identity_hash(REF)

@pytest.mark.parametrize('limit',['-1','501','invalid','0'])
def test_invalid_or_unconfigured_budget_fails_closed(monkeypatch,limit):
    monkeypatch.setenv('DROP_RATE_REGIONAL_TCGDEX_DAILY_LIMIT',limit)
    assert regional._daily_limit()==0
