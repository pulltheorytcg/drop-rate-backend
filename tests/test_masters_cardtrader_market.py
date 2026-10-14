from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import dragon_ball_market as db
from app.cardtrader_client import CardTraderApiError
from app.masters_cardtrader_market import MATCH_BASIS, cardtrader_matches, match_blueprints


def fixture():
    # Observed public CardTrader metadata, 14 Oct 2026: the same named card
    # has explicit Special Rare and Super Rare blueprints, not V1/V2 guesses.
    ref = dict(provider='Bandai Official', system_code=db.MASTERS, language='English',
               provider_id='428024:BT24-013_PR.png', set_id='428024', card_number='BT24-013_PR',
               name='SS2 Vegeta, Charging Rage', rarity='Special Rare[SPR]',
               set_name='Z07 Booster -BEYOND GENERATIONS-',
               evidence={'detail_level': 'OFFICIAL_CHECKLIST', 'card_type': 'BATTLE'})
    refs = [ref, dict(ref, provider_id='428024:BT24-013.png', card_number='BT24-013',
                      rarity='Super Rare[SR]')]
    expansion = dict(id=3613, game_id=9, name='Beyond Generations', code='bt24')
    bp = dict(id=282434, name=ref['name'], game_id=9, category_id=138, expansion_id=3613,
              version='Special Rare', fixed_properties={'collector_number': 'BT24-013',
              'dragonball_rarity': 'Special Rare'}, card_market_ids=[762001])
    blueprints = [bp, dict(bp, id=282431, version='Super Rare', card_market_ids=[762000],
                           fixed_properties={'collector_number': 'BT24-013sr',
                                             'dragonball_rarity': 'Super Rare'})]
    product = dict(idProduct=762001, name=ref['name'], idCategory=1049,
                   categoryName='Dragon Ball Super Singles', idExpansion=5609)
    singles = {'762001': product, '762000': dict(product, idProduct=762000)}
    packaging = {'pack': dict(idCategory=1050, categoryName='Dragon Ball Super Boosters',
                              name='Beyond Generation Booster', idExpansion=5609)}
    return refs, expansion, blueprints, singles, packaging


class Client:
    def __init__(self, expansion, blueprints):
        self.expansion = expansion
        self.blueprints = blueprints

    async def list_games(self):
        return [dict(id=9, name='Dragon Ball Super')]

    async def list_categories(self, *, game_id):
        assert game_id == 9
        return [dict(id=138, game_id=9, name='Dragon Ball Super Singles')]

    async def list_expansions(self):
        return [self.expansion]

    async def list_blueprints(self, *, expansion_id):
        assert expansion_id == self.expansion['id']
        return self.blueprints


def leader_fixture():
    refs, expansion, blueprints, singles, packaging = fixture()
    leader_refs, leader_blueprints, leader_singles = [], [], {}
    for suffix, rarity, bid, pid in [('', 'Uncommon[UC]', 282512, 761976),
                                     ('_PR', 'Special Leader Rare[SLR]', 282508, 761977)]:
        number = 'BT24-001' + suffix
        for face, name in [('', 'Vegeta'), ('_b', 'Vegeta, Awakened Feelings')]:
            filename = number + face + '.png'
            leader_refs.append(dict(refs[0], name=name, provider_id='428024:' + filename,
                card_number=number, rarity=rarity,
                evidence={'detail_level': 'OFFICIAL_CHECKLIST', 'card_type': 'LEADER'},
                image_url='https://www.dbs-cardgame.com/images/cardlist/cardimg/' + filename))
        name = 'Vegeta // Vegeta, Awakened Feelings'
        leader_blueprints.append(dict(blueprints[0], name=name, id=bid, card_market_ids=[pid],
            version='Special Leader Rare' if suffix else None,
            fixed_properties={'collector_number': 'BT24-001slr' if suffix else 'BT24-001',
                              'dragonball_rarity': 'Leader' if suffix else 'Uncommon'}))
        leader_singles[str(pid)] = dict(singles['762001'], idProduct=pid, name=name)
    return leader_refs, expansion, leader_blueprints, leader_singles, packaging


