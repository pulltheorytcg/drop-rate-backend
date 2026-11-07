"""Exercise real discovery receipts with isolated feeds and atomic fake saves."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import catalogue_maintenance as jobs


IDENTITY_FIELDS = ('provider', 'system_code', 'language', 'set_id')
SAMPLE_FIELDS = IDENTITY_FIELDS + ('name', 'release_date', 'source_url')


def identity(record):
    return tuple(record[field] for field in IDENTITY_FIELDS)


def record(set_id):
    return dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
                set_id=set_id, name=f'Release {set_id}', release_date='2026-11-06',
                source_url=f'https://example.test/sets/{set_id}')


def batch(release):
    return release, [{'provider_id':f"{release['set_id']}-001"}]


async def run_sync(monkeypatch, records, *, known=(), source='tcgdex',
                   fail_identity=None, failure_point=None):
    state = SimpleNamespace(
        stored={identity(row):deepcopy(row) for row in known}, saved=[],
        progress=[], final=None, run_id=uuid4(), opened=False, closed=False)

    class Feed:
        def __init__(self):
            self.failures = []

        async def tcgdex(self):
            for release, items in records:
                yield deepcopy(release), deepcopy(items)

        async def close(self):
            state.closed = True

    feed = Feed()

    class Connection:
        def __init__(self):
            self.pending = []

        async def fetch(self, sql, *args):
            assert 'from tcg.reference_sets' in sql
            return list(state.stored.values())

        async def fetchval(self, sql, *args):
            assert 'insert into tcg.reference_sync_runs' in sql
            assert args == (source,)
            self.pending.append(('running', None))
            return state.run_id

        async def execute(self, sql, *args):
            assert args[0] == state.run_id
            if 'report=$5::jsonb' in sql:
                self.pending.append(('final', dict(
                    status=args[1], sets_loaded=args[2], cards_loaded=args[3],
                    report=json.loads(args[4]))))
            else:
                assert 'sets_loaded=$2,cards_loaded=$3' in sql
                self.pending.append(('progress', args[1:]))

    @asynccontextmanager
    async def connection(*args):
        conn = Connection()
        yield conn
        # A failed transaction never publishes its staged set or progress.
        if failure_point == 'commit' and any(
                action == 'save' and identity(value) == fail_identity
                for action,value in conn.pending):
            raise RuntimeError('set transaction commit failed')
        for action,value in conn.pending:
            if action == 'running':
                state.opened = True
            elif action == 'save':
                state.stored[identity(value)] = value
                state.saved.append(identity(value))
            elif action == 'progress':
                state.progress.append(value)
            else:
                state.final = value

    async def save(conn, release, items):
        assert state.opened
        conn.pending.append(('save', deepcopy(release)))
        if failure_point == 'save' and identity(release) == fail_identity:
            raise RuntimeError('set save failed')

    async def admin(conn):
        assert isinstance(conn, Connection)

    monkeypatch.setattr(jobs, 'ReferenceFeeds', lambda:feed)
    monkeypatch.setattr(jobs, 'user_connection', connection)
    monkeypatch.setattr(jobs, 'require_platform_admin', admin)
    monkeypatch.setattr(jobs, 'save_reference_set', save)
    monkeypatch.setattr(jobs, 'save_sealed_set', save)
    monkeypatch.setattr(jobs, 'CardTraderClient', lambda **kwargs:object())
    monkeypatch.setattr(jobs, 'sealed_feed', lambda client:feed.tcgdex())
    result = await jobs.sync_source(
        object(), uuid4(), source, SimpleNamespace(cardtrader_api_token='fixture'))
    assert state.closed and state.final is not None
    return result,state


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['tcgdex', 'cardtrader_sealed'])
async def test_refreshing_existing_set_does_not_report_a_discovery(monkeypatch, source):
    existing = record('known')
    refreshed = dict(existing, name='Refreshed title')
    result,state = await run_sync(monkeypatch, [batch(refreshed)], known=[existing], source=source)
    assert result == {'status':'COMPLETE', 'sets':1, 'records':1}
    assert state.stored[identity(existing)]['name'] == 'Refreshed title'
    assert state.final['report']['new_sets'] == 0
    assert state.final['report']['new_set_samples'] == []


@pytest.mark.asyncio
async def test_repeated_set_identity_is_counted_once_after_successful_saves(monkeypatch):
    first = record('new')
    repeated = dict(first, name='Updated feed title')
    result,state = await run_sync(monkeypatch, [batch(first), batch(repeated)])
    assert result == {'status':'COMPLETE', 'sets':2, 'records':2}
    assert state.saved == [identity(first), identity(first)]
    assert state.final['report']['new_sets'] == 1
    assert state.final['report']['new_set_samples'] == [
        {field:first[field] for field in SAMPLE_FIELDS}]


@pytest.mark.asyncio
async def test_discovery_identity_preserves_provider_game_and_language(monkeypatch):
    existing = record('shared-id')
    japanese = dict(existing, language='Japanese', release_date=None)
    other_provider = dict(existing, provider='Bandai Official')
    other_game = dict(existing, system_code='DRAGON_BALL_SUPER_FUSION_WORLD')
    new = [japanese, other_provider, other_game]
    result,state = await run_sync(monkeypatch,
        [batch(existing)] + [batch(row) for row in new], known=[existing])
    assert result['status'] == 'COMPLETE'
    assert state.final['report']['new_sets'] == 3
    assert state.final['report']['new_set_samples'] == [
        {field:row[field] for field in SAMPLE_FIELDS} for row in new]
    assert state.final['report']['new_set_samples'][0]['release_date'] is None
    assert len(state.stored) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_point', ['save', 'commit'])
async def test_partial_failure_receipt_counts_only_committed_discoveries(monkeypatch, failure_point):
    successful, failed, unreached = [record(name) for name in ('saved', 'failed', 'unreached')]
    result,state = await run_sync(monkeypatch,
        [batch(successful), batch(failed), batch(unreached)],
        fail_identity=identity(failed), failure_point=failure_point)
    assert result == {'status':'INCOMPLETE', 'sets':1, 'records':1}
    assert state.saved == [identity(successful)]
    assert state.progress == [(1,1)]
    assert identity(failed) not in state.stored and identity(unreached) not in state.stored
    assert state.final['status'] == 'INCOMPLETE'
    assert state.final['sets_loaded'] == state.final['cards_loaded'] == 1
    report = state.final['report']
    assert report['new_sets'] == 1
    assert report['new_set_samples'] == [{field:successful[field] for field in SAMPLE_FIELDS}]
    assert report['failures'] == [{'reason':'RuntimeError'}]


@pytest.mark.asyncio
async def test_discovery_total_is_complete_while_samples_are_bounded(monkeypatch):
    releases = [record(f'set-{index:02}') for index in range(35)]
    result,state = await run_sync(monkeypatch, [batch(row) for row in releases])
    assert result == {'status':'COMPLETE', 'sets':35, 'records':35}
    report = state.final['report']
    assert report['new_sets'] == 35
    assert len(report['new_set_samples']) == 30
    assert [identity(row) for row in report['new_set_samples']] == [
        identity(row) for row in releases[:30]]
    assert len(state.stored) == 35
