"""DR107: coverage is bound to ACTIVE R2 generations and approved media only."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import expanded_artwork_coverage as coverage

ACTOR = UUID("11111111-1111-4111-8111-111111111111")


def row(code, provider, stored, released, linked=0, approved=0):
    return {
        "provider": provider, "system_code": code, "language": "English",
        "record_count": stored, "released_record_count": released,
        "materialized_links": linked, "approved_canonical_images": approved,
        "manifest_sha256": "a" * 64,
        "published_at": datetime(2026, 11, 7, tzinfo=timezone.utc),
    }


LIVE_LIKE = [
    row("DISNEY_LORCANA", "lorcast", 3505, 3505),
    row("MAGIC_THE_GATHERING", "mtgjson", 153662, 151613),
    row("YUGIOH", "ygoprodeck", 45418, 45418),
]


def test_three_game_live_like_metadata_is_not_misreported_as_artwork():
    result = coverage.summarize(LIVE_LIKE)
    assert result["totals"] == {
        "released_records": 200536, "approved_listing_artwork_records": 0,
        "artwork_missing_records": 200536, "artwork_coverage_percent": 0.0,
    }
    assert result["games"]["MAGIC_THE_GATHERING"]["stored_records"] == 153662
    assert result["games"]["MAGIC_THE_GATHERING"]["unlinked_records"] == 151613
    assert result["games"]["DISNEY_LORCANA"]["artwork_coverage_percent"] == 0.0
    assert result["image_candidates_are_not_approved"] is True
    assert result["reads_only"] is True


def test_coverage_counts_only_exact_current_link_and_media_ready():
    rows = [row("YUGIOH", "ygoprodeck", 100, 100, linked=20, approved=14)]
    result = coverage.summarize(rows)
    ygo = result["games"]["YUGIOH"]
    assert ygo["artwork_coverage_percent"] == 14.0
    assert ygo["artwork_missing_records"] == 86
    assert ygo["unlinked_records"] == 80
    assert ygo["linked_without_approved_artwork"] == 6
    assert result["games"]["DISNEY_LORCANA"]["status"] == "MISSING_PUBLISHED_CATALOGUE"


@pytest.mark.parametrize("change", [
    {"materialized_links": -1},
    {"materialized_links": 105},
    {"approved_canonical_images": 21},
    {"record_count": 9},
])
def test_inconsistent_source_media_counts_fail_closed(change):
    sample = row("YUGIOH", "ygoprodeck", 100, 100, linked=20, approved=14)
    sample.update(change)
    with pytest.raises(ValueError, match="Inconsistent"):
        coverage.summarize([sample])


def test_duplicate_provider_or_unknown_game_rejected():
    with pytest.raises(ValueError, match="Duplicate or unexpected"):
        coverage.summarize([LIVE_LIKE[0], LIVE_LIKE[0]])
    with pytest.raises(ValueError, match="Duplicate or unexpected"):
        coverage.summarize([row("OTHER", "provider", 1, 1)])


def test_canonical_query_requires_latest_active_manifest_and_all_media_gates():
    sql = coverage.COVERAGE_SQL
    for clause in (
        "p.active", "p.released_record_count",
        "l.source_manifest_sha256=p.manifest_sha256",
        "l.system_code=p.system_code", "l.language=p.language",
        "m.catalogue_id=l.catalogue_id",
        "m.rights_tier='STOREFRONT_ALLOWED'",
        "m.rights_status='VERIFIED'",
        "m.approval_status='APPROVED'",
        "m.source_status='ACTIVE'",
        "m.revoked_at is null", "m.shopify_file_status='READY'",
        "count(distinct l.reference_key)",
    ):
        assert clause in sql
    assert all(k not in sql.lower() for k in ("insert into", "update tcg.", "delete from"))


@pytest.mark.asyncio
async def test_coverage_route_is_read_only_with_authenticated_context(monkeypatch):
    class Conn:
        async def fetch(self, sql):
            assert sql == coverage.COVERAGE_SQL
            return LIVE_LIKE

        async def execute(self, *args):
            raise AssertionError("Coverage must not write")

    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert user_id == ACTOR and request_id == "dr107-audit"
        yield Conn()

    monkeypatch.setattr(coverage, "user_connection", connection)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="dr107-audit"),
    )
    result = await coverage.artwork_coverage(
        request, SimpleNamespace(user_id=ACTOR)
    )
    assert result["totals"]["released_records"] == 200536
    assert result["checked_at"].endswith("+00:00")
    assert all(not row.get("candidate_image_url") for row in result["games"].values())


def test_coverage_route_requires_platform_admin_at_router_mount():
    main = (Path(__file__).resolve().parents[1] /
            "backend/app/main.py").read_text(encoding="utf-8")
    assert "app.include_router(expanded_artwork_coverage_router, dependencies=[Depends(require_platform_admin_request)])" in main
    assert '@router.get("/coverage")' in Path(coverage.__file__).read_text()