def test_explicit_leader_rarity_and_exact_front_back_pair_share_one_market_product():
    refs, expansion, blueprints, singles, _ = leader_fixture()
    matches = match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)
    assert len(matches) == 4
    for index, ref in enumerate(refs):
        match = matches[(db.MASTERS, ref['provider_id'])]
        assert match['product']['idProduct'] == (761976 if index < 2 else 761977)
        assert match['proof']['reference_face'] == ('front' if index % 2 == 0 else 'back')
        assert match['proof']['reference_face_ids'] == [r['provider_id'] for r in refs[index // 2 * 2:index // 2 * 2 + 2]]
        assert match['proof']['cardtrader_rarity_source'] == ('rarity' if index < 2 else 'version')


@pytest.mark.parametrize('change', ['missing_back', 'wrong_back_number', 'wrong_image',
    'wrong_face_name', 'wrong_card_type', 'duplicate_pair', 'unknown_leader_rarity',
    'suffix_only_rarity', 'missing_market_back', 'reversed_market_faces', 'rarity_mismatch'])
def test_leader_pair_cannot_be_completed_or_classified_by_guessing(change):
    refs, expansion, blueprints, singles, _ = leader_fixture()
    front_key = (db.MASTERS, refs[2]['provider_id'])
    if change == 'missing_back': refs.pop()
    if change == 'wrong_back_number': refs[3]['card_number'] = 'BT24-002_PR'
    if change == 'wrong_image': refs[3]['image_url'] = refs[1]['image_url']
    if change == 'wrong_face_name': refs[3]['name'] = 'Wrong name'
    if change == 'wrong_card_type': refs[3]['evidence']['card_type'] = 'BATTLE'
    if change == 'duplicate_pair':
        refs.extend([dict(r, card_number='BT24-001_PR02', provider_id=r['provider_id'].replace('_PR', '_PR02'))
                     for r in refs[2:]])
    if change == 'unknown_leader_rarity': blueprints[1]['version'] = 'Leader'
    if change == 'suffix_only_rarity': blueprints[1]['version'] = None
    if change == 'missing_market_back': singles['761977']['name'] = 'Vegeta'
    if change == 'reversed_market_faces': singles['761977']['name'] = 'Vegeta, Awakened Feelings // Vegeta'
    if change == 'rarity_mismatch': refs[3]['rarity'] = 'Uncommon[UC]'
    matches = match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)
    assert front_key not in matches
    assert (db.MASTERS, '428024:BT24-001_PR_b.png') not in matches


def test_unmapped_collector_foil_blocks_only_its_own_explicit_rarity():
    refs, expansion, blueprints, singles, _ = leader_fixture()
    blueprints.append(dict(blueprints[0], id=283257, version='Collector Booster Foil', card_market_ids=[]))
    matches = match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)
    assert set(matches) == {(db.MASTERS, r['provider_id']) for r in refs[2:]}


@pytest.mark.asyncio
async def test_actual_rarity_distinguishes_identical_names_with_explicit_product_ids():
    refs, expansion, blueprints, singles, packaging = fixture()
    assert not db.matched_products(refs, singles, packaging)
    matches, report, failed = await cardtrader_matches(
        Client(expansion, blueprints), refs, singles, packaging, {})
    assert not failed and report['status'] == 'COMPLETE' and report['provider_calls'] == 4
    assert [matches[(db.MASTERS, r['provider_id'])]['product']['idProduct'] for r in refs] == [762001, 762000]
    for match in matches.values():
        assert match['proof']['match_basis'] == MATCH_BASIS
        assert match['proof']['physical_valuation_eligible'] is False


