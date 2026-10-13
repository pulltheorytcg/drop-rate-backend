"""Regression checks for real expansion/deck labels previously left unpriced."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import dragon_ball_market as db, one_piece_market as op
from app.dragon_ball_masters_missing_market import (
    EXPANSION_BASIS, _release_expansion_ids, exact_masters_supplemental_matches,
)
from app.fx import FxQuote


def masters_fixture():
    ref = dict(provider='Bandai Official', system_code=db.MASTERS, language='English',
               provider_id='428401:EX01-02.png', set_id='428401', name='Comrades Combined Vegeta',
               card_number='EX01-02', rarity='Expansion Rare[EX]',
               set_name='EXPANSION DECK BOX SET 01 -Mighty Heroes-')
    product = dict(idProduct=316895, name=ref['name'], idCategory=1049,
                   categoryName='Dragon Ball Super Singles', idExpansion=2088)
    pack = dict(idProduct=320607, name='Expansion Set: Mighty Heroes', idExpansion=2088,
                idCategory=1061, categoryName='Dragon Ball Super Expansion Sets')
    return ref, product, pack


def one_piece_fixture():
    ref = dict(provider='Punk Records', system_code='ONE_PIECE_CARD_GAME', language='English',
               provider_id='ST10-001', set_id='569010', name='Trafalgar Law',
               card_number='ST10-001', rarity='Leader',
               set_name='ULTRA DECK -The Three Captains- [ST-10]')
    product = dict(idProduct=744747, name='Trafalgar Law (ST10-001)', idCategory=1621,
                   categoryName='One Piece Single', idExpansion=5380)
    pack = dict(name='Ultimate Deck: The Three Captains', idExpansion=5380,
                idCategory=1625, categoryName='One Piece Preconstructed Decks')
    return ref, product, pack


@pytest.mark.parametrize('mutation', [
    'valid', 'regional_pack', 'wrong_category', 'wrong_release_year', 'wrong_number_family',
    'wrong_reference_file', 'wrong_game', 'japanese', 'parallel_with_different_name',
    'unpriced_source_duplicate', 'conflicting_expansion', 'missing_pack',
])
def test_masters_expansion_needs_complete_unique_print_and_exact_package(mutation):
    ref, product, pack = masters_fixture()
    refs, singles, packs = [ref], {'one': product}, {'one': pack}
    if mutation == 'regional_pack': pack['name'] += ' (Non-English)'
    if mutation == 'wrong_category': pack['idCategory'] = 1050
    if mutation == 'wrong_release_year': ref['set_name'] += ' 2024'
    if mutation == 'wrong_number_family':
        ref.update(card_number='EX02-02', provider_id='428401:EX02-02.png')
    if mutation == 'wrong_reference_file': ref['provider_id'] += '_PR'
    if mutation == 'wrong_game': ref['system_code'] = db.FUSION
    if mutation == 'japanese': ref['language'] = 'Japanese'
    if mutation == 'parallel_with_different_name':
        refs.append(dict(ref, name='Different face', card_number='EX01-02_PR',
                         provider_id='428401:EX01-02_PR.png'))
    if mutation == 'unpriced_source_duplicate': singles['two'] = dict(product, idProduct=999)
    if mutation == 'conflicting_expansion': packs['two'] = dict(pack, idExpansion=999)
    if mutation == 'missing_pack': packs.clear()
    before = deepcopy((refs, singles, packs))
    matches = exact_masters_supplemental_matches(refs, singles, packs)
    assert bool(matches) == (mutation == 'valid')
    assert (refs, singles, packs) == before


def test_box_versions_share_release_but_wrong_year_and_french_deck_do_not():
    def pack(name, expansion, category=1061):
        return dict(name=name, idExpansion=expansion, idCategory=category,
                    categoryName='Dragon Ball Super Expansion Sets' if category == 1061
                    else 'Dragon Ball Super Starter Decks')
    packs = {str(i): pack('Expansion Set: Special Anniversary Box 2020'+f' (Version {i})', 3173)
             for i in range(1, 5)}
    packs['2021'] = pack('Expansion Set: Special Anniversary Box 2021', 4368)
    packs['2024'] = pack('Premium 7th Anniversary Box 2024', 5904)
    packs['expert'] = pack('Expert Deck: Universe 6 Assailants', 2536, 1053)
    packs['french'] = pack('Expert Deck: Universe 6 Assailants (Version Française)', 999, 1053)
    assert _release_expansion_ids(packs) == {
        '428413': 3173, '428419': 4368, '428424': 5904, '428501': 2536,
    }
    packs['conflict'] = pack('Expansion Set: Special Anniversary Box 2020', 999)
    assert '428413' not in _release_expansion_ids(packs)


@pytest.mark.parametrize('official,pack_label,expected', [
    ('ULTRA DECK -The Three Captains- [ST-10]', 'Ultimate Deck: The Three Captains', 'thethreecaptains'),
    ('STARTER DECK -Zoro and Sanji- [ST-12]', 'Starter Deck: Zoro & Sanji', 'zorosanji'),
    ('ULTRA DECK -The Three Brothers- [ST-13]', 'Ultra Deck: The Three Brothers', 'thethreebrothers'),
    ('STARTER DECK -Red Edward.Newgate- [ST-15]', 'Starter Deck: Edward.Newgate', 'edwardnewgate'),
    ('STARTER DECK -Blue Donquixote Doflamingo- [ST-17]', 'Starter Deck: Donquixote Doflamingo', 'donquixotedoflamingo'),
    ('STARTER DECK -Black Smoker- [ST-19]', 'Starter Deck: Smoker', 'smoker'),
    ('STARTER DECK -Yellow Charlotte Katakuri- [ST-20]', 'Starter Deck: Charlotte Katakuri', 'charlottekatakuri'),
    ('STARTER DECK EX -GEAR5- [ST-21]', 'Starter Deck: EX Gear 5', 'exgear5'),
    ('STARTER DECK -Ace & Newgate- [ST-22]', 'Starter Deck: EX Ace & Newgate', 'exacenewgate'),
])
def test_recorded_deck_labels_keep_code_and_region_guards(official, pack_label, expected):
    identity = (expected, 'STARTER')
    assert op.release_identity(official) == identity
    assert op.release_identity(official, include_starters=False) is None
    pack = dict(name=pack_label, idExpansion=5380, idCategory=1625,
                categoryName='One Piece Preconstructed Decks')
    assert op.expansion_index({'one': pack})[identity] == 5380
    assert identity not in op.expansion_index({'one': dict(pack, name=pack_label+' (Japanese)')})
    assert identity not in op.expansion_index({'one': dict(pack, name=pack_label+' (Non-English)')})
    assert identity not in op.expansion_index({'one': pack, 'two': dict(pack, idExpansion=999)})
    assert op.release_identity(official[:-3]+'99]') != identity


@pytest.mark.parametrize('mutation', ['valid', 'parallel', 'unpriced_duplicate', 'wrong_number', 'region'])
def test_ultra_deck_price_match_still_requires_exact_card_number(mutation):
    ref, product, pack = one_piece_fixture()
    refs, products = [ref], {'one': product}
    if mutation == 'parallel': refs.append(dict(ref, provider_id='ST10-001_p1'))
    if mutation == 'unpriced_duplicate': products['two'] = dict(product, idProduct=999)
    if mutation == 'wrong_number': product['name'] = 'Trafalgar Law (ST10-002)'
    if mutation == 'region': pack['name'] += ' (Non-English)'
    assert bool(op.matched_products(refs, products, {'one': pack})) == (mutation == 'valid')


@pytest.mark.parametrize('module,fixture,basis', [
    (db, masters_fixture, EXPANSION_BASIS), (op, one_piece_fixture, op.STARTER_ALIAS_BASIS),
])
@pytest.mark.asyncio
async def test_worker_writes_traceable_gbp_reference_and_preserves_cache_on_outage(
        monkeypatch, module, fixture, basis):
    ref, product, pack = fixture()
    observed = datetime.now(timezone.utc)-timedelta(hours=2)
    writes = []
    class Connection:
        async def fetch(self, sql):
            assert 'inventory' not in sql
            return [ref]
        async def executemany(self, sql, values):
            assert 'inventory' not in sql and 'r.name=$11' in sql and 's.name=$14' in sql
            writes.extend(values)
    @asynccontextmanager
    async def connection(*args): yield Connection()
    async def download(client, path, **kwargs):
        if 'nonsingles' in path: return {'one': pack}, observed
        if 'singles' in path: return {str(product['idProduct']): product}, observed
        return {str(product['idProduct']): dict(idProduct=product['idProduct'],
                idCategory=product['idCategory'], trend='.24', **{'trend-foil': '.63'})}, observed
    class FX:
        async def quote(self, **kwargs):
            assert kwargs['at'] == observed
            return FxQuote('EUR', 'GBP', Decimal('.85'), observed, observed, 'ECB_EURO_REFERENCE_RATES')
    monkeypatch.setattr(module, 'download', download)
    monkeypatch.setattr(module, 'user_connection', connection)
    refresh = db.refresh_dragon_ball_prices if module is db else op.refresh_one_piece_prices
    report = await refresh(object(), uuid4(), FX())
    assert report['provider_failures'] == 0 and report['priced'] == 1
    assert report['masters_expansion_priced' if module is db else 'starter_alias_priced'] == 1
    assert len(writes) == 1 and writes[0][5] == 20 and writes[0][7] == observed
    for quote in writes[0][4]:
        assert quote['match_basis'] == basis and quote['physical_valuation_eligible'] is False
        assert quote['physical_language_confirmed'] is False and quote['condition_specific'] is False
        assert quote['product_id'] == str(product['idProduct'])
        assert quote['reference_identity'] == {k: ref[k] for k in ('name', 'set_id', 'card_number', 'set_name')}
    if module is db: assert writes[0][6] == 54
    writes.clear()
    async def unavailable(*args, **kwargs): raise ValueError('No current export')
    monkeypatch.setattr(module, 'download', unavailable)
    assert (await refresh(object(), uuid4(), FX()))['provider_failures'] == 1
    assert not writes
