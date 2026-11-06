"""DR97 release watches: four existing provider groups plus Riot gated sentinel.

Pure fake connection objects: no provider, PostgreSQL, or Shopify network I/O.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app import automation_commands as api
from app import legacy_release_watch as legacy

ACTOR = UUID("11111111-1111-4111-8111-111111111111")
GAMES = {
    "POKEMON": ("tcgdex",),
    "ONE_PIECE": ("punk", "one_piece_official"),
    "DRAGON_BALL": ("dragon_ball_masters", "dragon_ball_fusion"),
    "NARUTO": ("naruto_kayou", "naruto_bandai"),
}
ALL_GAMES = tuple(GAMES) + ("RIFTBOUND",)


class Connection:
    def __init__(self, allowed=True, refreshed=True, rows=None):
        self.allowed = allowed
        self.refreshed = refreshed
        self.rows = [] if rows is None else rows
        self.sql = []
    async def fetchval(self, sql, *args):
        self.sql.append(("fetchval", sql, args))
        assert sql == "select pg_try_advisory_lock($1)" and args == (847220092,)
        return self.allowed
    async def execute(self, sql, *args):
        self.sql.append(("execute", sql, args))
        assert sql == "select pg_advisory_unlock($1)" and args == (847220092,)
    async def fetch(self, sql, *args):
        self.sql.append(("fetch", sql, args))
        assert "tcg.reference_sync_runs" in sql
        assert len(args) == 1 and isinstance(args[0], list)
        return self.rows

class Pool:
    def __init__(self, allowed=True):
        self.conn = Connection(allowed=allowed)
        self.entered = 0
    @asynccontextmanager
    async def acquire(self):
        self.entered += 1
        yield self.conn


def fake_db(monkeypatch, *, capacity=True):
    @asynccontextmanager
    async def user_connection(pool, actor, request_id, *, readonly_snapshot):
        assert str(actor) == str(ACTOR)
        assert readonly_snapshot is True
        assert request_id
        yield pool.conn
    async def admin(c):
        assert isinstance(c, Connection)
    async def check(c):
        assert isinstance(c, Connection)
        return SimpleNamespace(refresh_allowed=capacity,
                               reason="WITHIN_SAFE_BULK_REFRESH_CAPACITY" if capacity else
                               "BULK_REFRESH_DEFERRED_CAPACITY")
    monkeypatch.setattr(legacy, "user_connection", user_connection)
    monkeypatch.setattr(legacy, "require_platform_admin", admin)
    monkeypatch.setattr(legacy, "check_database_capacity", check)


@pytest.mark.parametrize("game,sources", GAMES.items())
def test_exact_provider_groups_use_only_existing_reviewed_sources(game, sources):
    assert legacy.LEGACY_GAMES[game] == sources
    assert set(sources).issubset(legacy.SOURCES)


@pytest.mark.asyncio
async def test_riftbound_requires_riot_key_and_never_touches_a_database(monkeypatch):
    pool = Pool()
    monkeypatch.setattr(legacy, "sync_source",
                        AsyncMock(side_effect=AssertionError("Riot API without approval")))
    result = await legacy.check_game(pool, str(ACTOR), "RIFTBOUND")
    assert result["status"] == "AWAITING_RIOT_APP_APPROVAL"
    assert result["artwork_published"] is False
    assert result["source_imports"] == 0 and pool.entered == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("game", GAMES)
async def test_legacy_db_over_400mb_defers_without_provider_network_or_writes(monkeypatch, game):
    pool = Pool()
    fake_db(monkeypatch, capacity=False)
    network = AsyncMock(side_effect=AssertionError("capacity-pause cannot import"))
    monkeypatch.setattr(legacy, "sync_source", network)
    result = await legacy.check_game(pool, str(ACTOR), game)
    assert result["status"] == "DEFERRED_CAPACITY"
    assert result["capacity_reason"] == "BULK_REFRESH_DEFERRED_CAPACITY"
    assert result["artwork_published"] is False
    network.assert_not_awaited()
    assert pool.conn.sql[-1][1] == "select pg_advisory_unlock($1)"


@pytest.mark.asyncio
async def test_legacy_concurrent_maintenance_lock_blocks_duplicate_import(monkeypatch):
    pool = Pool(allowed=False)
    network = AsyncMock(side_effect=AssertionError("never run while daily worker active"))
    monkeypatch.setattr(legacy, "sync_source", network)
    result = await legacy.check_game(pool, str(ACTOR), "ONE_PIECE")
    assert result["status"] == "ALREADY_RUNNING"
    assert result["source_imports"] == 0
    network.assert_not_awaited()
    assert len(pool.conn.sql) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("game,sources", GAMES.items())
async def test_due_sources_use_existing_source_import_and_not_shopify(monkeypatch, game, sources):
    pool = Pool()
    fake_db(monkeypatch)
    monkeypatch.setattr(legacy, "due", lambda *a, **kw: True)
    observed = []
    async def import_source(db, actor, source, settings):
        assert db is pool and actor == ACTOR
        assert settings is None  # no sealed/CardTrader or Shopify import
        observed.append(source)
        return {"status": "COMPLETE", "sets": 1, "records": 5}
    monkeypatch.setattr(legacy, "sync_source", import_source)
    result = await legacy.check_game(pool, str(ACTOR), game)
    assert result["status"] == "COMPLETE"
    assert result["source_imports"] == len(sources)
    assert result["metadata_updated"] is True
    assert result["artwork_published"] is False
    assert tuple(observed) == sources
    assert pool.conn.sql[-1][1] == "select pg_advisory_unlock($1)"


@pytest.mark.asyncio
async def test_not_due_source_is_current_no_network(monkeypatch):
    pool = Pool()
    fake_db(monkeypatch)
    monkeypatch.setattr(legacy, "due", lambda *a, **kw: False)
    worker = AsyncMock(side_effect=AssertionError("already current"))
    monkeypatch.setattr(legacy, "sync_source", worker)
    result = await legacy.check_game(pool, str(ACTOR), "POKEMON")
    assert result["status"] == "CURRENT"
    assert result["sources_checked"] == 0 and result["source_imports"] == 0
    worker.assert_not_awaited()


@pytest.mark.asyncio
async def test_incomplete_provider_never_counts_as_successful_import(monkeypatch):
    pool = Pool()
    fake_db(monkeypatch)
    monkeypatch.setattr(legacy, "due", lambda *a, **kw: True)
    calls = []
    async def sync(*args):
        calls.append(args[2])
        return {"status": "INCOMPLETE"}
    monkeypatch.setattr(legacy, "sync_source", sync)
    result = await legacy.check_game(pool, str(ACTOR), "DRAGON_BALL")
    assert result["status"] == "INCOMPLETE"
    assert calls == ["dragon_ball_masters"]
    assert result["source_imports"] == 0
    assert result["artwork_published"] is False


def cmd(**changes):
    return {
        "schema_version": 1, "action": "CHECK_OR_REFRESH_LEGACY_GAME_RELEASES",
        "game": "NARUTO", "execution_id": "dr97-fixture-001",
        "occurred_at": "2026-11-06T23:00:00+00:00", **changes,
    }


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())))


def sign(monkeypatch, payload):
    async def verify(request, *, timestamp_header, signature_header):
        assert timestamp_header == "1111" and signature_header == "sha256=fixture"
        return json.dumps(payload).encode()
    monkeypatch.setattr(api, "_verified_command_body", verify)


async def invoke():
    return await api.check_legacy_game_releases(
        request(), x_drop_rate_timestamp="1111", x_drop_rate_signature="sha256=fixture",
    )


@pytest.mark.parametrize("invalid", [
    {"game": "YU_GI_OH"}, {"game": "RIFTBOUND_UNAPPROVED_DATA"},
    {"game": "naruto"}, {"action": "SCRAPE_ALL_RIOT_ARTWORK"},
    {"source_url": "https://untrusted.invalid/"}, {"occurred_at": "2026-11-06T23:00:00Z", "game": "RIFTBOUND", "override": True},
    {"schema_version": 2},
])
def test_signed_api_rejects_any_nonlisted_game_or_extra_keys(invalid):
    api.LegacyGameReleaseCommand.model_validate(cmd())
    with pytest.raises(ValidationError):
        api.LegacyGameReleaseCommand.model_validate(cmd(**invalid))


@pytest.mark.asyncio
@pytest.mark.parametrize("result_status", [
    "CURRENT", "COMPLETE", "ALREADY_RUNNING", "DEFERRED_CAPACITY",
    "AWAITING_RIOT_APP_APPROVAL",
])
async def test_signed_endpoint_reports_real_status_and_no_image_permission(monkeypatch, result_status):
    sign(monkeypatch, cmd(game="RIFTBOUND" if result_status == "AWAITING_RIOT_APP_APPROVAL" else "NARUTO"))
    monkeypatch.setattr(api, "get_settings",lambda: SimpleNamespace(catalogue_maintenance_actor_user_id=str(ACTOR)))
    async def check(pool, actor, game):
        return {"game": game, "status": result_status,
                "source_count": 2, "source_imports": 1,
                "capacity_reason": "BULK_REFRESH_DEFERRED_CAPACITY"}
    monkeypatch.setattr(api, "check_legacy_release_game", check)
    value = await invoke()
    assert value["status"] == result_status
    assert value["artwork_published"] is False
    assert value["shopify_updated"] is False
    assert value["ownership_or_price_changed"] is False


def test_five_source_controlled_n8n_workflows_are_inactive_and_signed():
    folder=Path(__file__).resolve().parents[1] / "automation/n8n/workflows"
    files=sorted(folder.glob("dr-97-*-release-watch.json"))
    assert len(files)==5
    found=set()
    for filename in files:
        w=json.loads(filename.read_text(encoding="utf8"))
        assert w["active"] is False
        assert w["settings"]["errorWorkflow"]=="DR90GlobalErrorV1"
        assert w["settings"]["timezone"]=="Europe/London"
        assert len(w["nodes"])==4
        game=w["meta"]["dropRate"]["game"]
        assert game in ALL_GAMES and game not in found
        found.add(game)
        js=[n["parameters"]["jsCode"] for n in w["nodes"] if n["type"]=="n8n-nodes-base.code"]
        assert len(js)==2
        assert f"game:'{game}'" in js[0]
        assert "createHmac('sha256'" in js[0]
        assert "CHECK_OR_REFRESH_LEGACY_GAME_RELEASES" in js[0]
        assert "/commands/catalogue/check-legacy-game-releases" in js[0]
        assert f"r.game!=='{game}'" in js[1]
        assert "r.artwork_published!==false" in js[1]
        assert "r.ownership_or_price_changed!==false" in js[1]
    assert found==set(ALL_GAMES)
