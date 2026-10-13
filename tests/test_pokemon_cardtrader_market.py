from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import pokemon_catalogue_market as pk
from app.cardtrader_client import CardTraderApiError
from app.pokemon_cardtrader_market import MATCH_BASIS, cardtrader_matches, match_blueprints


def fixture():
    refs=[dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',
               provider_id='xyp-XY01',set_id='xyp',set_name='XY Black Star Promos',
               name='Chespin',card_number='XY01/211',declared_card_count=1)]
    expansion=dict(id=1558,game_id=5,name='XY Black Star Promos')
    blueprint=dict(id=132044,game_id=5,expansion_id=1558,category_id=73,name='Chespin',
                   version='Holo Promo | XY01',fixed_properties={'collector_number':'XY01'},
                   card_market_ids=[281337])
    product=dict(idProduct=281337,idCategory=51,categoryName='Pokémon Single',
                 idExpansion=1558,name='Chespin [Vine Whip | Seed Bomb]')
    return refs,expansion,blueprint,{'281337':product}


class Client:
    def __init__(self,expansion,blueprints):self.expansion=expansion;self.blueprints=blueprints
    async def list_games(self):return [dict(id=5,name='Pokémon')]
    async def list_expansions(self):return [self.expansion]
    async def list_categories(self,*,game_id):
        assert game_id==5
        return [dict(id=73,game_id=5,name='Pokemon Single Cards')]
    async def list_blueprints(self,*,expansion_id):
        assert expansion_id==self.expansion['id']
        return self.blueprints


@pytest.mark.asyncio
async def test_explicit_promo_number_and_cross_id_match_without_booster_packaging():
    refs,expansion,blueprint,singles=fixture()
    assert not pk.matched_products(refs,singles,{})
    matches,report,failed=await cardtrader_matches(Client(expansion,[blueprint]),refs,singles,{})
    assert list(matches)==['xyp-XY01'] and report['provider_calls']==4
    assert report['status']=='COMPLETE' and not failed
    proof=matches['xyp-XY01']['proof']
    assert proof['match_basis']==MATCH_BASIS and proof['physical_valuation_eligible'] is False
    assert proof['cardtrader_blueprint_id']==132044


@pytest.mark.parametrize('mutation',[
    'reference_duplicate','reference_other_name','blueprint_duplicate','unmapped_duplicate',
    'wrong_blueprint_name','wrong_market_name','different_number','multiple_cross_ids',
    'wrong_blueprint_game','wrong_expansion','wrong_category','wrong_market_category',
    'wrong_language','conflicting_product_id','conflicting_reference_id',
])
def test_identity_bridge_rejects_ambiguous_or_conflicting_printings(mutation):
    refs,expansion,blueprint,singles=fixture();blueprints=[blueprint]
    if mutation in {'reference_duplicate','reference_other_name'}:
        refs.append(dict(refs[0],provider_id='xyp-parallel',name='Other' if mutation=='reference_other_name' else 'Chespin'))
    if mutation in {'blueprint_duplicate','unmapped_duplicate'}:
        blueprints.append(dict(blueprint,id=999,card_market_ids=[] if mutation=='unmapped_duplicate' else [281337]))
    if mutation=='wrong_blueprint_name':blueprint['name']='Other'
    if mutation=='wrong_market_name':singles['281337']['name']='Other'
    if mutation=='different_number':blueprint['fixed_properties']['collector_number']='XY02'
    if mutation=='multiple_cross_ids':blueprint['card_market_ids']=[281337,999]
    if mutation=='wrong_blueprint_game':blueprint['game_id']=6
    if mutation=='wrong_expansion':blueprint['expansion_id']=999
    if mutation=='wrong_category':blueprint['category_id']=78
    if mutation=='wrong_market_category':singles['281337']['categoryName']='Pokémon Jumbo'
    if mutation=='wrong_language':refs[0]['language']='Japanese'
    if mutation=='conflicting_product_id':singles['281337']['idProduct']=999
    if mutation=='conflicting_reference_id':refs[0]['provider_id']='xyp-XY02'
    assert not match_blueprints(refs,blueprints,expansion,{73},singles)


@pytest.mark.parametrize('change',['partial_checklist','regional_title','digital','already_priced'])
@pytest.mark.asyncio
async def test_no_card_requests_for_ineligible_releases_or_already_covered_cards(change):
    refs,expansion,blueprint,singles=fixture()
    if change=='partial_checklist':refs[0]['declared_card_count']=2
    if change=='regional_title':expansion['name']+=' (Japanese)'
    if change=='digital':refs[0].update(set_id='A1',set_name='Genetic Apex')
    if change=='already_priced':refs[0]['current_detail_priced']=True
    class NoBlueprints(Client):
        async def list_blueprints(self,**kwargs):raise AssertionError('Ineligible source request')
    matches,report,failed=await cardtrader_matches(NoBlueprints(expansion,[blueprint]),refs,singles,{})
    assert not matches and report['provider_calls']==3 and not failed


