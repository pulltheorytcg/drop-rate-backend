"""The actual app mounts the bridge without weakening its HMAC/opt-in gates."""
import httpx
import pytest

from app.settings import get_settings
from test_drive_archive_api import SECRET, BASE, body, signed


@pytest.mark.asyncio
async def test_real_application_mounts_private_transfer_routes_and_denies_unapproved_calls(monkeypatch):
    from app.main import create_app

    for key, value in {
        'TCG_AUTH_ISSUER': 'https://example.supabase.co/auth/v1',
        'TCG_DATABASE_URL': 'postgresql://test:test@localhost/test',
        'TCG_AUTH_AUDIENCE': 'authenticated',
        'TCG_SUPABASE_PUBLISHABLE_KEY': 'test-only',
        'TCG_AUTOMATION_COMMAND_SECRET': SECRET,
        'TCG_OBJECT_STORE_ENABLED': 'false',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED', raising=False)
    get_settings.cache_clear()
    try:
        application = create_app()
        expected = {'/plan', '/reserve', '/object', '/verify-readback', '/complete'}
        routes = {route.path for route in application.routes}
        assert {BASE + suffix for suffix in expected} <= routes
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                     base_url='http://fixture') as client:
            command = body('PLAN_DRIVE_ARCHIVE_COPY')
            assert (await client.post(BASE + '/plan', json=command)).status_code == 401
            raw, headers = signed(command)
            disabled = await client.post(BASE + '/plan', content=raw, headers=headers)
            assert disabled.status_code == 409
            assert disabled.json()['detail'] == 'DRIVE_ARCHIVE_TRANSFER_DISABLED'
            monkeypatch.setenv('TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED', 'true')
            storage_off = await client.post(BASE + '/plan', content=raw, headers=headers)
            assert storage_off.status_code == 503
            assert storage_off.json()['detail'] == 'PRIVATE_ARCHIVE_STORAGE_UNAVAILABLE'
            assert (await client.get(BASE + '/object')).status_code == 405
    finally:
        get_settings.cache_clear()
