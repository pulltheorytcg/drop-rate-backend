"""DR-95: unattended catalogue artwork has signed entry, bounded policy and receipts.

No provider calls, Shopify changes, R2 writes or real DB access in these tests.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import automation_commands as api


def payload(**update):
    return {
        "schema_version": 1, "action": "REFRESH_ELIGIBLE_ARTWORK",
        "execution_id": "dr95-fixture-001",
        "occurred_at": "2026-11-06T22:00:00+00:00",
        "canonical_limit": 3, "reference_limit": 10, **update,
    }


class Pool:
    def __init__(self, database_bytes=375_000_000, read_only="off"):
        self.database_bytes, self.read_only = database_bytes, read_only
        self.capacity_checks = 0

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchrow(self, query):
        from app.database_capacity import CAPACITY_SQL
        assert query == CAPACITY_SQL
        self.capacity_checks += 1
        return {"database_bytes": self.database_bytes, "default_read_only": self.read_only}


def request(pool):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),
        state=SimpleNamespace(request_id="dr95-signed-request-fixture"),
    )


def patch_signed(monkeypatch, command):
    async def verified(request, *, timestamp_header, signature_header):
        assert timestamp_header == "1111"
        assert signature_header == "sha256=fixture"
        return json.dumps(command).encode()
    monkeypatch.setattr(api, "_verified_command_body", verified)


async def execute(req):
    return await api.refresh_eligible_artwork(req,
        x_drop_rate_timestamp="1111", x_drop_rate_signature="sha256=fixture")


def mirror(examined=2, mirrored=1, failed=0, remaining_possible=False):
    return {"examined": examined, "mirrored": mirrored, "skipped": examined-mirrored-failed,
            "failed": failed, "remaining_possible": remaining_possible}


def test_command_rejects_unrecognised_sources_and_abusive_batches():
    api.RefreshEligibleArtworkCommand.model_validate(payload())
    for update in (
        {"canonical_limit": 10000}, {"reference_limit": 10000},
        {"action": "MIRROR_ALL_PROVIDER_IMAGES"}, {"arbitrary_image_url": "https://evil.test/1"},
        {"canonical_limit": 0}, {"reference_limit": 0},
    ):
        with pytest.raises(ValidationError):
            api.RefreshEligibleArtworkCommand.model_validate(payload(**update))


@pytest.mark.asyncio
async def test_approved_canonical_media_mirrors_unattended_but_reference_flag_is_respected(monkeypatch):
    pool = Pool()
    patch_signed(monkeypatch, payload())
    calls = []
    async def canonical(db_pool, *, limit, request_id):
        assert db_pool is pool and limit == 3 and request_id == "dr95-signed-request-fixture"
        calls.append("canonical")
        return mirror()
    async def reference(*args, **kwargs):
        pytest.fail("Unapproved reference cache cannot run")
    monkeypatch.setattr(api, "mirror_approved_media", canonical)
    monkeypatch.setattr(api, "mirror_reference_images", reference)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(r2_reference_cache_apply_enabled=False))
    monkeypatch.setattr(api, "worker_enabled", lambda: False)
    result = await execute(request(pool))
    assert calls == ["canonical"] and pool.capacity_checks == 1
    assert result == {
        "accepted": True, "execution_id": payload()["execution_id"], "status": "COMPLETED",
        "scope": "RIGHTS_APPROVED_CANONICAL_AND_LEGACY_REFERENCE_ONLY",
        "canonical": mirror(), "canonical_status": "MIRRORED_APPROVED_MEDIA", "reference": None,
        "reference_status": "DISABLED_BY_BACKEND_POLICY", "new_game_metadata_promoted": False,
    }


@pytest.mark.asyncio
async def test_eligible_reference_bytes_are_cached_without_becoming_approved_media(monkeypatch):
    pool = Pool()
    patch_signed(monkeypatch, payload(canonical_limit=5, reference_limit=20))
    calls = []
    async def canonical(db_pool, *, limit, request_id):
        calls.append(("canonical", limit))
        return mirror(examined=5, mirrored=5)
    async def reference(db_pool, *, limit, request_id):
        calls.append(("reference", limit))
        return mirror(examined=20, mirrored=19, failed=0, remaining_possible=True)
    monkeypatch.setattr(api, "mirror_approved_media", canonical)
    monkeypatch.setattr(api, "mirror_reference_images", reference)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(r2_reference_cache_apply_enabled=True))
    monkeypatch.setattr(api, "worker_enabled", lambda: False)
    result = await execute(request(pool))
    assert calls == [("canonical", 5), ("reference", 20)]
    assert result["status"] == "COMPLETED"
    assert result["canonical"]["mirrored"] == 5 and result["reference"]["mirrored"] == 19
    assert result["reference_status"] == "REFERENCE_ONLY_CACHE_VERIFIED"
    assert result["new_game_metadata_promoted"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("database_bytes,read_only,reason", [
    (400_000_000, "off", "BULK_REFRESH_DEFERRED_CAPACITY"),
    (451_000_000, "off", "FREE_DATABASE_CAPACITY_URGENT"),
    (300_000_000, "on", "DATABASE_READ_ONLY"),
])
async def test_capacity_fails_closed_without_touching_provider_or_media(monkeypatch, database_bytes, read_only, reason):
    pool = Pool(database_bytes, read_only)
    patch_signed(monkeypatch, payload())
    async def bad(*args, **kwargs):
        pytest.fail("No image fetching, DB mutations or R2 writes permitted")
    monkeypatch.setattr(api, "mirror_approved_media", bad)
    monkeypatch.setattr(api, "mirror_reference_images", bad)
    result = await execute(request(pool))
    assert pool.capacity_checks == 1
    assert result["status"] == "DEFERRED_CAPACITY"
    assert result["capacity_reason"] == reason
    assert result["canonical"] is None and result["reference"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["canonical", "reference"])
async def test_any_verification_failure_is_retryable_and_not_a_success_receipt(monkeypatch, failure_stage):
    patch_signed(monkeypatch, payload())
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(r2_reference_cache_apply_enabled=True))
    async def canonical(*args, **kwargs):
        return mirror(examined=2, mirrored=1, failed=1) if failure_stage == "canonical" else mirror()
    async def reference(*args, **kwargs):
        if failure_stage == "canonical":
            pytest.fail("Failure stops the next mirror step")
        return mirror(examined=2, mirrored=1, failed=1)
    monkeypatch.setattr(api, "mirror_approved_media", canonical)
    monkeypatch.setattr(api, "mirror_reference_images", reference)
    with pytest.raises(HTTPException) as exc:
        await execute(request(Pool()))
    assert exc.value.status_code == 502
    assert exc.value.detail["retryable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("update", [
    {"occurred_at": "2026-11-06T22:00:00"},
    {"canonical_limit": 100}, {"reference_limit": -1},
    {"action": "UNREVIEWED_IMAGE_PUBLISH"}, {"source_url": "https://evil.test/copy"},
])
async def test_rejected_command_never_invokes_any_worker(monkeypatch, update):
    patch_signed(monkeypatch, payload(**update))
    async def bad(*args, **kwargs):
        pytest.fail("No provider or R2 work for invalid commands")
    monkeypatch.setattr(api, "mirror_approved_media", bad)
    with pytest.raises(HTTPException) as exc:
        await execute(request(Pool()))
    assert exc.value.status_code == 422


def test_dr95_n8n_workflow_is_signed_inactive_and_rejects_false_receipts():
    path = Path(__file__).resolve().parents[1] / "automation/n8n/workflows/dr-95-eligible-artwork-sync.json"
    workflow = json.loads(path.read_text(encoding="utf8"))
    assert workflow["id"] == "DR95EligibleArtworkSyncV1"
    assert workflow["active"] is False
    assert workflow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert len(nodes) == 4
    sign = nodes["Sign Artwork Refresh Command"]["parameters"]["jsCode"]
    assert "createHmac('sha256'" in sign and "DROP_RATE_AUTOMATION_COMMAND_SECRET" in sign
    assert "REFRESH_ELIGIBLE_ARTWORK" in sign
    assert "/commands/storage/refresh-eligible-artwork" in sign
    assert "canonical_limit:0,reference_limit:10" in sign
    http = nodes["Call Governed Artwork Refresh"]["parameters"]
    assert http["method"] == "POST" and http["contentType"] == "raw"
    assert http["options"]["response"]["response"]["fullResponse"] is True
    assert http["options"]["response"]["response"]["neverError"] is True
    verify = nodes["Verify Deterministic Artwork Receipt"]["parameters"]["jsCode"]
    assert "artwork_refresh_http_" in verify and "artwork_refresh_not_completed" in verify
    assert "unexpected_artwork_publication_scope" in verify
    assert "APPROVED" not in workflow["name"].upper() or workflow["active"] is False
    assert "shopify" not in json.dumps(workflow).lower()


@pytest.mark.asyncio
async def test_live_existing_workers_are_delegated_without_duplicate_provider_requests(monkeypatch):
    pool = Pool()
    patch_signed(monkeypatch, payload(canonical_limit=0, reference_limit=10))
    monkeypatch.setattr(api, "worker_enabled", lambda: True)
    async def no_network(*args, **kwargs):
        pytest.fail("Existing DR94 / reference worker own these image queues")
    monkeypatch.setattr(api, "mirror_approved_media", no_network)
    monkeypatch.setattr(api, "mirror_reference_images", no_network)
    result = await execute(request(pool))
    assert result["status"] == "COMPLETED"
    assert result["canonical_status"] == "DELEGATED_TO_DR94"
    assert result["canonical"]["mirrored"] == 0
    assert result["reference_status"] == "DELEGATED_TO_REFERENCE_WORKER"
    assert result["reference"] is None
    assert result["new_game_metadata_promoted"] is False
