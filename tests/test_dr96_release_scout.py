"""Per-source unattended release scouts: deterministic, HMAC routed and scoped.

Never call real providers, Supabase, n8n, Shopify or Cloudflare in tests.
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
from app import r2_first_import as source

ACTOR = UUID("11111111-1111-4111-8111-111111111111")
SOURCES = (
    "ygoprodeck", "lorcast", "mtgjson", "cardcollectorcapital",
    "cardcollectorcapital_heritage", "reviewed_figures",
)


@pytest.fixture(autouse=True)
def isolate_provider_prewarm_from_railway_prod_environment(monkeypatch):
    # Railway sets real R2 flags even while its pre-deploy pytest suite runs.
    # Unit test workers must never prewarm real R2, PostgreSQL or credentials.
    monkeypatch.setattr(source.service, "enabled", lambda: False)


def payload(**changes):
    return {"schema_version": 1, "action": "REFRESH_APPROVED_RELEASE_SOURCE",
            "source": "lorcast", "execution_id": "releases-test-001",
            "occurred_at": "2026-11-06T23:00:00+00:00", **changes}


def signed(monkeypatch, command):
    async def verified(request, *, timestamp_header, signature_header):
        assert timestamp_header == "999"
        assert signature_header == "sha256=test"
        return json.dumps(command).encode("utf8")
    monkeypatch.setattr(api, "_verified_command_body", verified)


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())))


async def call(req):
    return await api.refresh_catalogue_release_source(
        req, x_drop_rate_timestamp="999", x_drop_rate_signature="sha256=test",
    )


@pytest.mark.parametrize("invalid", [
    {"action": "PUBLISH_UNVERIFIED_IMAGES"},
    {"source": "riftcodex"}, {"source": "scryfall"},
    {"source": "pokemon_unverified"}, {"provider_url": "https://attacker.invalid/metadata"},
    {"schema_version": 2}, {"execution_id": ""},
])
def test_only_approved_metadata_sources_and_bounded_signed_payloads(invalid):
    api.ReleaseScoutCommand.model_validate(payload())
    with pytest.raises(ValidationError):
        api.ReleaseScoutCommand.model_validate(payload(**invalid))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["CURRENT", "PUBLISHED", "ALREADY_RUNNING"])
async def test_authenticated_scoped_release_metadata_never_claims_artwork_or_prices(monkeypatch, status):
    signed(monkeypatch, payload())
    monkeypatch.setattr(api, "get_settings",
                        lambda: SimpleNamespace(catalogue_maintenance_actor_user_id=str(ACTOR)))
    called = []
    async def worker(pool, actor, target):
        called.append((pool, actor, target))
        return {"status": status, "source": target, "record_count": 3505,
                "generation": 3}
    monkeypatch.setattr(api, "run_selected", worker)
    req = request()
    result = await call(req)
    assert called == [(req.app.state.db_pool, str(ACTOR), "lorcast")]
    assert result["accepted"] is True
    assert result["status"] == status
    assert result["metadata_only"] is True
    assert result["artwork_published"] is False
    assert result["shopify_updated"] is False
    assert result["ownership_or_price_changed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"source_url": "https://attacker.invalid/metadata"},
    {"occurred_at": "2026-11-06T23:00:00"},
    {"source": "scryfall"}, {"action": "REFRESH_ANY_SOURCE"},
])
async def test_bad_commands_are_rejected_before_provider_request(monkeypatch, invalid):
    signed(monkeypatch, payload(**invalid))
    monkeypatch.setattr(api, "get_settings",
                        lambda: SimpleNamespace(catalogue_maintenance_actor_user_id=str(ACTOR)))
    monkeypatch.setattr(api, "run_selected", AsyncMock(side_effect=AssertionError("must not run")))
    with pytest.raises(HTTPException) as exc:
        await call(request())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_missing_service_identity_fails_before_any_provider_work(monkeypatch):
    signed(monkeypatch, payload())
    monkeypatch.setattr(api, "get_settings",
                        lambda: SimpleNamespace(catalogue_maintenance_actor_user_id=None))
    monkeypatch.setattr(api, "run_selected", AsyncMock(side_effect=AssertionError("must not run")))
    with pytest.raises(HTTPException) as error:
        await call(request())
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_upstream_error_is_sanitised_and_remains_retryable(monkeypatch):
    signed(monkeypatch, payload())
    monkeypatch.setattr(api, "get_settings",
                        lambda: SimpleNamespace(catalogue_maintenance_actor_user_id=str(ACTOR)))
    async def failed(*a):
        raise RuntimeError("sensitive provider credentials and URL")
    monkeypatch.setattr(api, "run_selected", failed)
    with pytest.raises(HTTPException) as error:
        await call(request())
    assert error.value.status_code == 502
    assert error.value.detail["retryable"] is True
    assert "sensitive" not in json.dumps(error.value.detail)


class FakeConnection:
    def __init__(self, allowed):
        self.allowed = allowed
        self.queries = []
    async def fetchval(self, sql):
        self.queries.append(sql)
        assert sql == "select pg_try_advisory_lock(847220121)"
        return self.allowed
    async def execute(self, sql):
        self.queries.append(sql)
        assert sql == "select pg_advisory_unlock(847220121)"


class Pool:
    def __init__(self, allowed=True):
        self.lock = FakeConnection(allowed)
        self.entered = 0
    @asynccontextmanager
    async def acquire(self):
        self.entered += 1
        yield self.lock


@pytest.mark.asyncio
async def test_targeted_release_import_reuses_background_global_lock(monkeypatch):
    monkeypatch.setattr(source, "configured_sources", lambda: SOURCES)
    calls = []
    async def importer(pool, actor, requested):
        calls.append((pool, actor, requested))
        return {"status": "PUBLISHED", "source": requested, "generation": 2,
                "record_count": 10, "metadata_only": True}
    monkeypatch.setattr(source, "import_source", importer)
    pool = Pool()
    result = await source.run_selected(pool, ACTOR, "ygoprodeck")
    assert result["status"] == "PUBLISHED"
    assert calls == [(pool, ACTOR, "ygoprodeck")]
    assert pool.lock.queries == [
        "select pg_try_advisory_lock(847220121)",
        "select pg_advisory_unlock(847220121)",
    ]


@pytest.mark.asyncio
async def test_real_published_generation_prewarms_app_reference_index(monkeypatch):
    monkeypatch.setattr(source, "configured_sources", lambda: SOURCES)
    async def importer(pool, actor, requested):
        assert requested == "mtgjson"
        return {"status": "PUBLISHED", "source": requested, "generation": 2}
    warmed = []
    async def warm(pool, actor):
        warmed.append((pool, actor))
    monkeypatch.setattr(source, "import_source", importer)
    monkeypatch.setattr(source.service, "enabled", lambda: True)
    monkeypatch.setattr(source.service, "prewarm", warm)
    pool = Pool()
    result = await source.run_selected(pool, ACTOR, "mtgjson")
    assert result["status"] == "PUBLISHED"
    assert warmed == [(pool, ACTOR)]
    assert pool.lock.queries[-1] == "select pg_advisory_unlock(847220121)"


@pytest.mark.asyncio
async def test_overlap_does_not_download_or_mutate_any_catalogue(monkeypatch):
    monkeypatch.setattr(source, "configured_sources", lambda: SOURCES)
    monkeypatch.setattr(source, "import_source",
                        AsyncMock(side_effect=AssertionError("lock must block work")))
    pool = Pool(False)
    assert await source.run_selected(pool, ACTOR, "lorcast") == {
        "status": "ALREADY_RUNNING", "source": "lorcast", "metadata_only": True,
    }
    assert pool.lock.queries == ["select pg_try_advisory_lock(847220121)"]


@pytest.mark.asyncio
async def test_rejected_or_unconfigured_source_does_not_obtain_sql_session(monkeypatch):
    monkeypatch.setattr(source, "configured_sources", lambda: ("lorcast",))
    pool = Pool()
    assert (await source.run_selected(pool, ACTOR, "mtgjson"))["status"] == "DISABLED"
    assert (await source.run_selected(pool, ACTOR, "riftcodex"))["status"] == "DISABLED"
    assert pool.entered == 0


@pytest.mark.asyncio
async def test_targeted_import_releases_lock_on_provider_error(monkeypatch):
    monkeypatch.setattr(source, "configured_sources", lambda: SOURCES)
    async def importer(*args):
        raise RuntimeError("provider offline")
    monkeypatch.setattr(source, "import_source", importer)
    pool = Pool()
    with pytest.raises(RuntimeError):
        await source.run_selected(pool, ACTOR, "lorcast")
    assert pool.lock.queries[-1] == "select pg_advisory_unlock(847220121)"


def test_n8n_releases_per_source_keep_backend_authoritative_and_inactive():
    root = Path(__file__).resolve().parents[1] / "automation/n8n/workflows"
    match = list(root.glob("dr-96-*-release-scout.json"))
    assert len(match) == 6
    ids = set()
    seen = set()
    for path in match:
        flow = json.loads(path.read_text(encoding="utf8"))
        assert flow["id"] not in ids
        ids.add(flow["id"])
        assert flow["active"] is False
        assert flow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"
        assert flow["settings"]["timezone"] == "Europe/London"
        assert len(flow["nodes"]) == 4
        kinds = {node["type"]: node for node in flow["nodes"]}
        assert "n8n-nodes-base.scheduleTrigger" in kinds
        assert "n8n-nodes-base.httpRequest" in kinds
        source_nodes = [n for n in flow["nodes"]
                        if n["type"] == "n8n-nodes-base.code"]
        assert len(source_nodes) == 2
        signer = source_nodes[0]["parameters"]["jsCode"]
        verifier = source_nodes[1]["parameters"]["jsCode"]
        name = flow["meta"]["dropRate"]["source"]
        assert name in SOURCES and name not in seen
        seen.add(name)
        assert "REFRESH_APPROVED_RELEASE_SOURCE" in signer
        assert f"source:'{name}'" in signer
        assert "createHmac('sha256'" in signer
        assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
        assert "/commands/catalogue/refresh-release-source" in signer
        assert f"r.source!=='{name}'" in verifier
        assert "r.artwork_published!==false" in verifier
        assert "release_source_unavailable_" in verifier
        http = kinds["n8n-nodes-base.httpRequest"]["parameters"]
        assert http["method"] == "POST"
        assert http["contentType"] == "raw"
        assert http["options"]["response"]["response"]["fullResponse"] is True
        assert "shopify" not in path.name.lower() 
    assert seen == set(SOURCES)
