"""DR-97: older game release checks reuse deterministic maintenance, never scrape independently."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app import legacy_release_scout as legacy
from app import automation_commands as api


SOURCES = (
    "tcgdex", "one_piece_official", "punk",
    "dragon_ball_masters", "dragon_ball_fusion",
    "naruto_kayou", "naruto_bandai", "riftbound_riot",
)
ACTOR = "11111111-1111-4111-8111-111111111111"


def message(**values):
    return {
        "schema_version":1, "action":"CHECK_LEGACY_RELEASE_SOURCE",
        "source":"tcgdex", "execution_id":"dr97-t1",
        "occurred_at":"2026-11-06T23:08:00+00:00", **values,
    }


@pytest.mark.parametrize("changes", [
    {"source":"a_random_game"}, {"source":"riftcodex"}, {"source":"pokemon_images"},
    {"url":"https://attacker.invalid/illegal.png"}, {"schema_version":2},
    {"action":"PUBLISH_ALL_ARTWORK"}, {"execution_id":""},
])
def test_strict_legacy_command_rejects_unapproved_provider_or_url(changes):
    api.LegacyReleaseScoutCommand.model_validate(message())
    with pytest.raises(ValidationError):
        api.LegacyReleaseScoutCommand.model_validate(message(**changes))


class Connection:
    def __init__(self, previous=None):
        self.previous=previous
        self.calls=0
    async def fetchrow(self, query, source):
        assert "tcg.reference_sync_runs" in query
        assert source in SOURCES
        self.calls+=1
        return self.previous


class Pool:
    def __init__(self, lock_held=False, previous=None):
        self.lock_held=lock_held
        self.connection=Connection(previous)
        self.lock_calls=[]
    @asynccontextmanager
    async def acquire(self):
        yield self
    async def fetchval(self, sql, key):
        assert sql=="select pg_try_advisory_lock($1)" and key==legacy.LOCK
        self.lock_calls.append("acquire")
        return not self.lock_held
    async def execute(self, sql, key):
        assert sql=="select pg_advisory_unlock($1)" and key==legacy.LOCK
        self.lock_calls.append("release")


def configure(monkeypatch, *, capacity=True):
    @asynccontextmanager
    async def user_connection(pool, actor, request_id):
        assert str(actor)==ACTOR
        assert request_id
        yield pool.connection
    async def check(conn):
        return SimpleNamespace(
            refresh_allowed=capacity,
            reason="BULK_REFRESH_DEFERRED_CAPACITY",
        )
    async def admin(conn):
        assert isinstance(conn,Connection)
    monkeypatch.setattr(legacy, "user_connection", user_connection)
    monkeypatch.setattr(legacy, "require_platform_admin", admin)
    monkeypatch.setattr(legacy, "check_database_capacity", check)
    return SimpleNamespace(catalogue_daily_refresh_enabled=True,
                           catalogue_maintenance_actor_user_id=ACTOR)


@pytest.mark.asyncio
async def test_legacy_source_is_stopped_before_any_download_on_capacity_defer(monkeypatch):
    settings=configure(monkeypatch,capacity=False)
    import_mock=AsyncMock(side_effect=AssertionError("must not fetch or write"))
    monkeypatch.setattr(legacy.maintenance,"sync_source",import_mock)
    pool=Pool()
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"tcgdex",settings)
    assert result["status"]=="DEFERRED_CAPACITY"
    assert result["reason"]=="BULK_REFRESH_DEFERRED_CAPACITY"
    assert pool.lock_calls==["acquire","release"]
    assert pool.connection.calls==0
    import_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_lock_deduplicates_daily_and_n8n_source_imports(monkeypatch):
    settings=configure(monkeypatch)
    import_mock=AsyncMock(side_effect=AssertionError("already running"))
    monkeypatch.setattr(legacy.maintenance,"sync_source",import_mock)
    pool=Pool(lock_held=True)
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"one_piece_official",settings)
    assert result["status"]=="ALREADY_RUNNING"
    assert pool.lock_calls==["acquire"]
    assert pool.connection.calls==0
    import_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_source_is_not_refetched_by_extra_daily_n8n_schedule(monkeypatch):
    now=datetime.now(timezone.utc)
    previous={"started_at":now,"status":"COMPLETE","report":{"importer_revision":1}}
    settings=configure(monkeypatch)
    mock=AsyncMock(side_effect=AssertionError("not due"))
    monkeypatch.setattr(legacy.maintenance,"sync_source",mock)
    pool=Pool(previous=previous)
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"tcgdex",settings)
    assert result["status"]=="CURRENT"
    assert pool.connection.calls==1
    assert pool.lock_calls==["acquire","release"]
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_due_legacy_source_runs_only_one_existing_adapter_and_reports_new_sets(monkeypatch):
    settings=configure(monkeypatch)
    mock=AsyncMock(return_value={"status":"COMPLETE","sets":4,"records":40,"new_sets":1,
        "new_set_samples":[{"system_code":"NARUTO","language":"Japanese",
                            "set_id":"NRT-2","name":"New set","release_date":"2026-11-06"}]})
    monkeypatch.setattr(legacy.maintenance,"sync_source",mock)
    pool=Pool()
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"naruto_kayou",settings)
    assert result["status"]=="VERIFIED_SOURCE_REFRESH"
    assert result["new_sets"]==1
    assert result["new_set_samples"][0]["set_id"]=="NRT-2"
    assert result["sets_checked"]==4
    assert result["records_checked"]==40
    assert len(mock.await_args_list)==1
    assert mock.await_args.args[2]=="naruto_kayou"
    assert pool.lock_calls==["acquire","release"]


@pytest.mark.asyncio
async def test_failed_provider_never_becomes_success(monkeypatch):
    settings=configure(monkeypatch)
    mock=AsyncMock(return_value={"status":"INCOMPLETE","sets":3,"records":0,"new_sets":0})
    monkeypatch.setattr(legacy.maintenance,"sync_source",mock)
    result=await legacy.run_legacy_release_scout(Pool(),ACTOR,"dragon_ball_fusion",settings)
    assert result["status"]=="SOURCE_INCOMPLETE"
    assert result["reason"]=="UPSTREAM_OR_SOURCE_VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_riftbound_requires_official_access_and_makes_no_sql_or_provider_call(monkeypatch):
    settings=configure(monkeypatch)
    mock=AsyncMock(side_effect=AssertionError("Riot key not approved"))
    monkeypatch.setattr(legacy.maintenance,"sync_source",mock)
    pool=Pool()
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"riftbound_riot",settings)
    assert result=={"status":"DEFERRED_RIOT_APPROVAL","source":"riftbound_riot",
                    "game":"RIFTBOUND","reason":"OFFICIAL_APP_KEY_OR_LICENSE_REQUIRED",
                    "source_policy":"https://developer.riotgames.com/docs/riftbound","new_sets":0}
    assert pool.lock_calls==[]
    assert pool.connection.calls==0
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_legacy_policy_never_fetches_and_never_locks(monkeypatch):
    settings=configure(monkeypatch)
    settings.catalogue_daily_refresh_enabled=False
    mock=AsyncMock(side_effect=AssertionError("disabled"))
    monkeypatch.setattr(legacy.maintenance,"sync_source",mock)
    pool=Pool()
    result=await legacy.run_legacy_release_scout(pool,ACTOR,"naruto_bandai",settings)
    assert result["status"]=="DISABLED_BY_POLICY"
    assert pool.lock_calls==[]
    mock.assert_not_awaited()


def sign(monkeypatch, command):
    async def verifier(*args, **kwargs):
        return json.dumps(command).encode()
    monkeypatch.setattr(api,"_verified_command_body",verifier)


@pytest.mark.asyncio
async def test_api_never_claims_artwork_or_shopify_publication(monkeypatch):
    sign(monkeypatch,message(source="dragon_ball_masters"))
    monkeypatch.setattr(api,"get_settings",
                        lambda:SimpleNamespace(catalogue_maintenance_actor_user_id=ACTOR))
    mock=AsyncMock(return_value={"status":"VERIFIED_SOURCE_REFRESH",
        "source":"dragon_ball_masters","game":"DRAGON_BALL",
        "new_sets":1,"sets_checked":2,"records_checked":35})
    monkeypatch.setattr(api,"run_legacy_release_scout",mock)
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=Pool())))
    result=await api.check_legacy_release_source(req)
    assert result["accepted"] is True and result["status"]=="VERIFIED_SOURCE_REFRESH"
    assert result["metadata_only"] is True
    assert result["artwork_published"] is False
    assert result["ownership_or_price_changed"] is False
    assert result["shopify_updated"] is False
    assert result["new_sets"]==1
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_rejects_untrusted_command_and_incomplete_import(monkeypatch):
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=Pool())))
    monkeypatch.setattr(api,"get_settings",
                        lambda:SimpleNamespace(catalogue_maintenance_actor_user_id=ACTOR))
    sign(monkeypatch,message(source="illegal_source"))
    monkeypatch.setattr(api,"run_legacy_release_scout",
                        AsyncMock(side_effect=AssertionError("not permitted")))
    with pytest.raises(HTTPException) as invalid:
        await api.check_legacy_release_source(req)
    assert invalid.value.status_code==422
    sign(monkeypatch,message(source="tcgdex"))
    monkeypatch.setattr(api,"run_legacy_release_scout",
                        AsyncMock(return_value={"status":"SOURCE_INCOMPLETE","game":"POKEMON_TCG"}))
    with pytest.raises(HTTPException) as failed:
        await api.check_legacy_release_source(req)
    assert failed.value.status_code==502


def test_eight_source_workflows_are_inactive_signed_scoped_and_non_publishers():
    root=Path(__file__).resolve().parents[1]/"automation/n8n/workflows"
    paths=list(root.glob("dr-97-*-source-scout.json"))
    assert len(paths)==8
    seen=set()
    for path in paths:
        flow=json.loads(path.read_text("utf8"))
        assert flow["active"] is False
        assert flow["settings"]["errorWorkflow"]=="DR90GlobalErrorV1"
        assert flow["settings"]["timezone"]=="Europe/London"
        assert len(flow["nodes"])==4
        source=flow["meta"]["dropRate"]["source"]
        assert source in SOURCES and source not in seen
        seen.add(source)
        code=[n["parameters"]["jsCode"] for n in flow["nodes"]
              if n["type"]=="n8n-nodes-base.code"]
        assert len(code)==2
        assert f"source:'{source}'" in code[0]
        assert "CHECK_LEGACY_RELEASE_SOURCE" in code[0]
        assert "createHmac('sha256'" in code[0]
        assert "/commands/catalogue/check-legacy-release-source" in code[0]
        assert "r.artwork_published!==false" in code[1]
        assert "r.ownership_or_price_changed!==false" in code[1]
    assert seen==set(SOURCES)
