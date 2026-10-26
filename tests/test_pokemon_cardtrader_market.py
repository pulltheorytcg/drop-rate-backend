from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import pokemon_catalogue_market as pk
from app.cardtrader_client import CardTraderApiError
from app.pokemon_cardtrader_market import MATCH_BASIS, cardtrader_matches, match_blueprints, cardtrader_release_titles


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


@pytest.mark.parametrize('reference,blueprint_name,market_name',[
    ('Nidoran ♀','Nidoran ♀','Nidoran [F] [Call for Family | Scratch | e-card]'),
    ('Nidoran ♂','Nidoran ♂','Nidoran [M] [Peck | e-card]'),
    ('Victini ◇','Victini ◇ Prism Star','Victini ◇ [Infinity | Prism]'),
])
def test_provider_gender_and_expanded_prism_labels_keep_exact_identity(reference,blueprint_name,market_name):
    refs,expansion,blueprint,singles=fixture()
    refs[0]['name']=reference;blueprint['name']=blueprint_name;singles['281337']['name']=market_name
    assert list(match_blueprints(refs,[blueprint],expansion,{73},singles))==['xyp-XY01']
    # An unpriced competing print is still ambiguous after name normalization.
    assert not match_blueprints(refs,[blueprint,dict(blueprint,id=999,card_market_ids=[])],expansion,{73},singles)


@pytest.mark.parametrize('reference,blueprint_name,market_name',[
    ('Nidoran ♀','Nidoran ♀','Nidoran [M] [Peck | e-card]'),
    ('Nidoran','Nidoran ♀','Nidoran [F] [Scratch | e-card]'),
    ('Victini','Victini ◇ Prism Star','Victini ◇ [Infinity | Prism]'),
    ('Victini ◇','Victini Prism Star','Victini ◇ [Infinity | Prism]'),
    ('Victini ◇','Victini ◇ Prism Star','Victini [Infinity | Prism]'),
    ('Victini ◇','Victini ◇ Prism Star (V.1)','Victini ◇ [Infinity | Prism]'),
])
def test_provider_label_normalization_cannot_change_gender_prism_or_version(reference,blueprint_name,market_name):
    refs,expansion,blueprint,singles=fixture()
    refs[0]['name']=reference;blueprint['name']=blueprint_name;singles['281337']['name']=market_name
    assert not match_blueprints(refs,[blueprint],expansion,{73},singles)


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

@pytest.mark.asyncio
async def test_existing_bridge_is_revalidated_even_when_detailed_quote_covers_card():
    refs,expansion,blueprint,singles=fixture()
    refs[0].update(current_detail_priced=True, existing_match_basis=MATCH_BASIS)
    matches,report,failed=await cardtrader_matches(Client(expansion,[blueprint]),refs,singles,{})
    assert list(matches)==['xyp-XY01']
    assert report['sets_checked']==1 and report['provider_calls']==4 and not failed

    # Conflicting new printings must still invalidate the bridge.
    duplicate=dict(blueprint,id=999,card_market_ids=[])
    matches,report,failed=await cardtrader_matches(Client(expansion,[blueprint,duplicate]),refs,singles,{})
    assert not matches and report['sets_checked']==1 and not failed


@pytest.mark.asyncio
async def test_existing_covered_bridge_outage_is_reported_for_cache_preservation():
    refs,expansion,blueprint,singles=fixture()
    refs[0].update(current_detail_priced=True, existing_match_basis=MATCH_BASIS)
    class Outage(Client):
        async def list_blueprints(self,**kwargs):raise CardTraderApiError('Unavailable',status_code=503)
    matches,report,failed=await cardtrader_matches(Outage(expansion,[blueprint]),refs,singles,{})
    assert not matches and report['provider_failures']==1 and failed=={'xyp'}


def hidden_fates_fixture():
    refs = [dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
                 provider_id='sma-SV49', set_id='sma', set_name='Hidden Fates Shiny Vault',
                 name='Charizard-GX', card_number='SV49/94', declared_card_count=94)]
    expansion = dict(id=1800, game_id=5, name='Hidden Fates')
    blueprint = dict(id=121421, game_id=5, expansion_id=1800, category_id=73,
                     name='Charizard GX', version='Shiny Rare | SV49/SV94',
                     fixed_properties={'collector_number': 'SV49/SV94'},
                     card_market_ids=[999001])
    singles = {'999001': dict(idProduct=999001, idCategory=51,
                             categoryName='Pokémon Single', idExpansion=1800,
                             name='Charizard GX [Wing Attack | Crimson Storm | Raging Out GX]')}
    return refs, expansion, blueprint, singles


