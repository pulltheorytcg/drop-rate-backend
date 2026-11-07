"""Expansion integration tests; no real provider, SQL or object-store writes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import HTTPException
import pytest

from app import catalogue_browser as browser
from app import r2_collectible_browse as combined
from app import r2_first_service as service
from app import r2_first_sources as sources

OWNER = UUID("11111111-1111-4111-8111-111111111111")


def reference(system="SPORTS_CARDS", **changes):
    row = {"key": "x:" + "a" * 64, "provider": "cardcollectorcapital",
        "system_code": system, "language": "English", "provider_id": "reviewed-source-id",
        "product_type": "CARD", "name": "A Player", "set_id": "2026-bowman-baseball",
        "set_name": "2026 Bowman Baseball", "card_number": "BP-1", "rarity": None,
        "finish": None, "release_date": None, "source_url": "https://example.com/metadata",
        "details": {"source_year": "2026", "sport": "Baseball", "manufacturer": "Topps",
                    "player": "A Player", "team": "Fixture Team", "variant": "Paper Prospects"}}
    row.update(changes)
    return row


@pytest.mark.parametrize("provider,system", [("lorcast", "DISNEY_LORCANA"),
    ("mtgjson", "MAGIC_THE_GATHERING"), ("cardcollectorcapital", "SPORTS_CARDS"),
    ("reviewed_figures", "FIGURES")])
def test_new_sources_have_explicit_reviewed_descriptors(provider, system):
    descriptor = sources.source_descriptor(provider)
    assert descriptor.system_code == system
    assert descriptor.permission_status == "METADATA_ACCESS_DOCUMENTED"
    assert descriptor.source_url.startswith("https://")
    assert descriptor.catalogue_language == ("Not applicable" if system == "FIGURES" else "English")


def test_partial_sports_view_keeps_identity_unknown_and_retains_attribution():
    row = reference()
    result = service._view(row, "a" * 64)
    assert result["sports_card"] == {"system_code": "SPORTS_CARDS", "sport": "Baseball",
        "release_year": 2026, "manufacturer": "Topps", "set_name": "Bowman Baseball",
        "subject_name": "A Player", "team": "Fixture Team", "card_number": "BP-1", "parallel": None}
    assert "language" not in result["sports_card"]
    assert result["source_attribution"]["label"] == "Card Collector Capital · CC BY 4.0"
    assert result["image_url"] is None and result["market_value_minor"] is None
    assert result["reference_verified"] is False and result["identity_review_required"] is True
    assert result["catalogue_id"] is None and row.get("sports_card") is None


def test_figure_view_does_not_invent_edition_or_physical_language():
    row = reference("FIGURES", provider="reviewed_figures", product_type="FIGURE",
        language="Not applicable", details={"manufacturer": "Funko", "franchise": "Pokémon",
            "character": "Pikachu", "product_line": "Pop!", "manufacturer_sku": "43263",
            "box_number": "553"})
    result = service._view(row, "a" * 64)
    assert result["language"] is None and result["figure_details"]["edition"] is None
    assert result["figure_details"]["release_year"] is None
    assert result["figure_details"]["manufacturer_sku"] == "43263"
    assert result["details"]["box_number"] == "553"
    assert result["source_attribution"]["notice_url"] == "/assets/catalogue-source-notices.txt"
    assert row["language"] == "Not applicable"


def test_magic_browse_mapping_does_not_enable_new_recognition_game():
    from app.recognition_games import SYSTEM_BY_GAME
    assert browser.GAME_BY_SYSTEM["MAGIC_THE_GATHERING"] == "Magic: The Gathering"
    assert "Magic: The Gathering" not in SYSTEM_BY_GAME


@pytest.mark.asyncio
@pytest.mark.parametrize("category,system", [("TCG", "FIGURES"), ("TCG", "SPORTS_CARDS"),
    ("SPORTS", "MAGIC_THE_GATHERING"), ("FIGURES", "YUGIOH"), ("COMICS", "FIGURES")])
async def test_categories_never_leak_other_reference_types(category, system, monkeypatch):
    read = AsyncMock()
    monkeypatch.setattr(service, "read", read)
    page = await service.browse(object(), owner_id=OWNER, category=category, system_code=system)
    assert page["items"] == []
    read.assert_not_awaited()


@pytest.fixture
def merge_runtime(monkeypatch):
    canonical = {"key": "c:22222222-2222-4222-8222-222222222222", "catalogue_id": "22222222-2222-4222-8222-222222222222",
        "name": "Bukayo Saka", "system_code": "SPORTS_CARDS", "product_type": "CARD",
        "card_number": "12", "market_value_minor": None, "release_date": None}
    refs = [service._view(reference(), "a" * 64)]
    r2 = AsyncMock(return_value={"items": refs, "has_more": False, "total_count": 1})
    sql = AsyncMock(return_value=[canonical])
    monkeypatch.setattr(service, "browse", r2)
    monkeypatch.setattr(combined.catalogue_r2_live, "read", AsyncMock(return_value=None))
    monkeypatch.setattr(combined.catalogue_r2_live, "fetch", sql)
    query_calls = []
    def query(**kwargs):
        query_calls.append(kwargs)
        return "fixture owner-authorized query", [kwargs["owner_id"]]
    monkeypatch.setattr(browser, "product_query", query)
    monkeypatch.setattr(browser, "with_artwork_path", lambda row: row)
    monkeypatch.setattr(browser, "with_signed_mirror", lambda row: row)
    from app import catalogue_collectibles
    enriched_pages = []
    async def enrich(connection, rows):
        enriched_pages.append(rows)
        assert len(rows) <= 80 and all(not row["key"].startswith("x:") for row in rows)
        return rows
    monkeypatch.setattr(catalogue_collectibles, "with_collectible_details", enrich)
    return SimpleNamespace(canonical=canonical, refs=refs, r2=r2, sql=sql,
                           queries=query_calls, enriched_pages=enriched_pages)


@pytest.mark.asyncio
async def test_new_r2_sports_do_not_hide_existing_canonical_references(merge_runtime):
    page = await combined.browse_collectibles(object(), owner_id=OWNER, system_code="SPORTS_CARDS", limit=1)
    assert page["items"][0]["name"] == "A Player" and page["has_more"]
    assert page["total_count"] == 2 and page["coverage"] == "PARTIAL_REFERENCE_CATALOGUE"
    second = await combined.browse_collectibles(object(), owner_id=OWNER, system_code="SPORTS_CARDS", limit=1, offset=1)
    assert second["items"][0]["name"] == "Bukayo Saka" and not second["has_more"]
    assert merge_runtime.queries[0]["owner_id"] == OWNER


@pytest.mark.asyncio
async def test_owned_filter_uses_real_inventory_even_when_reference_cache_is_cold(merge_runtime):
    merge_runtime.r2.side_effect = HTTPException(503, "reference cache cold")
    page = await combined.browse_collectibles(object(), owner_id=OWNER,
        system_code="SPORTS_CARDS", owned="owned")
    assert page["items"] == [merge_runtime.canonical]
    assert merge_runtime.queries[0]["owned"] == "owned"
    merge_runtime.r2.assert_not_awaited()


@pytest.mark.asyncio
async def test_collectible_union_has_no_silent_overflow(merge_runtime, monkeypatch):
    monkeypatch.setattr(combined, "MAX_MERGED_ROWS", 1)
    with pytest.raises(HTTPException) as error:
        await combined.browse_collectibles(object(), owner_id=OWNER, system_code="SPORTS_CARDS")
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_unexpected_category_does_not_query_or_load_any_source(merge_runtime):
    page = await combined.browse_collectibles(object(), owner_id=OWNER,
        system_code="FIGURES", category="SPORTS")
    assert page["items"] == []
    merge_runtime.r2.assert_not_awaited()
    merge_runtime.sql.assert_not_awaited()
