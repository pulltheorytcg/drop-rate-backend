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


@pytest.mark.asyncio
async def test_japanese_quotes_require_matching_request_locale_and_use_japanese_endpoint():
    reference={**REFERENCE,'language':'Japanese','name':'パウワウ','set_name':'インフェルノX'}
    payload=deepcopy(PAYLOAD);payload['name']=reference['name'];payload['set']['name']=reference['set_name']
    assert await market.tcgdex_quotes(payload,reference,FX(),now=NOW)==[]
    quotes=await market.tcgdex_quotes(payload,reference,FX(),now=NOW,language='Japanese')
    assert quotes[0]['reference_language']=='Japanese'
    async def handler(request):
        assert request.url.path=='/v2/ja/cards/me02-021'
        return httpx.Response(200,json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await market.fetch_quotes(client,reference,FX(),now=NOW)


@pytest.mark.asyncio
async def test_tcgplayer_is_exact_finish_support_without_usd_to_gbp_fallback():
    payload=deepcopy(PAYLOAD);variant=payload['variants_detailed'][0]
    variant['thirdParty']['tcgplayer']=123
    variant['pricing']['tcgplayer']={'unit':'USD','updated':NOW.isoformat(),
        'normal':{'productId':123,'marketPrice':.42},'reverse-holofoil':{'productId':123,'marketPrice':99}}
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    assert len(quotes)==2 and market.price_view(KEY,quotes,now=NOW)['market_value_minor']==7
    assert quotes[1]['original_minor']==42 and 'price_gbp_minor' not in quotes[1]
    variant['pricing']['cardmarket']=None
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    view=market.price_view(KEY,quotes,now=NOW)
    assert view['market_value_minor'] is None and view['market_value_source']=='TCGDEX_TCGPLAYER'
    variant['pricing']['tcgplayer']['normal']['productId']=456
    assert await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)==[]
    variant['pricing']['tcgplayer']['normal']['productId']=123
    variant['pricing']['tcgplayer']['updated']=(NOW-timedelta(days=8)).isoformat()
    assert await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('treatment',[{'subtype':'unlimited'},{'subtype':'shadowless'},{'stamp':['mcdonalds']},{'stamp':['1st-edition']}])
async def test_named_variants_keep_exact_references_without_becoming_base_physical_prices(treatment):
    payload=deepcopy(PAYLOAD);payload['variants_detailed'][0].update(treatment)
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    assert len(quotes)==1 and quotes[0]['source']==market.VARIANT_SOURCE
    assert quotes[0]['physical_valuation_eligible'] is False
    assert quotes[0]['variant_label']!='Normal'
    assert market.price_view(KEY,quotes,now=NOW)['market_value_minor']==7


@pytest.mark.asyncio
@pytest.mark.parametrize('unpriced_other',[False,True])
async def test_marketplace_id_shared_across_editions_is_not_evidence_for_either(unpriced_other):
    payload=deepcopy(PAYLOAD)
    payload['variants_detailed'][0]['subtype']='shadowless'
    other=deepcopy(payload['variants_detailed'][0]);other.update(stamp=['1st-edition'],variantId='first-edition')
    if unpriced_other:other.pop('pricing')
    payload['variants_detailed'].append(other)
    assert await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)==[]


@pytest.mark.asyncio
async def test_separate_named_variants_keep_their_own_prices_in_reference_range():
    payload=deepcopy(PAYLOAD)
    other=deepcopy(payload['variants_detailed'][0]);other.update(stamp=['special-event'],variantId='event')
    other['thirdParty']['cardmarket']=123
    other['pricing']['cardmarket'].update(idProduct=123,trend=10)
    payload['variants_detailed'].append(other)
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    assert len(quotes)==2 and market.price_view(KEY,quotes,now=NOW)['market_value_high_minor']==750
    assert [q['price_gbp_minor'] for q in quotes if q['source']==market.SOURCE]==[7]


@pytest.mark.asyncio
async def test_named_variant_reference_cannot_value_a_physical_base_copy():
    from app.cardmarket_valuations import guide_values
    payload=deepcopy(PAYLOAD);payload['variants_detailed'][0]['stamp']=['special-event']
    quotes=await market.tcgdex_quotes(payload,REFERENCE,FX(),now=NOW)
    product=dict(REFERENCE,product_type='CARD',game='Pokémon',variant='Normal')
    reference=dict(REFERENCE,quotes=quotes,reference_language='English',reference_name=REFERENCE['name'],
                   reference_set_name=REFERENCE['set_name'],reference_number=REFERENCE['card_number'])
    assert guide_values(product,[reference],now=NOW)==[]


@pytest.mark.asyncio
async def test_detail_refresh_keeps_independent_catalogue_fallback_out_of_tcgdex_writes(monkeypatch):
    now=datetime.now(timezone.utc)
    quote=dict(source=market.CATALOGUE_SOURCE,price_gbp_minor=100,observed_at=now.isoformat(),
               reference_identity={key:REFERENCE[key] for key in ('name','set_id','card_number','set_name')})
    writes=[]
    class Connection:
        async def fetch(self,*args):return [{**REFERENCE,'catalogue_quotes':[quote]}]
        async def execute(self,sql,*args):writes.append(args)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    async def no_quotes(*args,**kwargs):return []
    monkeypatch.setattr(market,'user_connection',connection)
    monkeypatch.setattr(market,'fetch_quotes',no_quotes)
    view=(await market.refresh_reference_prices(object(),uuid4(),'test',[KEY]))[0]
    assert view['market_value_minor']==100 and view['market_value_source']==market.CATALOGUE_SOURCE
    assert writes[0][4]==[] and writes[0][5] is None
    quote['reference_identity']['name']='Wrong card'
    assert (await market.refresh_reference_prices(object(),uuid4(),'test',[KEY]))[0]['market_value_minor'] is None
