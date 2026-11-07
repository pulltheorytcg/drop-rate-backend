"""Authenticated DR108 real-source pilot is bounded and read-only."""
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import expanded_artwork_coverage as coverage
from app import r2_first_catalogue as catalogue
from test_expanded_artwork_pilot import ygo, ygo_ref

ACTOR = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.asyncio
async def test_pilot_reads_exact_active_r2_snapshot_and_never_writes(monkeypatch):
    ref = ygo_ref(ygo())
    class Snapshot:
        provider = "ygoprodeck"
        manifest_digest = "e" * 64
        def search(self, *, limit, offset, sort, include_upcoming):
            assert (limit, offset, sort, include_upcoming) == (5, 0, "name", False)
            return {"items": [dict(ref)]}

    @contextmanager
    def borrow(snapshots):
        assert len(snapshots) == 1
        yield

    class Connection:
        async def execute(self, *args):
            raise AssertionError("Read-only pilot attempted to modify SQL")

    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert user_id == ACTOR and request_id == "dr108-live"
        yield Connection()

    async def read(conn, *, system_code, language):
        assert system_code == "YUGIOH" and language == "English"
        return [Snapshot()]

    async def collect(system_code, references, *, verify_bytes):
        assert system_code == "YUGIOH" and verify_bytes is True
        assert references[0]["key"] == ref["key"]
        assert references[0]["source_manifest_sha256"] == "e" * 64
        return {
            "system_code": system_code, "requested": len(references),
            "candidate_count": 1, "byte_verified_count": 0,
            "records": [], "can_publish": False, "can_mirror": False,
            "storage_writes": 0, "database_writes": 0,
        }

    monkeypatch.setattr(coverage, "user_connection", connection)
    monkeypatch.setattr(coverage.r2_first_service, "read", read)
    monkeypatch.setattr(coverage.r2_first_service, "_borrow", borrow)
    monkeypatch.setattr(coverage.expanded_artwork_live_pilot, "collect", collect)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="dr108-live"),
    )
    result = await coverage.live_artwork_pilot(
        "YUGIOH", request, SimpleNamespace(user_id=ACTOR),
        limit=5, offset=0, verify_bytes=True,
    )
    assert result["schema"] == "drop-rate-live-artwork-pilot-v1"
    assert result["source_manifest_sha256"] == "e" * 64
    assert result["can_publish"] is False and result["can_mirror"] is False
    assert result["storage_writes"] == 0 and result["database_writes"] == 0


@pytest.mark.asyncio
async def test_unknown_source_or_out_of_bounds_pilot_fails_before_network():
    for code, size, offset, expected in (
        ("OTHER", 5, 0, 404),
        ("YUGIOH", 5, 25, 422),
        ("DISNEY_LORCANA", 5, 21, 422),
        ("MAGIC_THE_GATHERING", 5, 22, 422),
    ):
        with pytest.raises(HTTPException) as exc:
            await coverage.live_artwork_pilot(
                code, None, None, limit=size, offset=offset,
                verify_bytes=False,
            )
        assert exc.value.status_code == expected


def test_live_pilot_is_platform_admin_only_and_founder_ui_never_publishes():
    main = (Path(__file__).resolve().parents[1] /
            "backend/app/main.py").read_text(encoding="utf-8")
    assert "app.include_router(expanded_artwork_coverage_router, dependencies=[Depends(require_platform_admin_request)])" in main
    source = (Path(__file__).resolve().parents[1] /
              "backend/app/static/founder-dashboard.js").read_text(encoding="utf-8")
    assert "/api/v1/artwork/pilot/" in source
    assert "verify_bytes=true" in source
    assert "Not approved for storefront publishing" in source
    assert "artOffset<20" in source
    assert "hub-session-cleared" in source
    assert "/api/v1/artwork/approve" not in source
    assert "/api/v1/artwork/publish" not in source
