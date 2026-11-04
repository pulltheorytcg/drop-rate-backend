from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import re

import httpx
import pytest
from fastapi import FastAPI

from app import catalogue_browser as browser
from app.auth import require_user
from app.catalogue_browse_groups import BROWSE_GROUPS, group_for, group_predicate, validate_browse_group


@pytest.mark.parametrize("system,facts,expected", [
    ("MARVEL_COMICS", {}, "MARVEL"), ("DC_COMICS", {}, "DC"),
    ("OTHER_COMICS", {"publisher": " Image Comics "}, "INDIE"),
    ("OTHER_COMICS", {"publisher": "Dark Horse"}, "INDIE"),
    ("OTHER_COMICS", {"publisher": "IDW Publishing"}, "INDIE"),
    ("OTHER_COMICS", {"publisher": "Unreviewed small press"}, "OTHER"),
    ("OTHER_COMICS", {"publisher": "Marvel character fan anthology"}, "OTHER"),
    ("OTHER_COMICS", {"publisher": None}, "OTHER"),
    ("OTHER_COMICS", {"publisher": ["Image Comics"]}, "OTHER"),
    ("MANGA", {"series_title": " One Piece "}, "SHONEN"),
    ("MANGA", {"series_title": "Baby & Me"}, "SHOJO"),
    ("MANGA", {"series_title": "Initial D", "publisher": "Tokyopop"}, "SEINEN"),
    ("MANGA", {"series_title": "Princess Jellyfish"}, "JOSEI"),
    ("MANGA", {"publisher": "VIZ Media", "series_title": "Other title"}, "UNKNOWN"),
    ("MANGA", {"publisher": "Kodansha", "demographic": "SHONEN"}, "UNKNOWN"),
    ("MANGA", {"series_title": "Shonen title not reviewed", "rating": "16+"}, "UNKNOWN"),
    ("MANGA", {"series_title": "One Piece spin-off"}, "UNKNOWN"),
    ("MANGA", {"series_title": "İnitial D"}, "UNKNOWN"),
    ("MANGA", {"series_title": {"name": "Naruto"}}, "UNKNOWN"),
    ("SPORTS_CARDS", {"manufacturer": "PANINI"}, "PANINI"),
    ("SPORTS_CARDS", {"manufacturer": "Panini America"}, "PANINI"),
    ("SPORTS_CARDS", {"manufacturer": "Topps"}, "TOPPS"),
    ("SPORTS_CARDS", {"manufacturer": "Other Topps-like company"}, "OTHER"),
    ("SPORTS_CARDS", {"manufacturer": "PanİNİ"}, "OTHER"),
    ("SPORTS_CARDS", {"manufacturer": ["Topps"]}, "OTHER"),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "Pop!"}, "FUNKO_POP"),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "Pop"}, "FUNKO_POP"),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "Other"}, "OTHER"),
    ("FIGURES", {"manufacturer": "Good Smile Company", "product_line": "Nendoroid"}, "FIGURINES"),
    ("FIGURES", {"manufacturer": "Good Smile Company", "product_line": "Unknown"}, "OTHER"),
    ("FIGURES", {"manufacturer": "Unreviewed", "product_line": "Pop!"}, "OTHER"),
    ("FIGURES", {}, "OTHER"),
    ("POKEMON_TCG", {"manufacturer": "Topps"}, ""),
])
def test_exact_reviewed_classification_does_not_mutate_identity(system, facts, expected):
    before = deepcopy(facts)
    assert group_for(system, facts) == expected
    assert facts == before


@pytest.mark.parametrize("system", ["FIGURES", "MANGA", "SPORTS_CARDS", "OTHER_COMICS"])
@pytest.mark.parametrize("facts", [None, "unsafe", ["Topps"], 42])
def test_unstructured_facts_remain_unknown(system, facts):
    assert group_for(system, facts) == ("UNKNOWN" if system == "MANGA" else "OTHER")


