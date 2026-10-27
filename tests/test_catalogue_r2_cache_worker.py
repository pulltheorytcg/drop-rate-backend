import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import catalogue_maintenance as maintenance


ACTOR = UUID('00000000-0000-4000-8000-000000000025')


def worker_settings(**updates):
    values = dict(catalogue_r2_cache_build_enabled=True,
                  catalogue_source_archive_enabled=False,
                  catalogue_maintenance_actor_user_id=str(ACTOR))
    values.update(updates)
    return SimpleNamespace(**values)


def stop_after_one_pass(monkeypatch):
    async def stop(delay):
        raise asyncio.CancelledError
    monkeypatch.setattr(maintenance.asyncio, 'sleep', stop)
    monkeypatch.setattr(maintenance, 'archive_check_window', lambda now: None)


@pytest.mark.asyncio
async def test_warming_follows_normal_work_and_limits_each_pass_to_twenty_scopes(monkeypatch):
    calls = []
    cursors = []

    async def pricing(*args):
        calls.append('pricing')

    async def source_archive(*, apply):
        assert apply is True
        calls.append('source')
        return dict(archive_id='fixed', status='BYTES_VERIFIED', uploaded=True,
                    file_count=14, source_bytes=6228589, manifest_object={})

    async def warm(pool, actor, *, cursor, limit, verify_query_parity):
        assert actor == ACTOR
        assert limit == 5
        assert cursor == (cursors[-1] if cursors else None)
        assert verify_query_parity is (not cursors)
        calls.append('warm')
        cursors.append(['provider', 'system', 'en', str(len(cursors) + 1)])
        return dict(next_cursor=cursors[-1], has_more=True, verified=5)

    monkeypatch.setattr(maintenance, 'daily_pass', pricing)
    monkeypatch.setattr(maintenance, 'archive_reviewed_openlibrary_sources', source_archive)
    monkeypatch.setattr(maintenance, 'warm_reference_snapshots', warm)
    stop_after_one_pass(monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(), worker_settings(catalogue_source_archive_enabled=True))
    assert calls == ['pricing', 'source', 'warm', 'warm', 'warm', 'warm']


@pytest.mark.asyncio
@pytest.mark.parametrize('fails', [False, True])
async def test_warming_stops_on_directory_end_or_failure(monkeypatch, fails):
    calls = []

    async def pricing(*args):
        calls.append('pricing')

    async def warm(*args, **kwargs):
        calls.append('warm')
        if fails:
            raise RuntimeError('failed bounded batch')
        return dict(next_cursor=None, has_more=False, verified=2)

    monkeypatch.setattr(maintenance, 'daily_pass', pricing)
    monkeypatch.setattr(maintenance, 'warm_reference_snapshots', warm)
    stop_after_one_pass(monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(), worker_settings())
    assert calls == ['pricing', 'warm']


@pytest.mark.asyncio
@pytest.mark.parametrize('shopify,enabled', [(False, False), (True, True)])
async def test_warming_requires_opt_in_and_does_not_run_in_shopify_worker(monkeypatch, shopify, enabled):
    calls = []

    async def ordinary(*args):
        calls.append('ordinary')

    async def warm(*args, **kwargs):
        calls.append('warm')

    monkeypatch.setattr(maintenance, 'daily_pass', ordinary)
    monkeypatch.setattr(maintenance, 'shopify_pass', ordinary)
    monkeypatch.setattr(maintenance, 'warm_reference_snapshots', warm)
    stop_after_one_pass(monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(), worker_settings(catalogue_r2_cache_build_enabled=enabled),
                                   shopify=shopify)
    assert calls == ['ordinary']
