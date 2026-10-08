from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app import catalogue_browser as browser
from app import reference_market as market
from app.auth import require_user
from app.fx import FxQuote


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
KEY = 'r:' + 'a' * 32
REFERENCE = dict(key=KEY, provider='TCGdex', system_code='POKEMON_TCG', language='English',
                 provider_id='me02-021', set_id='me02', name='Seel', set_name='Phantasmal Flames', card_number='021/94')
PAYLOAD = dict(id='me02-021', name='Seel', localId='021', set=dict(id='me02', name='Phantasmal Flames'),
               variants=dict(normal=True,holo=False,reverse=True), variants_detailed=[dict(type='normal', size='standard', variantId='exact-normal',
                   thirdParty=dict(cardmarket=857596), pricing=dict(cardmarket=dict(unit='EUR', updated=NOW.isoformat(),
                       idProduct=857596, trend=.09, **{'trend-holo':.25})))])


class FX:
    async def quote(self, **kwargs):
        assert kwargs['at'] == NOW and kwargs['base_currency'] == 'EUR'
        return FxQuote('EUR', 'GBP', Decimal('.75'), NOW, NOW, 'ECB_EURO_REFERENCE_RATES')


@pytest.mark.asyncio
async def test_exact_finish_price_not_high_or_different_finish_and_auditable_fx():
    quotes = await market.tcgdex_quotes(PAYLOAD, REFERENCE, FX(), now=NOW)
    assert len(quotes) == 1
    assert quotes[0]['price_gbp_minor'] == 7
    assert quotes[0]['original_minor'] == 9
    assert quotes[0]['product_id'] == '857596'
    assert quotes[0]['finish'] == 'Normal'
    assert quotes[0]['fx_rate_to_gbp'] == '0.75'


@pytest.mark.asyncio
async def test_broad_reference_returns_finish_range_without_claiming_inventory_condition():
    payload = deepcopy(PAYLOAD)
    reverse = deepcopy(payload['variants_detailed'][0]); reverse.update(type='reverse', variantId='exact-reverse')
    payload['variants_detailed'].append(reverse)
    quotes = await market.tcgdex_quotes(payload, REFERENCE, FX(), now=NOW)
    view = market.price_view(KEY, quotes, now=NOW)
    assert (view['market_value_minor'], view['market_value_high_minor']) == (7, 19)
    assert view['basis_condition'] == 'Raw · Cardmarket'
    assert view['pricing_updated_at'] == NOW
    assert market.price_view(KEY, quotes, now=NOW+timedelta(days=8))['market_value_minor'] is None


@pytest.mark.asyncio
async def test_holo_only_base_sku_uses_base_trend_and_ambiguous_foil_is_rejected():
    payload=deepcopy(PAYLOAD)
    payload['variants']=dict(normal=False,holo=True,reverse=False)
    payload['variants_detailed'][0]['type']='holo'
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    assert quotes[0]['price_gbp_minor']==7 and quotes[0]['source_field']=='trend'
    payload['variants']=dict(normal=True,holo=True,reverse=True)
    assert await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)==[]
    payload['variants_detailed'][0]['type']='reverse'
    assert await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)==[]
    payload['variants']=dict(normal=True,holo=True,reverse=False)
    payload['variants_detailed'][0]['type']='holo'
    assert (await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW))[0]['price_gbp_minor']==19


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('provider_id','wrong-printing'), ('set_id','wrong-set'), ('name','Dewgong'),
    ('set_name','Different set'), ('card_number','022/94'), ('language','Japanese'), ('system_code','ONE_PIECE_CARD_GAME')])
async def test_wrong_identity_is_never_priced(field,value):
    assert await market.tcgdex_quotes(PAYLOAD, {**REFERENCE, field:value}, FX(), now=NOW) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['no_variant_id','no_product_id','wrong_product_id','wrong_currency','no_finish_price',
    'stale','future','timezone','zero','negative','nan','bool','no_variants','stamp','jumbo','conflicting_variant'])
