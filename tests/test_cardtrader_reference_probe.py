from copy import deepcopy

import pytest

from app.cardtrader_client import CardTraderApiError
from app.cardtrader_reference_probe import number_key, probe_cardtrader_references


def fixture():
    ref=dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',
             set_id='dp6',set_name='Legends Awakened',name='Azelf',card_number='1/146',provider_id='dp6-1')
    blueprint=dict(id=1,game_id=5,expansion_id=9,category_id=10,name='Azelf',version=None,
                   fixed_properties={'collector_number':'001'},card_market_ids=[123])
    product=dict(idProduct=123,idCategory=51,name='Azelf',idExpansion=99)
    class Client:
        calls=[]
        rows=[blueprint]
        expansions=[dict(id=9,game_id=5,name='Legends Awakened')]
        async def list_games(self): self.calls.append('games'); return [dict(id=5,name='Pokémon')]
        async def list_expansions(self): self.calls.append('expansions'); return self.expansions
        async def list_blueprints(self,*,expansion_id):
            assert expansion_id==9
            self.calls.append('blueprints'); return self.rows
    return ref,blueprint,product,Client()


@pytest.mark.asyncio
async def test_existing_provider_probe_is_bounded_read_only_and_preserves_inputs():
    ref,blueprint,product,client=fixture()
    original=deepcopy((ref,blueprint,product))
    result=await probe_cardtrader_references(client,[ref],{'123':product})
    assert result['status']=='COMPLETE' and result['read_only']
    assert result['provider_calls']==3 and result['price_writes']==0
    assert result['sets'][0]['exact_identity_candidates']==1
    assert result['sets'][0]['candidate_examples']==[
        dict(reference_id='dp6-1',blueprint_id=1,cardmarket_product_id='123')]
    assert (ref,blueprint,product)==original


@pytest.mark.parametrize('change',['reference_collision','blueprint_collision','multiple_market_ids',
                                   'wrong_name','wrong_market_name','missing_number','wrong_game',
                                   'regional_expansion','duplicate_expansion'])
@pytest.mark.asyncio
async def test_probe_does_not_count_ambiguous_or_unproven_cross_ids(change):
    ref,blueprint,product,client=fixture();refs=[ref]
    if change=='reference_collision':refs.append(dict(ref,provider_id='dp6-other'))
    if change=='blueprint_collision':client.rows=[blueprint,dict(blueprint,id=2)]
    if change=='multiple_market_ids':blueprint['card_market_ids']=[123,456]
    if change=='wrong_name':blueprint['name']='Other'
    if change=='wrong_market_name':product['name']='Other'
    if change=='missing_number':blueprint['fixed_properties']={}
    if change=='wrong_game':blueprint['game_id']=6
    if change=='regional_expansion':client.expansions[0]['name']+=' (Japanese)'
    if change=='duplicate_expansion':client.expansions.append(dict(client.expansions[0],id=10))
    result=await probe_cardtrader_references(client,refs,{'123':product})
    assert result['sets'][0].get('exact_identity_candidates',0)==0


@pytest.mark.asyncio
async def test_provider_failure_is_reported_without_credentials_or_writes():
    ref,blueprint,product,client=fixture()
    async def denied():raise CardTraderApiError('sensitive provider diagnostic',status_code=403)
    client.list_games=denied
    result=await probe_cardtrader_references(client,[ref],{'123':product})
    assert result['status']=='UNAVAILABLE' and result['http_status']==403
    assert result['provider_calls']==1 and result['price_writes']==0
    assert 'sensitive' not in str(result)


def test_collector_number_normalization_retains_printing_prefixes_and_suffixes():
    assert number_key('001/146')==number_key('1')
    assert number_key('XY001')!=number_key('1')
    assert number_key('1a')!=number_key('1')
    assert number_key('1 (Parallel)') is None
