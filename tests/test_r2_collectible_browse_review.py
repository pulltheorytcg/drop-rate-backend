"""Independent review regressions: bounded, mocked reads; no production access."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import FastAPI
import httpx
import pytest

from app import catalogue_browser as browser
from app import catalogue_collectibles
from app import r2_first_import as worker
from app import r2_first_sources as sources
from app.auth import require_user


OWNER = UUID("11111111-1111-4111-8111-111111111111")
ACTOR = UUID("22222222-2222-4222-8222-222222222222")
CANONICAL = UUID("33333333-3333-4333-8333-333333333333")


def catalogue_row(system="FIGURES", *, key=None, name="Existing canonical figure"):
    figure = system == "FIGURES"
    return {"key": key or "c:" + str(CANONICAL), "catalogue_id": str(CANONICAL),
        "system_code": system, "game": "Figures" if figure else "Sports Cards",
        "product_type": "FIGURE" if figure else "CARD", "provider": "", "provider_id": "",
        "name": name, "set_id": "existing-set", "set_name": "Existing Set",
        "card_number": None if figure else "1", "variant": "", "rarity": None,
        "language": None if figure else "English", "source_kind": "CATALOGUE",
        "release_date": None, "image_url": None, "market_value_minor": None,
        "owned_count": 1, "owned_quantity": 1}


def set_row(system, *, provider="", set_id="existing-set", name="Existing Set", count=2):
    return {"system_code": system, "provider": provider, "language": "" if system == "FIGURES" else "English",
        "set_id": set_id, "set_name": name, "name": name,
        "game": "Figures" if system == "FIGURES" else "Sports Cards", "release_date": None,
        "indexed_count": count, "card_count": count, "owned_count": 1 if not provider else 0,
        "owned_value_minor": None, "unknown_values": 1 if not provider else 0,
        "total_count": 1, "checklist_status": "PARTIAL"}


@pytest.fixture
def route_environment(monkeypatch):
    state = SimpleNamespace(canonical=[], references=[], sql_sets=[], ref_sets=[],
        sql_queries=[], r2_queries=[], set_queries=[], connections=[])
    connection = object()
    @asynccontextmanager
    async def user_connection(pool, actor, operation, **options):
        assert actor == ACTOR
        state.connections.append((operation, options))
        yield connection

    async def fetch(conn, query, params, snapshot, **options):
        assert conn is connection and params[0] == OWNER
        assert "i.owner_id=$1" in query
        assert not any(token in query.lower() for token in ("insert into", "delete from", "update tcg"))
        state.sql_queries.append((query, params, options))
        return deepcopy(state.sql_sets if query == browser.SETS_SQL else state.canonical)

    async def references(conn, **options):
        assert conn is connection and options["owner_id"] == OWNER
        state.r2_queries.append(options)
        return {"items": deepcopy(state.references), "has_more": False,
            "total_count": len(state.references), "offset": 0, "metadata_only": True}

    async def sets(conn, **options):
        assert conn is connection and options["owner_id"] == OWNER
        state.set_queries.append(options)
        return {"items": deepcopy(state.ref_sets), "has_more": False,
            "total_count": len(state.ref_sets), "offset": 0, "coverage": "METADATA_ONLY"}

    async def unchanged(conn, rows):
        assert conn is connection
        return [dict(row) for row in rows]

    monkeypatch.setattr(browser, "user_connection", user_connection)
    monkeypatch.setattr(browser, "delivery_enabled", lambda: False)
    monkeypatch.setattr(browser.catalogue_r2_live, "enabled", lambda _: False)
    monkeypatch.setattr(browser.catalogue_r2_live, "read", AsyncMock(return_value=None))
    monkeypatch.setattr(browser.catalogue_r2_live, "fetch", fetch)
    monkeypatch.setattr(browser.r2_first_service, "browse", references)
    monkeypatch.setattr(browser.r2_first_service, "sets", sets)
    monkeypatch.setattr(browser, "_r2_first_publications", AsyncMock(return_value=[
        {"system_code": "FIGURES", "provider": "reviewed_figures", "active": True},
        {"system_code": "SPORTS_CARDS", "provider": "cardcollectorcapital", "active": True}]))
    monkeypatch.setattr(browser, "read_shared_prices", AsyncMock(return_value={}))
    monkeypatch.setattr(browser, "with_shared_price", lambda row, _: dict(row))
    monkeypatch.setattr(browser, "add_reference_history", unchanged)
    monkeypatch.setattr(browser, "add_asking_estimates", unchanged)
    monkeypatch.setattr(browser, "with_book_details", unchanged)
    monkeypatch.setattr(browser, "with_collectible_details", unchanged)
    monkeypatch.setattr(catalogue_collectibles, "with_collectible_details", unchanged)
    monkeypatch.setattr(browser, "with_signed_mirror", lambda row: dict(row))

    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(browser.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=ACTOR)
    app.dependency_overrides[browser.browser_access] = lambda: {"owner_id": OWNER}
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "review-regression"
        return await call_next(request)
    state.app = app
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("system,category", [("FIGURES", "FIGURES"), ("SPORTS_CARDS", "SPORTS")])
@pytest.mark.parametrize("owned", ["all", "owned"])
async def test_selected_collectible_canonical_only_saved_keys_remain_on_sql(route_environment, system, category, owned):
    state = route_environment
    existing = catalogue_row(system)
    state.canonical = [existing]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser/products", params={
            "system_code": system, "category": category, "keys": existing["key"], "owned": owned})
    assert response.status_code == 200
    assert [row["key"] for row in response.json()["items"]] == [existing["key"]]
    assert state.sql_queries and not state.r2_queries
    query, params, _ = state.sql_queries[0]
    assert "e.key=any(" in query and [existing["key"]] in params
    assert "identity_status='VERIFIED'" in query
    if owned == "owned":
        assert "coalesce(o.quantity,0)>0" in query


@pytest.mark.parametrize("language", ["English", "en", "Japanese"])
def test_figure_publication_permission_rejects_language_not_applicable_mismatch(language):
    descriptor = sources.source_descriptor("reviewed_figures")
    manifest = {"provider": descriptor.provider, "system_code": descriptor.system_code,
        "source_url": descriptor.source_url, "permission_ref": descriptor.permission_ref,
        "language": language}
    with pytest.raises(sources.SourceError):
        worker._permission(manifest)


def test_figure_publication_permission_accepts_only_catalogue_language_scope():
    descriptor = sources.source_descriptor("reviewed_figures")
    assert descriptor.catalogue_language == "Not applicable"
    worker._permission({"provider": descriptor.provider, "system_code": descriptor.system_code,
        "source_url": descriptor.source_url, "permission_ref": descriptor.permission_ref,
        "language": descriptor.catalogue_language})


@pytest.mark.asyncio
@pytest.mark.parametrize("system,provider", [("FIGURES", "reviewed_figures"),
    ("SPORTS_CARDS", "cardcollectorcapital")])
async def test_publishing_partial_source_does_not_hide_existing_canonical_sets(route_environment, system, provider):
    state = route_environment
    state.sql_sets = [set_row(system, name="Existing canonical set")]
    state.ref_sets = [set_row(system, provider=provider, set_id="new-reference-set", name="New reference set")]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser/sets", params={"system_code": system})
    assert response.status_code == 200
    result = response.json()
    assert {row["set_id"] for row in result["items"]} == {"existing-set", "new-reference-set"}
    assert result["total_count"] == 2
    assert result["catalogue_scope"] == "R2_REFERENCE_PLUS_CANONICAL"
    assert state.sql_queries and state.set_queries
    assert state.sql_queries[0][1][0] == OWNER
    assert state.set_queries[0]["owner_id"] == OWNER


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,expected_bounded", [(1, True), (40, False)])
async def test_partial_sports_union_keeps_slab_corrobation_and_review_flags(route_environment, limit, expected_bounded):
    state = route_environment
    good = catalogue_row("SPORTS_CARDS", key="x:" + "a" * 64, name="Fixture Player")
    bad = catalogue_row("SPORTS_CARDS", key="x:" + "b" * 64, name="Wrong Player")
    for row in (good, bad):
        row.update(catalogue_id=None, source_kind="REFERENCE", metadata_only=True,
            identity_review_required=True, owned_count=0, owned_quantity=0,
            provider="cardcollectorcapital", card_number="BP-1", set_id="set", set_name="2026 Bowman Baseball")
    state.references = [good, bad]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser/products", params={
            "system_code": "SPORTS_CARDS", "category": "SPORTS", "slab_name": "Fixture Player",
            "slab_number": "BP-1", "slab_set": "2026 Bowman Baseball", "limit": limit, "sort": "name"})
    assert response.status_code == 200
    result = response.json()
    assert [row["key"] for row in result["items"]] == [good["key"]]
    assert result["slab_review_required"] is True
    assert result["slab_search_bounded"] is expected_bounded
    assert result["total_count"] == 2  # Bounded suggestions, not a complete verified match list.
    assert all(row["identity_review_required"] for row in result["items"])
