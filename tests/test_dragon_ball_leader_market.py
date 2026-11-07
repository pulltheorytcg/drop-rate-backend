from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import dragon_ball_market as db
from app.cardmarket_valuations import guide_values
from app.dragon_ball_leader_market import IMAGE_ROOT, MATCH_BASIS, paired_leader_matches
from app.fx import FxQuote


def fixture():
    refs = [dict(provider='Bandai Official', system_code=db.MASTERS, language='English',
                 provider_id='428020:'+filename, set_id='428020', name=name,
                 card_number='BT20-023', rarity='Uncommon[UC]',
                 set_name='Z03 Booster -POWER ABSORBED-', image_url=IMAGE_ROOT+filename,
                 evidence={'card_type':'LEADER', 'detail_level':'OFFICIAL_CHECKLIST'})
            for filename, name in [('BT20-023.png', 'Android 18'),
                                   ('BT20-023_b.png', 'Android 18, Impenetrable Rushdown')]]
    products = {'697740': dict(idProduct=697740, idExpansion=5272, idCategory=1049,
                              categoryName='Dragon Ball Super Singles',
                              name='Android 18 // Android 18, Impenetrable Rushdown')}
    packs = {'one': dict(idCategory=1050, categoryName='Dragon Ball Super Boosters',
                         name='Power Absorbed Booster', idExpansion=5272)}
    return refs, products, packs


def test_actual_official_leader_sides_match_one_explicit_combined_product():
    refs, products, packs = fixture()
    assert not db.matched_products(refs, products, packs)
    matches = paired_leader_matches(refs, products, packs)
    assert len(matches) == 2
    assert {m['product']['idProduct'] for m in matches.values()} == {697740}
    assert {m['reference_face'] for m in matches.values()} == {'front', 'back'}
    assert all(m['reference_face_ids'] == [r['provider_id'] for r in refs] for m in matches.values())
    assert paired_leader_matches(list(reversed(refs)), products, packs) == matches


@pytest.mark.parametrize('change', [
    'missing_face', 'extra_face', 'parallel', 'same_name_other_number', 'wrong_number',
    'wrong_filename', 'wrong_image', 'wrong_provider', 'wrong_game', 'wrong_language',
    'wrong_set', 'wrong_rarity', 'not_leader', 'missing_evidence', 'wrong_detail_level',
    'market_duplicate', 'market_wrong_name', 'market_one_face', 'market_reverse_faces',
    'market_extra_face', 'market_wrong_category', 'market_wrong_category_name',
    'market_invalid_id', 'regional_pack', 'conflicting_expansion', 'wrong_release',
])
def test_no_pair_is_inferred_from_ambiguous_or_incomplete_identity(change):
    refs, products, packs = fixture()
    ref, product = refs[0], products['697740']
    if change == 'missing_face': refs.pop()
    if change == 'extra_face': refs.append(dict(ref, provider_id=ref['provider_id']+'_extra'))
    if change == 'parallel': refs.append(dict(ref, provider_id='428020:BT20-023_PR.png', card_number='BT20-023_PR'))
    if change == 'same_name_other_number': refs.append(dict(ref, provider_id='428020:BT20-024.png', card_number='BT20-024'))
    if change == 'wrong_number': ref['card_number'] = 'BT20-024'
    if change == 'wrong_filename': ref['provider_id'] = '428020:BT20-023_p1.png'
    if change == 'wrong_image': ref['image_url'] += '?other=printing'
    if change == 'wrong_provider': ref['provider'] = 'Other'
    if change == 'wrong_game': ref['system_code'] = db.FUSION
    if change == 'wrong_language': ref['language'] = 'Japanese'
    if change == 'wrong_set': ref['set_name'] = 'Another release'
    if change == 'wrong_rarity': ref['rarity'] = 'Rare[R]'
    if change == 'not_leader': ref['evidence']['card_type'] = 'BATTLE'
    if change == 'missing_evidence': ref['evidence'] = {}
    if change == 'wrong_detail_level': ref['evidence']['detail_level'] = 'UNVERIFIED'
    if change == 'market_duplicate': products['9999'] = dict(product, idProduct=9999)
    if change == 'market_wrong_name': product['name'] = 'Android 18 // Other'
    if change == 'market_one_face': product['name'] = 'Android 18'
    if change == 'market_reverse_faces': product['name'] = 'Android 18, Impenetrable Rushdown // Android 18'
    if change == 'market_extra_face': product['name'] += ' // Other'
    if change == 'market_wrong_category': product['idCategory'] = 999
    if change == 'market_wrong_category_name': product['categoryName'] = 'Other'
    if change == 'market_invalid_id': product['idProduct'] = True
    if change == 'regional_pack': packs['one']['name'] += ' (Non-English)'
    if change == 'conflicting_expansion': packs['two'] = dict(packs['one'], idExpansion=9999)
    if change == 'wrong_release': packs['one']['name'] = 'Other Booster'
    assert not paired_leader_matches(refs, products, packs)


