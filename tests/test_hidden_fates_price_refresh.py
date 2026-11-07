from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import access_control, database_capacity
from app import pokemon_catalogue_market as pricing
from app import pokemon_subset_price_refresh as runner
from app.cardtrader_client import CardTraderApiError


def references():
    rows = [dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
                 provider_id=f'sma-SV{number}', name=f'Fixture {number}', set_id='sma',
                 set_name='Hidden Fates Shiny Vault', declared_card_count=94,
                 card_number=f'SV{number}/94') for number in range(1, 95)]
    for number, name in ((49, 'Charizard-GX'), (59, 'Mewtwo-GX'), (69, 'Umbreon-GX')):
        rows[number-1]['name'] = name
    return rows


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'title', 'language', 'number', 'count'])
def test_bounded_scope_requires_exact_complete_hidden_fates_identity(change):
    rows = references()
    pricing.validate_hidden_fates_scope(rows)
    if change == 'missing': rows.pop()
    elif change == 'duplicate': rows[-1] = rows[0]
    elif change == 'title': rows[0]['set_name'] = 'Hidden Fates'
    elif change == 'language': rows[0]['language'] = 'Japanese'
    elif change == 'number': rows[0]['card_number'] = '1/94'
    elif change == 'count': rows[0]['declared_card_count'] = 93
    with pytest.raises(ValueError):
        pricing.validate_hidden_fates_scope(rows)


@pytest.fixture
def environment(monkeypatch):
    state = SimpleNamespace(rows=references(), writes=[], receipts=[], provider_reads=0,
                            claims=[], claim_reads=0, fail_source=False, capacity_allowed=True,
                            locked=True, unlocks=0, admin=True)
    now = datetime.now(timezone.utc)
    products, blueprints = {}, []
    for number, blueprint_id, product_id, name in (
        (49, 121421, 381243, 'Charizard GX'),
        (59, 121431, 396937, 'Mewtwo GX'),
        (69, 121441, 396982, 'Umbreon GX'),
    ):
        products[str(product_id)] = dict(idProduct=product_id, idCategory=51,
            categoryName='Pokémon Single', idExpansion=1615, name=name)
        blueprints.append(dict(id=blueprint_id, game_id=5, expansion_id=1615,
            category_id=73, name=name, version=f'Shiny Rare | SV{number}/SV94',
            fixed_properties={'collector_number': f'SV{number}/SV94'}, card_market_ids=[product_id]))

    class Client:
        async def list_games(self):
            if state.fail_source: raise CardTraderApiError('Private upstream detail')
            return [dict(id=5, name='Pokémon')]
        async def list_expansions(self): return [dict(id=1615, game_id=5, name='Hidden Fates')]
        async def list_categories(self, **kwargs): return [dict(id=73, game_id=5, name='Pokemon Single Cards')]
        async def list_blueprints(self, **kwargs): return blueprints

    class Connection:
        async def fetch(self, sql, *args):
            if sql.startswith(pricing.READ_SQL):
                assert args == ('sma',)
                return deepcopy(state.rows)
            if sql == pricing.OUTSIDE_SCOPE_CLAIMS_SQL:
                state.claim_reads += 1
                claims = state.claims(state.claim_reads) if callable(state.claims) else state.claims
                return [dict(product_id=value) for value in claims]
            assert 'checked_at=$2' in sql
            return [dict(provider_id=value[3]) for value in state.writes]
        async def executemany(self, sql, values):
            assert sql == pricing.WRITE_SQL
            assert len(values) <= 94
            assert all(v[0:3] == ('TCGdex', 'POKEMON_TCG', 'English') and
                       v[3].startswith('sma-SV') and v[5] > 0 for v in values)
            state.writes.extend(values)
        async def fetchval(self, sql, *args):
            if 'pg_try_advisory_lock' in sql:
                assert args == (847220092,)
                return state.locked
            if 'pg_advisory_unlock' in sql:
                state.unlocks += 1
                return True
            assert 'reference_sync_runs' in sql
            state.receipts.append(('start', args))
            return uuid4()
        async def execute(self, sql, *args):
            assert 'update tcg.reference_sync_runs' in sql
            state.receipts.append(('finish', args))

    connection = Connection()
    @asynccontextmanager
    async def user_connection(*args): yield connection
    class Pool:
        def acquire(self): return user_connection()
    async def admin(connection):
        if not state.admin: raise PermissionError('Not an administrator')
    async def capacity(connection):
        return SimpleNamespace(refresh_allowed=state.capacity_allowed,
            report=lambda: {'refresh_allowed': state.capacity_allowed})
    async def download(client, path, **kwargs):
        state.provider_reads += 1
        if 'nonsingles' in path: return {}, now
        if 'singles' in path: return products, now
        return {key: dict(idProduct=int(key), idCategory=51, trend=10) for key in products}, now
    class FX:
        async def quote(self, **kwargs):
            return SimpleNamespace(rate=Decimal('0.85'), source='TEST_ECB',
                                   effective_at=now, retrieved_at=now)
    monkeypatch.setattr(pricing, 'user_connection', user_connection)
    monkeypatch.setattr(pricing, 'download', download)
    monkeypatch.setattr(runner, 'user_connection', user_connection)
    monkeypatch.setattr(runner, 'require_platform_admin', admin)
    monkeypatch.setattr(runner, 'check_database_capacity', capacity)
    monkeypatch.setattr(access_control, 'require_platform_admin', admin)
    monkeypatch.setattr(database_capacity, 'check_database_capacity', capacity)
    state.client, state.fx, state.pool, state.actor = Client(), FX(), Pool(), uuid4()
    return state