@pytest.mark.parametrize("group,category,system", [
    ("OTHER", "", ""), ("SHONEN", "", ""),
    ("PANINI", "MANGA", ""), ("SHONEN", "MANGA", "SPORTS_CARDS"),
    ("OTHER", "TCG", ""), ("OTHER", "", "POKEMON_TCG"),
    ("MARVEL", "COMICS", "DC_COMICS"), ("INDIE", "", "MARVEL_COMICS"),
    ("DC", "", "OTHER_COMICS"), ("%' OR true --", "COMICS", ""),
    ("shonen", "MANGA", ""), (None, "MANGA", ""),
])
def test_invalid_mismatched_and_ambiguous_groups_fail_closed(group, category, system):
    with pytest.raises(ValueError):
        validate_browse_group(group, category=category, system_code=system)


def test_all_supported_groups_require_and_accept_their_category():
    for category, groups in BROWSE_GROUPS.items():
        for group in groups:
            assert validate_browse_group(group, category=category) == group
    assert validate_browse_group("", system_code="POKEMON_TCG") == ""


@pytest.mark.parametrize("category,group", [(category, group) for category, groups in BROWSE_GROUPS.items() for group in groups])
@pytest.mark.parametrize("sort", ["newest", "value_asc"])
def test_product_groups_are_bound_before_pagination_with_owned_and_saved_filters(category, group, sort):
    owner = uuid4()
    query, params = browser.product_query(owner_id=owner, category=category, browse_group=group,
        owned="owned", keys=["c:" + str(uuid4())], q="literal %' term", sort=sort, limit=2, offset=3)
    assert params[0] == owner and params[-2:] == [3, 3]
    assert group in params and "literal %' term" not in query
    assert "coalesce(o.quantity,0)>0" in query and "e.key=any(" in query
    assert "i.owner_id=$1" in query
    assert query.index("browse_profile.catalogue_id=e.catalogue_id") < query.index("limit $")
    assert {int(number) for number in re.findall(r"\$(\d+)", query)} == set(range(1, len(params) + 1))


def test_empty_group_retains_legacy_sql_and_parameters():
    owner = uuid4()
    assert browser.product_query(owner_id=owner) == browser.product_query(owner_id=owner, browse_group="")
    assert browser.sets_query(owner_id=owner, system_code="COMICS", q="  literal  ") == (
        browser.SETS_SQL, [owner, browser.browse_systems("COMICS"), "", "literal", 41, 0])


@pytest.mark.parametrize("system,group", [("COMICS", "INDIE"), ("MANGA", "SHONEN"),
    ("SPORTS_CARDS", "TOPPS"), ("FIGURES", "FUNKO_POP")])
def test_grouped_set_counts_filter_entries_before_group_and_page(system, group):
    query, params = browser.sets_query(owner_id=uuid4(), system_code=system, browse_group=group,
        q="literal %'", limit=2, offset=1)
    assert params[3] == "literal %'" and params[-2:] == [3, 1]
    assert "literal %'" not in query and "i.owner_id=$1" in query
    predicate = query.index("browse_profile.catalogue_id=e.catalogue_id")
    assert predicate < query.index("group by e.system_code") < query.index("limit $")
    assert "declared_card_count" not in query
    assert {int(number) for number in re.findall(r"\$(\d+)", query)} == set(range(1, len(params) + 1))


def test_predicate_rejects_unreviewed_group_and_sql_identifier():
    with pytest.raises(ValueError):
        group_predicate("unreviewed", lambda value: "$1")
    with pytest.raises(ValueError):
        group_predicate("OTHER", lambda value: "$1", entry_alias="e;select")


