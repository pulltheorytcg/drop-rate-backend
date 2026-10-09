from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal

import httpx
import pytest

from app import sealed_market as market
from app.fx import FxQuote
from app.reference_sealed import sealed_reference,cardmarket_product_id

NOW=datetime(2026,10,9,12,tzinfo=timezone.utc)
REFERENCE={'product_type':'BOOSTER_BOX','evidence':{'cardmarket_product_id':'12'}}
PRODUCTS={'12':{'idProduct':12,'idCategory':53,'categoryName':'Pokémon Booster Boxes'}}
PRICES={'12':{'idProduct':12,'idCategory':53,'trend':100}}


class FX:
    async def quote(self,**kwargs):return FxQuote('EUR','GBP',Decimal('.8'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')


@pytest.mark.asyncio
async def test_bulk_guide_requires_explicit_mapping_and_same_packaging_category():
    quote=await market.quote_for(REFERENCE,PRODUCTS,PRICES,NOW,FX(),game_name='Pokémon')
    assert quote['price_gbp_minor']==8000 and quote['physical_language_confirmed'] is False
    assert quote['valuation_role']=='MIXED_LANGUAGE_REFERENCE'
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