def test_one_product_cannot_be_claimed_by_two_official_release_pairs():
    refs, products, packs = fixture()
    refs.extend([dict(r, set_id='428999', provider_id=r['provider_id'].replace('428020:', '428999:'))
                 for r in list(refs)])
    assert not paired_leader_matches(refs, products, packs)


@pytest.mark.asyncio
@pytest.mark.parametrize('conflict', [False, True, 'reused_product'])
async def test_worker_persists_both_faces_or_rejects_entire_conflicting_pair(monkeypatch, conflict):
    refs, products, packs = fixture()
    now = datetime.now(timezone.utc)
    prices = {'697740': dict(idProduct=697740, idCategory=1049, trend=.12)}
    if conflict:
        refs.append(dict(refs[0], provider_id='428020:BT20-002.png', card_number='BT20-002',
                         name='Paparoni', evidence={'card_type':'BATTLE'}))
        products['697230'] = dict(products['697740'], idProduct=697230, name='Paparoni')
        prices['697230'] = dict(idProduct=697230, idCategory=1049, trend=.04)
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
            return FxQuote('EUR', 'GBP', Decimal('.85'), now, now, 'ECB_EURO_REFERENCE_RATES')

    monkeypatch.setattr(db, 'user_connection', connection)
    monkeypatch.setattr(db, 'download', download)
    if conflict == 'reused_product':
        monkeypatch.setattr(db, 'matched_products', lambda *args: {
            (db.MASTERS, refs[2]['provider_id']): products['697740']})
    elif conflict:
        monkeypatch.setattr(db, 'matched_products', lambda *args: {
            (db.MASTERS, refs[0]['provider_id']): dict(products['697740'], idProduct=9999),
            (db.MASTERS, refs[2]['provider_id']): products['697230']})
    report = await db.refresh_dragon_ball_prices(object(), uuid4(), FX())
    if conflict == 'reused_product':
        assert report['provider_failures'] == 1 and not writes
        assert report['masters_leader_pairs_conflicting'] == 1
        return
    assert report['provider_failures'] == 0
    assert len(writes) == len(refs)
    if conflict:
        assert report['masters_leader_pairs_conflicting'] == 1
        assert all(w[5] is None for w in writes[:2])
        assert writes[2][5] == 3
        return
    assert report['masters_leader_faces_priced'] == 2
    for ref, write in zip(refs, writes):
        assert write[5] == 10
        quote = write[4][0]
        assert quote['physical_valuation_eligible'] is False
        assert quote['match_basis'] == MATCH_BASIS
        assert quote['reference_identity']['name'] == ref['name']
        assert quote['reference_face_ids'] == [r['provider_id'] for r in refs]
        canonical = dict(product_type='CARD', game='Dragon Ball Super', name=ref['name'],
                         set_name='Power Absorbed', card_number=ref['card_number'],
                         variant='Normal', rarity='Uncommon', language='English')
        reference = dict(ref, reference_language='English', reference_name=ref['name'],
                         reference_set_name=ref['set_name'], reference_number=ref['card_number'],
                         reference_rarity=ref['rarity'], quotes=write[4])
        assert not guide_values(canonical, [reference], now=now)
