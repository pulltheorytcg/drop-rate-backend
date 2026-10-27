from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import imports
from app import import_preview_rebuild as rebuild
from app.settings import Settings


def request(enabled=None):
    state = SimpleNamespace()
    if enabled is not None:
        state.settings = SimpleNamespace(import_preview_rebuild_enabled=enabled)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def batch(**changes):
    return {"version": 3, "status": "PREVIEW", "source_sha256": "a" * 64,
            "filename": "original.csv", "automatic_intake": False,
            "last_auto_apply_version": None, "committed_at": None, **changes}


def test_rebuild_setting_defaults_off_and_requires_an_explicit_boolean(monkeypatch):
    for value in (None, False, "true", 1):
        assert rebuild.rebuild_enabled(request(value)) is False
    assert rebuild.rebuild_enabled(request(True)) is True
    monkeypatch.setenv("TCG_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.setenv("TCG_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.delenv("TCG_IMPORT_PREVIEW_REBUILD_ENABLED", raising=False)
    assert Settings.from_env().import_preview_rebuild_enabled is False
    monkeypatch.setenv("TCG_IMPORT_PREVIEW_REBUILD_ENABLED", "true")
    assert Settings.from_env().import_preview_rebuild_enabled is True


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_application_exposes_its_validated_startup_flag(monkeypatch, enabled):
    from app.main import create_app
    from app.access_control import require_platform_admin_request
    from app.settings import get_settings

    for key, value in {
        "TCG_DATABASE_URL": "postgresql://unused",
        "TCG_AUTH_ISSUER": "https://example.test/auth/v1",
        "TCG_AUTH_AUDIENCE": "authenticated",
        "TCG_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "TCG_IMPORT_PREVIEW_REBUILD_ENABLED": "true" if enabled else "false",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        application = create_app()  # Lifespan is not run; no DB/network access.
        assert rebuild.rebuild_enabled(SimpleNamespace(app=application)) is enabled
        assert application.state.settings is get_settings()
        route = next(route for route in application.routes if route.path == "/api/v1/imports/{batch_id}/rebuild")
        assert require_platform_admin_request in [item.call for item in route.dependant.dependencies]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disabled_rebuild_cannot_reach_database():
    payload = imports.ImportPreviewRebuildRequest(filename="a.csv", content="Name\nCard", version=1)
    # No pool or actor exists: the default-off check must precede all DB access.
    with pytest.raises(HTTPException) as error:
        await imports.rebuild_import_preview(uuid4(), payload, request(), SimpleNamespace())
    assert error.value.status_code == 404


@pytest.mark.parametrize("changes,version,sha,code", [
    ({"version": 4}, 3, "a" * 64, 409),
    ({"status": "COMMITTED"}, 3, "a" * 64, 409),
    ({"status": "CANCELLED"}, 3, "a" * 64, 409),
    ({"committed_at": "2026-10-27"}, 3, "a" * 64, 409),
    ({"automatic_intake": True}, 3, "a" * 64, 409),
    ({"last_auto_apply_version": 2}, 3, "a" * 64, 409),
    ({}, 3, "b" * 64, 409),
    ({"filename": None}, 3, "a" * 64, 409),
    ({"filename": "old.xlsx"}, 3, "a" * 64, 409),
])
def test_rebuild_batch_guards(changes, version, sha, code):
    with pytest.raises(HTTPException) as error:
        rebuild.validate_rebuild_batch(batch(**changes), version=version, source_sha256=sha)
    assert error.value.status_code == code


def test_unknown_batch_is_not_found_and_valid_manual_preview_passes():
    with pytest.raises(HTTPException) as error:
        rebuild.validate_rebuild_batch(None, version=3, source_sha256="a" * 64)
    assert error.value.status_code == 404
    rebuild.validate_rebuild_batch(batch(), version=3, source_sha256="a" * 64)


def test_rebuild_request_inherits_the_existing_mapping_validation():
    for changes in ({"version": 0}, {"column_mapping": {"owner_id": "Mine"}},
                    {"filename": "file.xlsx"}):
        with pytest.raises(ValidationError):
            imports.ImportPreviewRebuildRequest(**{
                "filename": "a.csv", "content": "Name\nCard", "version": 1, **changes})


@pytest.mark.asyncio
async def test_replacement_bound_fails_before_database_call(monkeypatch):
    args = dict(connection=object(), actor_id=uuid4(), owner_id=uuid4(), batch_id=uuid4(),
                version=1, source_sha256="a" * 64)
    with pytest.raises(HTTPException) as error:
        await rebuild.replace_preview(**args, preview={"candidates": [{}] * 10001})
    assert error.value.status_code == 422
    monkeypatch.setattr(rebuild, "MAX_REBUILD_BYTES", 8)
    with pytest.raises(HTTPException) as error:
        await rebuild.replace_preview(**args, preview={"candidates": [{"bounded": "payload"}]})
    assert error.value.status_code == 422