@pytest.fixture
def grouped_app(monkeypatch):
    user_id, owner = uuid4(), uuid4()
    queries, connection_calls = [], []
    class Connection:
        async def fetch(self, query, *params):
            queries.append((query, params))
            return []
    @asynccontextmanager
    async def connection(*args, **kwargs):
        connection_calls.append(args)
        yield Connection()
    async def passthrough(connection, rows):
        return rows
    monkeypatch.setattr(browser, "user_connection", connection)
    monkeypatch.setattr(browser, "_r2_first_publications", AsyncMock(return_value=[]))
    monkeypatch.setattr(browser.catalogue_r2_live, "read", AsyncMock(side_effect=AssertionError("Grouped queries must not hydrate legacy R2")))
    monkeypatch.setattr(browser, "read_shared_prices", AsyncMock(return_value={}))
    for helper in ("add_reference_history", "add_asking_estimates", "with_book_details", "with_collectible_details"):
        monkeypatch.setattr(browser, helper, passthrough)
    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(browser.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=user_id)
    app.dependency_overrides[browser.browser_access] = lambda: {"owner_id": owner}
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "group-test"
        return await call_next(request)
    return app, owner, queries, connection_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/products?browse_group=SHONEN", "/products?browse_group=OTHER&keys=x:saved",
    "/products?category=TCG&browse_group=TOPPS", "/products?category=MANGA&system_code=SPORTS_CARDS&browse_group=SHONEN",
    "/sets?system_code=MANGA&browse_group=MARVEL", "/sets?system_code=POKEMON_TCG&browse_group=OTHER",
])
async def test_routes_reject_ambiguous_or_mismatched_groups_before_data_read(grouped_app, path):
    app, _, queries, calls = grouped_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser" + path)
    assert response.status_code == 422
    assert queries == [] and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path,group", [("/products?category=MANGA&browse_group=SHONEN", "SHONEN"),
    ("/sets?system_code=COMICS&browse_group=INDIE", "INDIE")])
async def test_grouped_canonical_routes_use_scoped_sql_without_legacy_r2(grouped_app, path, group):
    app, owner, queries, calls = grouped_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser" + path)
    assert response.status_code == 200 and response.json()["items"] == []
    assert len(calls) == 1 and len(queries) == 1
    assert queries[0][1][0] == owner and group in queries[0][1]


@pytest.mark.asyncio
async def test_category_only_group_dispatch_includes_r2_collectible_references(monkeypatch, grouped_app):
    from app import r2_collectible_browse
    app, owner, _, _ = grouped_app
    monkeypatch.setattr(browser, "_r2_first_publications", AsyncMock(return_value=[{"system_code": "SPORTS_CARDS"}]))
    browse = AsyncMock(return_value={"items": [], "has_more": False})
    monkeypatch.setattr(r2_collectible_browse, "browse_collectibles", browse)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser/products?category=SPORTS&browse_group=TOPPS")
    assert response.status_code == 200
    assert browse.await_args.kwargs["browse_group"] == "TOPPS"
    assert browse.await_args.kwargs["system_code"] == "SPORTS_CARDS"
    assert browse.await_args.kwargs["owner_id"] == owner


@pytest.mark.asyncio
async def test_mixed_saved_keys_carry_group_into_both_engines_before_final_page(monkeypatch, grouped_app):
    app, owner, queries, _ = grouped_app
    canonical = "c:" + str(uuid4())
    monkeypatch.setattr(browser, "_r2_first_publications", AsyncMock(return_value=[{"system_code": "SPORTS_CARDS"}]))
    browse = AsyncMock(return_value={"items": [{"key": "x:saved", "name": "Topps reference", "market_value_minor": None}], "has_more": False})
    monkeypatch.setattr(browser.r2_first_service, "browse", browse)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue-browser/products", params={
            "category": "SPORTS", "browse_group": "TOPPS", "keys": f"x:saved,{canonical}", "limit": 1})
    assert response.status_code == 200
    assert browse.await_args.kwargs["browse_group"] == "TOPPS"
    assert browse.await_args.kwargs["keys"] == ["x:saved"]
    assert browse.await_args.kwargs["limit"] == 100 and browse.await_args.kwargs["offset"] == 0
    assert queries[0][1][0] == owner and "TOPPS" in queries[0][1]
    assert [canonical] in queries[0][1] and queries[0][1][-2:] == (101, 0)
    assert response.json()["items"][0]["key"] == "x:saved"
    assert response.json()["total_count"] == 1