async def test_invalid_ambiguous_or_unmatched_provider_evidence_fails_closed(change):
    payload = deepcopy(PAYLOAD); variant = payload['variants_detailed'][0]; source=variant['pricing']['cardmarket']
    if change == 'no_variant_id': variant.pop('variantId')
    if change == 'no_product_id': variant['thirdParty']={}
    if change == 'wrong_product_id': source['idProduct']=123
    if change == 'wrong_currency': source['unit']='USD'
    if change == 'no_finish_price': source.pop('trend')
    if change == 'stale': source['updated']=(NOW-timedelta(days=8)).isoformat()
    if change == 'future': source['updated']=(NOW+timedelta(days=1)).isoformat()
    if change == 'timezone': source['updated']='2026-10-08T12:00:00'
    if change in {'zero','negative','nan','bool'}: source['trend']={'zero':0,'negative':-1,'nan':'NaN','bool':True}[change]
    if change == 'no_variants': payload['variants_detailed']=[]
    if change == 'stamp': variant['stamp']='special event'
    if change == 'jumbo': variant['size']='jumbo'
    if change == 'conflicting_variant':
        other=deepcopy(variant); other['variantId']='another-treatment'; payload['variants_detailed'].append(other)
    assert await market.tcgdex_quotes(payload, REFERENCE, FX(), now=NOW) == []


@pytest.mark.asyncio
async def test_fetch_uses_fixed_host_and_encoded_master_id():
    seen=[]
    async def handler(request):
        seen.append(str(request.url)); return httpx.Response(200,json=PAYLOAD)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await market.fetch_quotes(client,REFERENCE,FX(),now=NOW)
    assert seen == ['https://api.tcgdex.net/v2/en/cards/me02-021']


@pytest.mark.asyncio
async def test_cache_retry_and_provider_failure_preserve_recent_quote_without_holding_db(monkeypatch):
    now=datetime.now(timezone.utc); quote=(await market.tcgdex_quotes(PAYLOAD,REFERENCE,FX(),now=NOW))[0]
    quote['observed_at']=now.isoformat()
    rows=[{**REFERENCE,'quotes':[quote],'expires_at':now-timedelta(minutes=1)}]
    writes=[]; opened=0; fetches=0
    class Connection:
        async def fetch(self,sql,keys): assert keys==[KEY]; return rows
        async def execute(self,sql,*args): writes.append((sql,args))
    @asynccontextmanager
    async def connection(pool,user,request):
        nonlocal opened
        opened+=1
        try: yield Connection()
        finally: opened-=1
    async def failed(*args,**kwargs):
        nonlocal fetches
        assert opened==0
        fetches+=1; raise httpx.ReadTimeout('provider down')
    monkeypatch.setattr(market,'user_connection',connection)
    monkeypatch.setattr(market,'fetch_quotes',failed)
    view=(await market.refresh_reference_prices(object(),uuid4(),'test',[KEY]))[0]
    assert view['market_value_minor']==7 and view['pricing_updated_at']==now
    assert len(writes)==1 and 'checked_at<=excluded.checked_at' in writes[0][0]
    assert writes[0][1][-1]-writes[0][1][-2] == timedelta(minutes=5)
    rows[0]['expires_at']=now+timedelta(hours=1)
    assert (await market.refresh_reference_prices(object(),uuid4(),'test',[KEY]))[0]['market_value_minor']==7
    assert len(writes)==1 and fetches==1


@pytest.mark.parametrize('payload',[{'keys':[KEY],'price':100},{'keys':[KEY],'owner_id':str(uuid4())},
    {'keys':['https://attacker.invalid']},{'keys':['c:'+str(uuid4())]},{'keys':[]},{'keys':[KEY]*41}])
def test_price_route_accepts_only_bounded_reference_keys(payload):
    with pytest.raises(ValidationError): browser.ReferencePriceRequest(**payload)


@pytest.mark.asyncio
async def test_price_route_requires_authentication_before_provider_access(monkeypatch):
    app=FastAPI(); app.include_router(browser.router)
    async def forbidden(*args,**kwargs): raise AssertionError('provider must not run')
    monkeypatch.setattr(browser,'refresh_reference_prices',forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post('/api/v1/catalogue-browser/market-values',json={'keys':[KEY]})).status_code in (401,403)


@pytest.mark.asyncio
async def test_price_route_deduplicates_and_keeps_authenticated_context(monkeypatch):
    user_id=uuid4(); owner_id=uuid4(); pool=object()
    async def refresh(got_pool,user,request,keys):
        assert got_pool is pool and user==user_id and request=='request' and keys==[KEY]
        return [market.price_view(KEY,[],now=NOW)]
    monkeypatch.setattr(browser,'refresh_reference_prices',refresh)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),state=SimpleNamespace(request_id='request'))
    result=await browser.market_values(browser.ReferencePriceRequest(keys=[KEY,KEY]),request,
        SimpleNamespace(user_id=user_id),{'owner_id':owner_id})
    assert result['items'][0]['market_value_minor'] is None
