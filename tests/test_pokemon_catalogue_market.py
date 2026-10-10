from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app import pokemon_catalogue_market as market

NOW = datetime(2026,10,10,tzinfo=timezone.utc)
REF = dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',provider_id='sv01-001',
           set_id='sv01',set_name='Scarlet & Violet',name='Pineco',card_number='001/198',declared_card_count=1)
PRODUCT = dict(idProduct=123,idExpansion=5223,idCategory=51,categoryName='Pokémon Single',name='Pineco [Guard Press]')
BOX = dict(idProduct=456,idExpansion=5223,idCategory=52,categoryName='Pokémon Booster',name='Scarlet & Violet Booster')
PRICE = dict(idProduct=123,idCategory=51,trend=.1,**{'trend-holo':.5})
FX = SimpleNamespace(rate=Decimal('.75'),source='ECB_EURO_REFERENCE_RATES',effective_at=NOW,retrieved_at=NOW)


def test_complete_unowned_checklist_matches_and_retains_source_and_printing_identity():
    matches=market.matched_products([REF],{'123':PRODUCT},{'456':BOX})
    assert matches=={'sv01-001':PRODUCT}
    quotes=market.quotes_for(REF,PRODUCT,PRICE,NOW,FX)
    assert [q['price_gbp_minor'] for q in quotes]==[8,38]
    assert quotes[0]['reference_identity']=={key:REF[key] for key in ('name','set_id','card_number','set_name')}
    assert all(q['physical_valuation_eligible'] is False and q['collector_number_supplied_by_marketplace'] is False for q in quotes)


@pytest.mark.parametrize('change',['provider','game','language','wrong_release','wrong_name','regional_release',
    'partial_checklist','unknown_count','duplicate_reference','duplicate_product','duplicate_release',
    'wrong_category','wrong_category_id','version_suffix','edition_suffix','number_suffix','gender'])
def test_ambiguous_partial_or_different_identity_is_not_priced(change):
    ref=deepcopy(REF);product=deepcopy(PRODUCT);box=deepcopy(BOX)
    refs=[ref];products={'123':product};boxes={'456':box}
    if change=='provider':ref['provider']='Unknown'
    if change=='game':ref['system_code']='ONE_PIECE_CARD_GAME'
    if change=='language':ref['language']='Japanese'
    if change=='wrong_release':box['name']='Other Set Booster'
    if change=='wrong_name':product['name']='Charizard [Guard Press]'
    if change=='regional_release':box['name']='Scarlet & Violet (Chinese) Booster'
    if change=='partial_checklist':ref['declared_card_count']=2
    if change=='unknown_count':ref['declared_card_count']=None
    if change=='duplicate_reference':refs.append({**ref,'provider_id':'sv01-201','card_number':'201/198'})
    if change=='duplicate_product':products['789']={**product,'idProduct':789}
    if change=='duplicate_release':boxes['789']={**box,'idProduct':789,'idExpansion':1}
    if change=='wrong_category':product['categoryName']='Pokémon Jumbo'
    if change=='wrong_category_id':product['idCategory']=1621
    if change=='version_suffix':product['name']='Pineco (V.1) [Guard Press]'
    if change=='edition_suffix':product['name']='Pineco (1st Edition) [Guard Press]'
    if change=='number_suffix':product['name']='Pineco (205) [Guard Press]'
    if change=='gender':ref['name']='Nidoran♀';product['name']='Nidoran♂ [Guard Press]'
    assert market.matched_products(refs,products,boxes)=={}


@pytest.mark.parametrize('field,value',[('idProduct',999),('idCategory',52),('trend',0),('trend',-1),('trend',True),('trend','NaN'),('trend',float('inf'))])
def test_invalid_price_or_wrong_category_is_rejected(field,value):
    price={**PRICE,field:value,'trend-holo':None}
    assert market.quotes_for(REF,PRODUCT,price,NOW,FX)==[]


@pytest.mark.asyncio
async def test_daily_pass_reads_entire_catalogue_without_inventory_and_does_not_hold_connection_for_provider(monkeypatch):
    writes=[];opened=0
    class Connection:
        async def fetch(self,sql):
            assert 'inventory' not in sql and 'reference_cards' in sql
            return [REF]
        async def executemany(self,sql,values):writes.extend(values)
    @asynccontextmanager
    async def connection(*args):
        nonlocal opened
        opened+=1
        try:yield Connection()
        finally:opened-=1
    async def download(client,path,**kwargs):
        assert opened==0
        if 'priceGuide' in path:return {'123':PRICE},NOW
        return ({'456':BOX} if 'nonsingles' in path else {'123':PRODUCT}),NOW
    class Provider:
        async def quote(self,**kwargs):
            assert opened==0
            return FX
    monkeypatch.setattr(market,'user_connection',connection)
    monkeypatch.setattr(market,'download',download)
    result=await market.refresh_pokemon_catalogue_prices(object(),uuid4(),Provider())
    assert result==dict(checked=1,matched=1,priced=1,provider_failures=0,inventory_rows_read=0)
    assert len(writes)==1 and writes[0][5:7]==(8,38)


@pytest.mark.asyncio
async def test_export_outage_preserves_existing_cache(monkeypatch):
    async def failed(*args,**kwargs):raise httpx.ReadTimeout('provider unavailable')
    def no_database(*args):raise AssertionError('No write on source failure')
    monkeypatch.setattr(market,'download',failed)
    monkeypatch.setattr(market,'user_connection',no_database)
    result=await market.refresh_pokemon_catalogue_prices(object(),uuid4(),object())
    assert result['provider_failures']==1 and result['priced']==0
