from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal

import httpx
import pytest

from app import sealed_market as market
from app.fx import FxQuote
from app.reference_sealed import sealed_reference,cardmarket_product_id

NOW=datetime(2026,10,9,12,tzinfo=timezone.utc)
REFERENCE={'product_type':'BOOSTER_BOX','evidence':{'cardmarket_product_id':'12'}}
PRODUCTS={'12':{'idProduct':12,'idCategory':53,'categoryName':'Pokémon Display'}}
PRICES={'12':{'idProduct':12,'idCategory':53,'trend':100}}


class FX:
    async def quote(self,**kwargs):return FxQuote('EUR','GBP',Decimal('.8'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')


@pytest.mark.asyncio
async def test_bulk_guide_requires_explicit_mapping_and_same_packaging_category():
    quote=await market.quote_for(REFERENCE,PRODUCTS,PRICES,NOW,FX(),game_name='Pokémon')
    assert quote['price_gbp_minor']==8000 and quote['physical_language_confirmed'] is False
    assert quote['valuation_role']=='MIXED_LANGUAGE_REFERENCE'
    deck=await market.quote_for(dict(REFERENCE,product_type='STARTER_DECK'),
       {'12':{'idProduct':12,'idCategory':53,'categoryName':'One Piece Preconstructed Decks'}},PRICES,NOW,FX(),game_name='One Piece')
    assert deck['price_gbp_minor']==8000
    for reference in ({**REFERENCE,'evidence':{}},{**REFERENCE,'product_type':'BOOSTER_PACK'}):
        assert await market.quote_for(reference,PRODUCTS,PRICES,NOW,FX(),game_name='Pokémon') is None
    for price in ({**PRICES['12'],'idCategory':52},{**PRICES['12'],'trend':0},{**PRICES['12'],'trend':'NaN'}):
        assert await market.quote_for(REFERENCE,PRODUCTS,{'12':price},NOW,FX(),game_name='Pokémon') is None


@pytest.mark.asyncio
async def test_bulk_feed_rejects_stale_duplicate_and_wrong_wrapper():
    good={'createdAt':NOW.isoformat(),'products':[PRODUCTS['12']]}
    for payload in (dict(good,createdAt=(NOW-timedelta(days=4)).isoformat()),
                    dict(good,products=good['products']*2),dict(good,products={})): 
        async def handler(request):return httpx.Response(200,json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError):await market.download(client,'fixture',rows_key='products',now=NOW)


def test_blueprint_retains_explicit_cross_provider_id_without_approving_language():
    row=sealed_reference({'id':12,'category_id':9,'name':'Box','card_market_ids':[271440]},{'id':10},'POKEMON_TCG',{'9':'BOOSTER_BOX'})
    assert row['evidence']['cardmarket_product_id']=='271440' and row['language']=='Unknown'
    assert row['evidence']['exact_product_verified'] is False


def test_current_and_legacy_cross_ids_reject_ambiguous_or_malformed_mappings():
    assert cardmarket_product_id({'cardmarket_id':271440})=='271440'
    assert cardmarket_product_id({'card_market_ids':[271440,'271440']})=='271440'
    for blueprint in ({'card_market_ids':[1,2]}, {'card_market_ids':[1],'cardmarket_id':2},
                      {'card_market_ids':True}, {'card_market_ids':[True]}, {'card_market_ids':[0]},
                      {'card_market_ids':['wrong']}, {'card_market_ids':[]}, {}):
        assert cardmarket_product_id(blueprint) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('category,packaging',[
    ('Dragon Ball Super Boosters','BOOSTER_PACK'),
    ('Dragon Ball Super Booster Boxes','BOOSTER_BOX'),
    ('Dragon Ball Super Starter Decks','STARTER_DECK'),
    ('Dragon Ball Super Draft Boxes','COLLECTION'),
    ('Dragon Ball Super Expansion Sets','COLLECTION'),
    ('Dragon Ball Super Special Packs','COLLECTION'),
])
async def test_dragon_ball_bulk_packaging_never_prices_a_case_as_a_single_box(category,packaging):
    product={'12':dict(PRODUCTS['12'],categoryName=category)}
    quote=await market.quote_for(dict(REFERENCE,product_type=packaging),product,PRICES,NOW,FX(),game_name='Dragon Ball Super')
    assert quote['price_gbp_minor']==8000 and quote['source']==market.SOURCE
    assert quote['physical_language_confirmed'] is False and quote['condition_specific'] is False
    for wrong in ('SEALED_PRODUCT','TIN','ELITE_TRAINER_BOX'):
        assert await market.quote_for(dict(REFERENCE,product_type=wrong),product,PRICES,NOW,FX(),game_name='Dragon Ball Super') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('outage',[False,True])
async def test_daily_dragon_ball_sealed_refresh_shares_exports_and_preserves_quotes_on_outage(monkeypatch,outage):
    from app import catalogue_maintenance
    downloads=[];writes=[];receipts=[]
    class DailyFX(FX):
        def __init__(self,**kwargs):pass
    class Connection:
        async def fetch(self,sql,system):
            assert 'tcg.reference_sealed_products' in sql and 'release_date<=current_date' in sql
            if not system.startswith('DRAGON_BALL'):return []
            return [dict(REFERENCE,provider='CardTrader',system_code=system,language='Unknown',provider_id=system)]
        async def executemany(self,sql,values):
            assert sql==market.WRITE_SQL
            writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    async def download(client,path,**kwargs):
        downloads.append(path)
        if outage and path.endswith('_13.json'):raise httpx.ReadTimeout('Fixture outage')
        values={'12':dict(PRODUCTS['12'],categoryName='Dragon Ball Super Booster Boxes')} if kwargs['rows_key']=='products' else PRICES
        return values,NOW
    async def receipt(*args):receipts.append(args);return 'run'
    monkeypatch.setattr(market,'user_connection',connection)
    monkeypatch.setattr(market,'download',download)
    monkeypatch.setattr(market,'EcbHistoricalFxProvider',DailyFX)
    monkeypatch.setattr(catalogue_maintenance,'receipt',receipt)
    report=await market.refresh_sealed_prices(None,'actor')
    if outage:
        assert not writes and report['provider_failures']==2
        assert receipts[-1][3]=='INCOMPLETE'
    else:
        assert report['priced']==2 and report['provider_failures']==0
        assert {v[1] for v in writes}=={'DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD'}
        assert all(v[5]==8000 and v[4][0]['valuation_role']=='MIXED_LANGUAGE_REFERENCE' for v in writes)
        assert downloads.count('productList/products_nonsingles_13.json')==1
        assert downloads.count('priceGuide/price_guide_13.json')==1
        assert receipts[-1][3]=='COMPLETE'
