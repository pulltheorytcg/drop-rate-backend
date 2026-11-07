from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.owner_import_recovery import enabled, rebuild_owner_preview
from app.imports import ImportPreviewRebuildRequest
from app.settings import Settings


def test_owner_recovery_is_independent_and_defaults_off(monkeypatch):
    for key,value in {'TCG_DATABASE_URL':'postgresql://unused','TCG_AUTH_ISSUER':'https://example.test/auth/v1','TCG_AUTH_AUDIENCE':'authenticated','TCG_SUPABASE_PUBLISHABLE_KEY':'sb_publishable_test','TCG_IMPORT_PREVIEW_REBUILD_ENABLED':'true'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.delenv('TCG_OWNER_IMPORT_PREVIEW_REBUILD_ENABLED',raising=False)
    assert Settings.from_env().owner_import_preview_rebuild_enabled is False
    monkeypatch.setenv('TCG_OWNER_IMPORT_PREVIEW_REBUILD_ENABLED','true')
    assert Settings.from_env().owner_import_preview_rebuild_enabled is True


@pytest.mark.asyncio
async def test_disabled_recovery_does_not_touch_database():
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert not enabled(request)
    payload=ImportPreviewRebuildRequest(filename='original.csv',content='Name\nSynthetic',version=1)
    with pytest.raises(HTTPException) as error:
        await rebuild_owner_preview(uuid4(),payload,request,SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code==404
