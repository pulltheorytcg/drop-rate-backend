from types import SimpleNamespace
import asyncio
import pytest
from app import catalogue_maintenance as maintenance


@pytest.mark.asyncio
@pytest.mark.parametrize('fails', [False, True])
async def test_source_archive_follows_pricing_and_is_bounded(monkeypatch, fails):
    calls = []
    sleeps = 0

    async def pricing(*args):
        calls.append('pricing')

    async def archive(*, apply):
        assert apply is True
        calls.append('archive')
        if fails:
            raise RuntimeError('private provider detail must not be logged')
        return dict(archive_id='fixed-checkpoint', status='BYTES_VERIFIED',
                    uploaded=True, file_count=14, source_bytes=6228589,
                    manifest_object={'key': 'drop-rate/exports/verified.json'})

    async def sleep(delay):
        nonlocal sleeps
        assert delay == 300
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(maintenance, 'daily_pass', pricing)
    monkeypatch.setattr(maintenance, 'archive_reviewed_openlibrary_sources', archive)
    monkeypatch.setattr(maintenance, 'archive_check_window', lambda now: None)
    monkeypatch.setattr(maintenance.asyncio, 'sleep', sleep)
    settings = SimpleNamespace(catalogue_source_archive_enabled=True)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(), settings)
    assert calls == ['pricing', 'archive', 'pricing']


@pytest.mark.asyncio
@pytest.mark.parametrize('shopify,enabled', [(False, False), (True, True)])
async def test_source_archive_is_opt_in_and_not_run_by_shopify(monkeypatch, shopify, enabled):
    async def ordinary(*args):
        pass

    async def unexpected(**kwargs):
        raise AssertionError('source archive must not run here')

    async def stop(delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(maintenance, 'daily_pass', ordinary)
    monkeypatch.setattr(maintenance, 'shopify_pass', ordinary)
    monkeypatch.setattr(maintenance, 'archive_reviewed_openlibrary_sources', unexpected)
    monkeypatch.setattr(maintenance, 'archive_check_window', lambda now: None)
    monkeypatch.setattr(maintenance.asyncio, 'sleep', stop)
    settings = SimpleNamespace(catalogue_source_archive_enabled=enabled)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(), settings, shopify=shopify)