@pytest.mark.asyncio
async def test_dry_run_previews_actual_adapter_quotes_without_writing(environment):
    e = environment
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx)
    assert report['status'] == 'VERIFIED' and report['priced'] == 3
    assert not e.writes and not e.receipts and e.unlocks == 1
    assert {r['provider_id'] for r in report['preview']} == {'sma-SV49', 'sma-SV59', 'sma-SV69'}
    quote = report['preview'][0]['quotes'][0]
    assert quote['price_gbp_minor'] == 850 and quote['original_minor'] == 1000
    assert quote['original_currency'] == 'EUR' and quote['fx_rate_to_gbp'] == '0.85'
    assert quote['observed_at'] and quote['fx_effective_at'] and quote['fx_retrieved_at']
    assert quote['physical_valuation_eligible'] is False
    assert quote['match_basis'] == 'CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID'


@pytest.mark.asyncio
async def test_apply_only_writes_positive_subset_quotes_with_receipt_and_readback(environment):
    e = environment
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
    assert report['status'] == 'COMPLETE' and report['written'] == 3
    assert len(e.writes) == 3 and e.unlocks == 1
    assert [row[0] for row in e.receipts] == ['start', 'finish']
    assert e.receipts[-1][1][1] == 'COMPLETE'
    # The other91 references are untouched; no negative results clear old guides.
    assert {value[3] for value in e.writes} == {'sma-SV49', 'sma-SV59', 'sma-SV69'}


@pytest.mark.asyncio
async def test_provider_failure_preserves_all_prices_and_records_incomplete(environment):
    e = environment
    e.fail_source = True
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
    assert report['status'] == 'INCOMPLETE' and not e.writes
    assert e.receipts[-1][1][1] == 'INCOMPLETE'
    assert 'Private upstream detail' not in str(report)


@pytest.mark.asyncio
async def test_outside_scope_claim_is_excluded_before_preview(environment):
    e = environment
    e.claims = ['381243']
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx)
    assert report['outside_scope_conflicts'] == 1 and report['priced'] == 2
    assert 'sma-SV49' not in {row['provider_id'] for row in report['preview']}
    assert not e.writes


@pytest.mark.asyncio
async def test_new_outside_claim_at_commit_makes_entire_write_a_noop(environment):
    e = environment
    e.claims = lambda call: [] if call == 1 else ['381243']
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
    assert report['status'] == 'INCOMPLETE' and not e.writes
    assert e.receipts[-1][1][1] == 'INCOMPLETE'


@pytest.mark.parametrize('guard', ['busy', 'capacity', 'admin', 'partial_checklist'])
@pytest.mark.asyncio
async def test_guards_prevent_provider_calls_or_price_writes(environment, guard):
    e = environment
    if guard == 'busy': e.locked = False
    elif guard == 'capacity': e.capacity_allowed = False
    elif guard == 'admin': e.admin = False
    else: e.rows.pop()
    if guard == 'admin':
        with pytest.raises(PermissionError):
            await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
    else:
        report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
        assert report['status'] in {'BUSY', 'CAPACITY_BLOCKED', 'INCOMPLETE'}
    assert not e.writes and e.provider_reads == 0
    assert e.unlocks == (0 if guard == 'busy' else 1)


@pytest.mark.asyncio
async def test_capacity_is_rechecked_before_price_write(environment):
    e = environment
    checks = 0
    async def capacity(connection):
        nonlocal checks
        checks += 1
        return SimpleNamespace(refresh_allowed=checks == 1,
            report=lambda: {'refresh_allowed': checks == 1})
    # Runner preflight succeeds; adapter persistence preflight blocks.
    from unittest.mock import patch
    with patch.object(runner, 'check_database_capacity', capacity), \
         patch.object(database_capacity, 'check_database_capacity', capacity):
        report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx, apply=True)
    assert checks == 2 and report['status'] == 'INCOMPLETE' and not e.writes


@pytest.mark.asyncio
async def test_bounded_fill_requires_explicit_number_bridge_even_if_bulk_name_matches(environment, monkeypatch):
    e = environment
    monkeypatch.setattr(pricing, 'matched_products',
        lambda *args: {'sma-SV1': dict(idProduct=381243)})
    report = await runner.refresh_hidden_fates(e.pool, e.actor, e.client, e.fx)
    assert report['priced'] == 3
    assert 'sma-SV1' not in {row['provider_id'] for row in report['preview']}