def test_hidden_fates_parent_alias_is_exclusive_to_exact_cardtrader_subset():
    refs, _, _, _ = hidden_fates_fixture()
    assert cardtrader_release_titles(refs[0]) == {'Hidden Fates'}
    # Name-only bulk mapping must still see the subset, never its parent.
    assert pk.release_titles(refs[0]) == {'Hidden Fates Shiny Vault'}
    assert cardtrader_release_titles(dict(refs[0], set_id='other')) == {'Hidden Fates Shiny Vault'}
    assert cardtrader_release_titles(dict(refs[0], set_name='Hidden Fates Shiny Vault (Japanese)')) == {
        'Hidden Fates Shiny Vault (Japanese)'}


def test_hidden_fates_exact_sv_number_does_not_collide_with_base_charizard():
    refs, expansion, shiny, singles = hidden_fates_fixture()
    base = dict(shiny, id=121245, version='Full Art | 009/068',
                fixed_properties={'collector_number': '009/068'}, card_market_ids=[999002])
    singles['999002'] = dict(singles['999001'], idProduct=999002)
    matches = match_blueprints(refs, [base, shiny], expansion, {73}, singles)
    assert list(matches) == ['sma-SV49']
    assert matches['sma-SV49']['product']['idProduct'] == 999001
    assert matches['sma-SV49']['proof']['cardtrader_parent_release'] == 'Hidden Fates'
    assert matches['sma-SV49']['proof']['physical_valuation_eligible'] is False


@pytest.mark.parametrize('mutation', [
    'duplicate_blueprint', 'unmapped_duplicate', 'multiple_market_ids', 'base_number',
    'out_of_range_number', 'wrong_subset_title', 'regional_parent', 'wrong_name',
])
def test_hidden_fates_parent_alias_keeps_printing_ambiguity_guards(mutation):
    refs, expansion, blueprint, singles = hidden_fates_fixture()
    blueprints = [blueprint]
    if mutation == 'duplicate_blueprint':
        blueprints.append(dict(blueprint, id=999))
    elif mutation == 'unmapped_duplicate':
        blueprints.append(dict(blueprint, id=999, card_market_ids=[]))
    elif mutation == 'multiple_market_ids':
        blueprint['card_market_ids'] = [999001, 999002]
    elif mutation in {'base_number', 'out_of_range_number'}:
        number = '9' if mutation == 'base_number' else 'SV95'
        refs[0].update(provider_id='sma-' + number, card_number=number + '/94')
        blueprint['fixed_properties']['collector_number'] = number
    elif mutation == 'wrong_subset_title':
        refs[0]['set_name'] = 'Hidden Fates'
    elif mutation == 'regional_parent':
        expansion['name'] = 'Hidden Fates (Japanese)'
    elif mutation == 'wrong_name':
        blueprint['name'] = 'Charizard'
    assert not match_blueprints(refs, blueprints, expansion, {73}, singles)



@pytest.mark.parametrize('complete', [True, False])
@pytest.mark.asyncio
async def test_hidden_fates_parent_selection_requires_complete_canonical_subset(complete):
    refs, expansion, blueprint, singles = hidden_fates_fixture()
    exemplar = refs[0]
    refs = [dict(exemplar, provider_id='sma-SV' + str(number),
                 card_number='SV' + str(number) + '/94', name='Fixture ' + str(number))
            for number in range(1, 95 if complete else 94)]
    refs[48] = exemplar
    class CountedClient(Client):
        requests = 0
        async def list_blueprints(self, *, expansion_id):
            self.requests += 1
            assert complete, 'A partial checklist cannot request a parent expansion'
            return await super().list_blueprints(expansion_id=expansion_id)
    client = CountedClient(expansion, [blueprint])
    matches, report, failed = await cardtrader_matches(client, refs, singles, {})
    assert not failed
    assert list(matches) == (['sma-SV49'] if complete else [])
    assert client.requests == (1 if complete else 0)
    assert report['sets_checked'] == (1 if complete else 0)


@pytest.mark.parametrize('competing_ids', [[999001], [999001, 999003]])
def test_hidden_fates_rejects_unpriced_outside_subset_product_claims(competing_ids):
    refs, expansion, shiny, singles = hidden_fates_fixture()
    base = dict(shiny, id=121245, version='Full Art | 009/068',
                fixed_properties={'collector_number': '009/068'}, card_market_ids=competing_ids)
    # No base reference or positive cached price is present in this bounded pass.
    assert not match_blueprints(refs, [base, shiny], expansion, {73}, singles)
