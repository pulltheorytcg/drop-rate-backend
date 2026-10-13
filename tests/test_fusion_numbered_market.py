from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import dragon_ball_market as db
from app.cardmarket_valuations import guide_values
from app.fx import FxQuote


def fixture():
    refs = [dict(provider='Bandai Official', system_code=db.FUSION, language='English',
                 provider_id='583001:'+number, set_id='583001', name='Gowasu',
                 card_number=number, rarity=None,
                 set_name='BOOSTER PACK -AWAKENED PULSE- [FB01]')
            for number in ('FB01-040', 'FB01-041')]
    products = {str(pid): dict(idProduct=pid, idExpansion=5552, idCategory=1049,
                              categoryName='Dragon Ball Super Singles',
                              name=f'Gowasu ({ref["card_number"]}) [Fusion World]')
                for pid, ref in zip((756881, 756882), refs)}
    packs = {'one': dict(idCategory=1050, categoryName='Dragon Ball Super Boosters',
                         name='Awakened Pulse Booster [Fusion World]', idExpansion=5552)}
    return refs, products, packs


def test_exact_collector_numbers_distinguish_same_character_without_guessing():
    refs, products, packs = fixture()
    assert not db.matched_products(refs, products, packs)
    matches = db.numbered_fusion_matches(refs, products, packs)
    assert {key[1]: value['idProduct'] for key, value in matches.items()} == {
        '583001:FB01-040': 756881, '583001:FB01-041': 756882}
    assert db.numbered_fusion_matches(list(reversed(refs)), products, packs) == matches


@pytest.mark.parametrize('change', [
    'reference_parallel', 'reference_other_name', 'market_duplicate', 'market_other_name',
    'market_suffix', 'market_without_fusion', 'wrong_name', 'wrong_number',
    'wrong_language', 'wrong_provider', 'wrong_game', 'non_base_id',
    'wrong_release', 'regional_pack', 'conflicting_expansion',
])
def test_numbered_recovery_rejects_printing_and_source_identity_collisions(change):
    refs, products, packs = fixture()
    ref = refs[0]
    product = products['756881']
    if change.startswith('reference_'):
        refs.append(dict(ref, provider_id=ref['provider_id']+'_p1',
                         name='Other' if change=='reference_other_name' else ref['name']))
    if change.startswith('market_'):
        duplicate = dict(product, idProduct=9999)
        if change=='market_other_name': duplicate['name']=product['name'].replace('Gowasu','Other')
        if change=='market_suffix': duplicate['name']+=' (Parallel)'
        if change=='market_without_fusion': duplicate['name']=product['name'].replace(' [Fusion World]','')
        products['9999']=duplicate
    if change=='wrong_name': product['name']=product['name'].replace('Gowasu','Other')
    if change=='wrong_number': product['name']=product['name'].replace('FB01-040','FB01-042')
    if change=='wrong_language': ref['language']='Japanese'
    if change=='wrong_provider': ref['provider']='Other'
    if change=='wrong_game': ref['system_code']=db.MASTERS
    if change=='non_base_id': ref['provider_id']+='_p1'
    if change=='wrong_release': ref['set_name']='BOOSTER PACK -OTHER- [FB01]'
    if change=='regional_pack': packs['one']['name']+=' (Non-English)'
    if change=='conflicting_expansion': packs['other']=dict(packs['one'],idExpansion=9999)
    assert (db.FUSION,ref['provider_id']) not in db.numbered_fusion_matches(refs,products,packs)


@pytest.mark.asyncio
async def test_worker_persists_exact_number_guides_without_enabling_physical_values(monkeypatch):
    refs, products, packs = fixture()
    now = datetime.now(timezone.utc)
    prices = {pid: dict(idProduct=int(pid),idCategory=1049,trend=.04) for pid in products}
    writes = []

    class Connection:
        async def fetch(self, sql): return deepcopy(refs)
        async def executemany(self, sql, values):
            assert 'reference_market_prices' in sql and 'inventory_items' not in sql
            writes.extend(values)

    @asynccontextmanager
    async def connection(*args): yield Connection()

    async def download(client, path, **kwargs):
        if 'nonsingles' in path: return packs, now
        if 'singles' in path: return products, now
        return prices, now

    class FX:
        async def quote(self, **kwargs):
            return FxQuote('EUR','GBP',Decimal('.85'),now,now,'ECB_EURO_REFERENCE_RATES')

    monkeypatch.setattr(db,'user_connection',connection)
    monkeypatch.setattr(db,'download',download)
    report = await db.refresh_dragon_ball_prices(object(),uuid4(),FX())
    assert report['provider_failures']==0 and report['fusion_numbered_priced']==2
    assert report['fusion_numbered_conflicts']==0
    assert len(writes)==2
    for ref, write in zip(refs,writes):
        assert write[5]==3
        quote=write[4][0]
        assert quote['physical_valuation_eligible'] is False
        assert quote['match_basis']=='EXACT_FUSION_RELEASE_NAME_NUMBER_REFERENCE'
        assert quote['reference_identity']['card_number']==ref['card_number']
        canonical=dict(product_type='CARD',game='Dragon Ball Super Fusion World',
                       name=ref['name'],set_name='Awakened Pulse',card_number=ref['card_number'],
                       variant='Normal',rarity='Common',language='English')
        reference=dict(ref,reference_language='English',reference_name=ref['name'],
                       reference_set_name=ref['set_name'],reference_number=ref['card_number'],
                       reference_rarity=None,quotes=write[4])
        assert not guide_values(canonical,[reference],now=now)