@pytest.mark.asyncio
async def test_failed_existing_source_does_not_invent_or_refresh_prior_evidence():
    refs,expansion,blueprint,singles=fixture()
    class Outage(Client):
        async def list_blueprints(self,**kwargs):raise CardTraderApiError('secret detail',status_code=503)
    matches,report,failed=await cardtrader_matches(Outage(expansion,[blueprint]),refs,singles,{})
    assert not matches and report['status']=='PARTIAL' and failed=={'xyp'}
    assert 'secret detail' not in str(report)


@pytest.mark.asyncio
async def test_worker_persists_proven_guide_with_original_identity_and_source_trace(monkeypatch):
    refs,expansion,blueprint,singles=fixture();writes=[]
    now=datetime.now(timezone.utc)
    class Connection:
        async def fetch(self,sql):
            assert 'inventory' not in sql
            return refs
        async def executemany(self,sql,values):writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return {},now
        if 'singles' in path:return singles,now
        return {'281337':dict(idProduct=281337,idCategory=51,trend=1)},now
    class FX:
        async def quote(self,**kwargs):return SimpleNamespace(rate=Decimal('.85'),source='ECB_EURO_REFERENCE_RATES',effective_at=now,retrieved_at=now)
    monkeypatch.setattr(pk,'user_connection',connection);monkeypatch.setattr(pk,'download',download)
    report=await pk.refresh_pokemon_catalogue_prices(object(),uuid4(),FX(),cardtrader_client=Client(expansion,[blueprint]))
    assert report['provider_failures']==0 and report['cardtrader_bridge']['priced']==1
    assert writes[0][5]==85
    quote=writes[0][4][0]
    assert quote['match_basis']==MATCH_BASIS and quote['physical_valuation_eligible'] is False
    assert quote['reference_identity']=={key:refs[0][key] for key in ('name','set_id','card_number','set_name')}
    assert quote['source']=='CARDMARKET_CATALOGUE' and quote['product_id']=='281337'


@pytest.mark.asyncio
async def test_outage_preserves_old_bridge_cache_while_ordinary_guides_refresh(monkeypatch):
    refs,expansion,blueprint,singles=fixture();writes=[]
    refs[0]['existing_match_basis']=MATCH_BASIS
    refs.append(dict(refs[0],provider_id='dp6-1',set_id='dp6',set_name='Legends Awakened',
                     name='Azelf',card_number='1/146',existing_match_basis=None))
    singles['123']=dict(idProduct=123,idCategory=51,categoryName='Pokémon Single',
                        idExpansion=99,name='Azelf')
    now=datetime.now(timezone.utc)
    class Connection:
        async def fetch(self,sql):return refs
        async def executemany(self,sql,values):writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return {'pack':dict(idCategory=52,categoryName='Pokémon Booster',
                                                  name='Legends Awakened Booster',idExpansion=99)},now
        if 'singles' in path:return singles,now
        return {'123':dict(idProduct=123,idCategory=51,trend=1)},now
    class FX:
        async def quote(self,**kwargs):return SimpleNamespace(rate=Decimal('.85'),source='ECB_EURO_REFERENCE_RATES',effective_at=now,retrieved_at=now)
    class Outage(Client):
        async def list_blueprints(self,**kwargs):raise CardTraderApiError('Unavailable',status_code=503)
    monkeypatch.setattr(pk,'user_connection',connection);monkeypatch.setattr(pk,'download',download)
    report=await pk.refresh_pokemon_catalogue_prices(object(),uuid4(),FX(),cardtrader_client=Outage(expansion,[blueprint]))
    assert report['provider_failures']==1 and report['cardtrader_bridge']['status']=='PARTIAL'
    assert [row[3] for row in writes]==['dp6-1']


@pytest.mark.asyncio
async def test_same_source_product_cannot_silently_price_different_releases():
    refs,expansion,blueprint,singles=fixture()
    refs[0].update(set_id='dp1',set_name='Diamond & Pearl',provider_id='dp1-1',card_number='1/130')
    blueprint['fixed_properties']['collector_number']='1'
    expansion['name']='Diamond & Pearl'
    other_expansion=dict(expansion,id=999,name='Mysterious Treasures')
    refs.append(dict(refs[0],set_id='dp2',set_name=other_expansion['name'],provider_id='dp2-1'))
    class ReusedId(Client):
        async def list_expansions(self):return [expansion,other_expansion]
        async def list_blueprints(self,*,expansion_id):return [dict(blueprint,id=expansion_id,expansion_id=expansion_id)]
    matches,report,failed=await cardtrader_matches(ReusedId(expansion,[blueprint]),refs,singles,{})
    assert not matches and not failed and report['cross_release_conflicts']==2