@pytest.mark.parametrize('change', [
    'duplicate_reference', 'different_name_duplicate', 'unmapped_duplicate', 'unknown_rarity',
    'missing_number', 'unknown_number_suffix', 'missing_reference_rarity', 'contradictory_abbreviation',
    'wrong_game', 'wrong_expansion', 'wrong_category', 'wrong_product_category',
    'wrong_market_release', 'wrong_market_name', 'wrong_blueprint_name', 'conflicting_cross_ids',
    'wrong_language', 'wrong_reference_id', 'missing_official_evidence', 'leader',
    'wrong_number', 'invalid_blueprint_id', 'invalid_product_id', 'unknown_reference_rarity',
])
def test_unpriced_unmapped_and_conflicting_prints_cannot_be_chosen(change):
    refs, expansion, blueprints, singles, _ = fixture()
    if change in {'duplicate_reference', 'different_name_duplicate'}:
        refs.append(dict(refs[0], provider_id='428024:BT24-013_PR02.png', card_number='BT24-013_PR02',
                         name='Different' if change == 'different_name_duplicate' else refs[0]['name']))
    if change == 'unmapped_duplicate':
        blueprints.append(dict(blueprints[0], id=999, card_market_ids=[]))
    if change == 'unknown_rarity':
        blueprints.append(dict(blueprints[0], id=999, fixed_properties={'collector_number': 'BT24-013'}))
    if change == 'missing_number':
        blueprints.append(dict(blueprints[0], id=999, fixed_properties={'dragonball_rarity': 'Unknown'}))
    if change == 'unknown_number_suffix':
        blueprints.append(dict(blueprints[0], id=999, fixed_properties={
            'collector_number': 'BT24-013 (Alternative)', 'dragonball_rarity': 'Special Rare'}))
    if change == 'missing_reference_rarity': refs[1]['rarity'] = None
    if change == 'unknown_reference_rarity': refs[1]['rarity'] = 'Unknown'
    if change == 'contradictory_abbreviation': refs[0]['rarity'] = 'Special Rare[SR]'
    if change == 'wrong_game': blueprints[0]['game_id'] = 999
    if change == 'wrong_expansion': blueprints[0]['expansion_id'] = 999
    if change == 'wrong_category': blueprints[0]['category_id'] = 999
    if change == 'wrong_product_category': singles['762001']['categoryName'] = 'Other'
    if change == 'wrong_market_release': singles['762001']['idExpansion'] = 999
    if change == 'wrong_market_name': singles['762001']['name'] = 'Other'
    if change == 'wrong_blueprint_name': blueprints[0]['name'] = 'Other'
    if change == 'conflicting_cross_ids': blueprints[0]['card_market_ids'] += [999]
    if change == 'wrong_language': refs[0]['language'] = 'Japanese'
    if change == 'wrong_reference_id': refs[0]['provider_id'] = '428024:BT24-014_PR.png'
    if change == 'missing_official_evidence': refs[0]['evidence'] = {}
    if change == 'leader': refs[0]['evidence']['card_type'] = 'LEADER'
    if change == 'wrong_number': blueprints[0]['fixed_properties']['collector_number'] = 'BT24-014'
    if change == 'invalid_blueprint_id': blueprints[0]['id'] = True
    if change == 'invalid_product_id': singles['762001']['idProduct'] = 999
    matches = match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)
    assert (db.MASTERS, refs[0]['provider_id']) not in matches


def test_bare_number_needs_release_family_and_rarity_without_dropping_reprints():
    refs, expansion, blueprints, singles, _ = fixture()
    for bp in blueprints:
        bp['fixed_properties']['collector_number'] = bp['fixed_properties']['collector_number'][5:]
    # An original-set reprint must not redefine bare-number expansion identity.
    refs.append(dict(refs[0], card_number='BT1-013', provider_id='428024:BT1-013.png'))
    assert len(match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)) == 2
    assert not match_blueprints(refs, blueprints, dict(expansion, code=None), {138}, singles, 5609)


def test_same_product_id_for_two_rarities_is_rejected_for_both():
    refs, expansion, blueprints, singles, _ = fixture()
    blueprints[1]['card_market_ids'] = [762001]
    assert not match_blueprints(refs, blueprints, expansion, {138}, singles, 5609)


@pytest.mark.parametrize('change', ['regional', 'fusion', 'prerelease', 'ambiguous_market', 'ambiguous_provider'])
@pytest.mark.asyncio
async def test_release_identity_is_independently_required_in_both_providers(change):
    refs, expansion, blueprints, singles, packaging = fixture()
    if change == 'regional': expansion['name'] += ' (Japanese)'
    if change == 'fusion': expansion['name'] = 'Fusion World: Beyond Generations'
    if change == 'prerelease': expansion['name'] += ' Pre-Release'
    if change == 'ambiguous_market': packaging['other'] = dict(packaging['pack'], idExpansion=999)
    class NoRequest(Client):
        async def list_expansions(self):
            return [expansion, dict(expansion, id=999)] if change == 'ambiguous_provider' else [expansion]
        async def list_blueprints(self, **kwargs):
            raise AssertionError('Ambiguous release requested')
    matches, report, failed = await cardtrader_matches(NoRequest(expansion, blueprints), refs, singles, packaging, {})
    assert not matches and not failed and report['sets_checked'] == 0


@pytest.mark.parametrize('outage', [False, True])
@pytest.mark.parametrize('leader', [False, True])
@pytest.mark.asyncio
async def test_refresh_retains_provenance_and_preserves_previous_evidence_during_outage(monkeypatch, outage, leader):
    refs, expansion, blueprints, singles, packaging = (leader_fixture if leader else fixture)()
    for ref in refs:
        ref['existing_match_basis'] = MATCH_BASIS
    now = datetime.now(timezone.utc)
    writes = []
    class Connection:
        async def fetch(self, sql):
            assert 'inventory' not in sql and 'existing_match_basis' in sql
            return refs
        async def executemany(self, sql, values): writes.extend(values)
    @asynccontextmanager
    async def connection(*args): yield Connection()
    async def download(client, path, **kwargs):
        if 'nonsingles' in path: return packaging, now
        if 'singles' in path: return singles, now
        return {key: dict(idProduct=int(key), idCategory=1049, trend=2, **{'trend-foil': 5})
                for key in singles}, now
    class FX:
        async def quote(self, **kwargs):
            return SimpleNamespace(rate=Decimal('.85'), source='ECB_EURO_REFERENCE_RATES',
                                   effective_at=now, retrieved_at=now)
    class Source(Client):
        async def list_blueprints(self, **kwargs):
            if outage: raise CardTraderApiError('private token detail', status_code=503)
            return self.blueprints
    monkeypatch.setattr(db, 'user_connection', connection)
    monkeypatch.setattr(db, 'download', download)
    # An ordinary match lets the refresh continue while the bridge is down.
    if outage:
        plain = dict(refs[0], name='Different card', card_number='BT24-014',
                     provider_id='428024:BT24-014.png', existing_match_basis=None)
        refs.append(plain)
        singles['99'] = dict(next(iter(singles.values())), idProduct=99, name=plain['name'])
    report = await db.refresh_dragon_ball_prices(object(), uuid4(), FX(),
                                                cardtrader_client=Source(expansion, blueprints))
    assert report['provider_failures'] == int(outage)
    assert 'private token detail' not in str(report)
    if outage:
        assert [row[3] for row in writes] == ['428024:BT24-014.png']
        return
    assert report['cardtrader_masters_bridge']['priced'] == (4 if leader else 2)
    assert report['cardtrader_masters_bridge']['leader_faces_priced'] == (4 if leader else 0)
    assert len(writes) == (4 if leader else 2)
    for row in writes:
        assert row[5:7] == (170, 425)
        for quote in row[4]:
            assert quote['match_basis'] == MATCH_BASIS
            assert quote['physical_valuation_eligible'] is False
            assert quote['physical_language_confirmed'] is False
            assert quote['condition_specific'] is False
            assert quote['source'] == 'CARDMARKET_BULK_SINGLES'
            assert quote['observed_at'] == now.isoformat()

