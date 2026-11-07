"""R2-first browser integration keeps legacy reads and physical intake boundaries."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI, HTTPException

from app import catalogue_browser as browser
from app.auth import require_user


KEY = "x:" + "a" * 64
SOURCE = {
    "provider": "Lorcast", "system_code": "DISNEY_LORCANA", "language": "English",
    "manifest_sha256": "b" * 64, "generation": "test-generation",
    "record_count": 2, "set_count": 1, "active": True, "game": "Disney Lorcana",
}
RECORD = {
    "key": KEY, "catalogue_id": None, "source_kind": "REFERENCE", "product_type": "CARD",
    "provider": "Lorcast", "system_code": "DISNEY_LORCANA", "language": "English",
    "provider_id": "exact-printing-001", "game": "Disney Lorcana", "name": "Test character",
    "set_id": "1", "set_name": "Test set", "card_number": "1", "rarity": "Rare",
    "variant": "exact-printing-001", "market_value_minor": None, "image_url": None,
}


async def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected source or legacy operation")


@pytest.fixture
def context(monkeypatch):
    owner_id, user_id = uuid4(), uuid4()
    calls = []

    class Connection:
        receipt = None
        rows = []

        async def fetch(self, sql, *args):
            calls.append(("sql", sql, args))
            assert args[0] == owner_id
            return self.rows

        async def fetchrow(self, sql, *args):
            calls.append(("sql_row", sql, args))
            assert "request_receipts" in sql
            assert args[0] == owner_id
            return self.receipt

    connection = Connection()

    @asynccontextmanager
    async def user_connection(pool, subject, request_id, **options):
        assert subject == user_id
        assert request_id == "r2-first-browser-test"
        calls.append(("enter", connection, options))
        try:
            yield connection
        except Exception:
            calls.append(("rollback", connection))
            raise
        else:
            calls.append(("commit", connection))

    async def legacy_read(connection):
        calls.append(("legacy_read", connection))
        return None

    async def legacy_fetch(connection, sql, args, live, **kwargs):
        return await connection.fetch(sql, *args)

    async def no_prices(*args, **kwargs):
        calls.append(("legacy_prices",))
        return {}

    async def unchanged(connection, rows):
        return rows

    monkeypatch.setattr(browser, "user_connection", user_connection)
    monkeypatch.setattr(browser, "delivery_enabled", lambda: False)
    monkeypatch.setattr(browser.catalogue_r2_live, "enabled", lambda *args: False)
    monkeypatch.setattr(browser.catalogue_r2_live, "read", legacy_read)
    monkeypatch.setattr(browser.catalogue_r2_live, "fetch", legacy_fetch)
    monkeypatch.setattr(browser, "read_shared_prices", no_prices)
    for name in ("add_reference_history", "add_asking_estimates", "with_book_details", "with_collectible_details"):
        monkeypatch.setattr(browser, name, unchanged)
    monkeypatch.setattr(browser.r2_first_service, "enabled", lambda: False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id="r2-first-browser-test"))
    return SimpleNamespace(request=request, user=SimpleNamespace(user_id=user_id),
                           access={"owner_id": owner_id}, connection=connection, calls=calls)


async def product_request(context, **changes):
    options = dict(q="", system_code="", language="", set_id="", provider=None,
                   product_type="", owned="all", category="", sort="newest", keys=None,
                   slab_number="", slab_name="", slab_set="", limit=40, offset=0)
    options.update(changes)
    return await browser.products(context.request, context.user, context.access, **options)


def publish(monkeypatch, sources=None):
    monkeypatch.setattr(browser.r2_first_service, "enabled", lambda: True)

    async def publications(connection):
        return [dict(SOURCE)] if sources is None else sources

    monkeypatch.setattr(browser.r2_first_service, "sources", publications)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["games", "sets", "products"])
async def test_disabled_feature_never_calls_new_registry_or_data_source(context, monkeypatch, route):
    for name in ("sources", "read", "resolve", "browse", "materialize", "sets", "games"):
        monkeypatch.setattr(browser.r2_first_service, name, forbidden, raising=False)
    if route == "games":
        await browser.games(context.request, context.user, context.access)
    elif route == "sets":
        await browser.sets(context.request, context.user, context.access, "POKEMON_TCG", "", "", 40, 0)
    else:
        await product_request(context, system_code="POKEMON_TCG")
    assert any(call[0] == "sql" for call in context.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["games", "sets?system_code=DISNEY_LORCANA", "products?system_code=DISNEY_LORCANA", "select", "intake"])
async def test_new_routes_require_active_owner_membership_before_reading_r2(context, monkeypatch, route):
    publish(monkeypatch)

    async def no_membership(sql, *args):
        assert "from tcg.owner_memberships m" in sql
        return []

    monkeypatch.setattr(context.connection, "fetch", no_membership)
    for name in ("sources", "read", "resolve", "browse", "materialize", "sets"):
        monkeypatch.setattr(browser.r2_first_service, name, forbidden, raising=False)
    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(browser.router)
    app.dependency_overrides[require_user] = lambda: context.user

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = context.request.state.request_id
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/v1/catalogue-browser/" + route
        if route in ("select", "intake"):
            result = await client.post(path, json={"key": KEY, "confirmed": True},
                                      headers={"Idempotency-Key": str(uuid4())})
        else:
            result = await client.get(path)
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_games_merge_exact_registry_counts_without_duplicating_sql_canonicals(context, monkeypatch):
    context.connection.rows = [
        {"system_code": "POKEMON_TCG", "game": "Pokémon", "languages": ["English"], "products": 500, "sets": 8},
        {"system_code": "DISNEY_LORCANA", "game": "Disney Lorcana", "languages": ["English"], "products": 1, "sets": 1},
    ]
    publish(monkeypatch, [SOURCE, {**SOURCE, "language": "French", "record_count": 8,
                                 "released_record_count": 3, "set_count": 2},
                         {**SOURCE, "language": "German", "active": False, "record_count": 99}])
    monkeypatch.setattr(browser.r2_first_service, "read", forbidden)
    result = await browser.games(context.request, context.user, context.access)
    by_system = {item["system_code"]: item for item in result["items"]}
    assert by_system["POKEMON_TCG"]["products"] == 500
    assert by_system["POKEMON_TCG"]["sets"] == 8
    assert by_system["DISNEY_LORCANA"] == {
        "system_code": "DISNEY_LORCANA", "game": "Disney Lorcana", "languages": ["English", "French"],
        "products": 5, "sets": 3, "catalogue_scope": "R2_FIRST_SYSTEM"}


@pytest.mark.asyncio
async def test_figures_do_not_offer_unknown_or_metadata_language_filters(context, monkeypatch):
    context.connection.rows = [
        {"system_code": "FIGURES", "game": "Figures", "languages": ["Unknown"],
         "products": 2, "sets": 1},
    ]
    publish(monkeypatch, [{**SOURCE, "provider": "reviewed_figures", "system_code": "FIGURES",
                          "game": "Figures", "language": "Not applicable", "record_count": 4}])
    result = await browser.games(context.request, context.user, context.access)
    figures = next(item for item in result["items"] if item["system_code"] == "FIGURES")
    assert figures["products"] == 6
    assert figures["languages"] == []
    assert figures["catalogue_scope"] == "R2_REFERENCE_PLUS_CANONICAL"


@pytest.mark.asyncio
async def test_published_sets_use_service_and_never_expose_product_artwork(context, monkeypatch):
    publish(monkeypatch)
    expected = {"system_code": "DISNEY_LORCANA", "language": "English", "provider": "Lorcast",
                "set_id": "1", "set_name": "Test set", "card_count": 2, "indexed_count": 2,
                "image_url": "https://unverified.example/card.jpg", "provider_id": "wrong-card",
                "source_kind": "REFERENCE", "owned_count": 0}

    async def sets(connection, **kwargs):
        assert connection is context.connection
        assert kwargs == dict(owner_id=context.access["owner_id"], system_code="DISNEY_LORCANA",
                              language="English", q="Test", limit=12, offset=24)
        return {"items": [expected], "has_more": True, "offset": 24, "total_count": 40,
                "coverage": "R2_FIRST_METADATA"}

    monkeypatch.setattr(browser.r2_first_service, "sets", sets, raising=False)
    result = await browser.sets(context.request, context.user, context.access,
                                "DISNEY_LORCANA", "English", " Test ", 12, 24)
    assert result["total_count"] == 40 and result["offset"] == 24 and result["has_more"]
    assert result["metadata_only"] is True and result["catalogue_scope"] == "R2_FIRST_SYSTEM"
    assert result["items"][0]["card_count"] == 2
    assert "artwork" in result["items"][0]
    for field in ("image_url", "source_kind", "provider_id"):
        assert field not in result["items"][0]
    assert not any(call[0] in {"sql", "sql_row", "legacy_read"} for call in context.calls)


@pytest.mark.asyncio
async def test_published_sets_cold_state_is_not_an_empty_success_or_sql_fallback(context, monkeypatch):
    publish(monkeypatch)

    async def unavailable(*args, **kwargs):
        raise HTTPException(503, "Catalogue snapshot is warming")

    monkeypatch.setattr(browser.r2_first_service, "sets", unavailable, raising=False)
    with pytest.raises(HTTPException) as error:
        await browser.sets(context.request, context.user, context.access,
                           "DISNEY_LORCANA", "English", "", 40, 0)
    assert error.value.status_code == 503
    assert not any(call[0] in {"sql", "sql_row", "legacy_read"} for call in context.calls)


@pytest.mark.asyncio
async def test_selected_published_system_routes_before_legacy_queries_and_prices(context, monkeypatch):
    publish(monkeypatch)
    received = {}

    async def browse(connection, **kwargs):
        assert connection is context.connection
        received.update(kwargs)
        return {"items": [dict(RECORD)], "has_more": False, "offset": kwargs["offset"]}

    monkeypatch.setattr(browser.r2_first_service, "browse", browse)
    result = await product_request(context, system_code="DISNEY_LORCANA", language="English",
        q="Test", category="TCG", provider="Lorcast", product_type="CARD", owned="owned",
        sort="value_desc", set_id="1", keys=KEY, limit=12, offset=24)
    assert received == dict(owner_id=context.access["owner_id"], q="Test", system_code="DISNEY_LORCANA",
        language="English", category="TCG", set_id="1", provider="Lorcast", product_type="CARD",
        owned="owned", sort="value_desc", keys=[KEY], limit=12, offset=24)
    assert result["items"][0]["key"] == KEY
    assert result["items"][0]["market_value_minor"] is None
    assert result["items"][0]["image_url"] is None
    assert result["catalogue_scope"] == "R2_FIRST_SYSTEM"
    assert result["metadata_only"] is True
    assert not result["slab_review_required"]
    assert not any(call[0] in {"sql", "sql_row", "legacy_read", "legacy_prices"} for call in context.calls)


@pytest.mark.asyncio
async def test_pure_x_saved_keys_work_without_selecting_a_system(context, monkeypatch):
    publish(monkeypatch)

    async def browse(connection, **kwargs):
        assert kwargs["keys"] == [KEY] and kwargs["system_code"] == ""
        assert kwargs["limit"] == 40 and kwargs["offset"] == 0
        return {"items": [dict(RECORD)], "has_more": False, "offset": 0}

    monkeypatch.setattr(browser.r2_first_service, "browse", browse)
    result = await product_request(context, keys=KEY)
    assert result["items"][0]["key"] == KEY
    assert result["catalogue_scope"] == "R2_FIRST_KEYS"
    assert not any(call[0] in {"sql", "sql_row", "legacy_read", "legacy_prices"} for call in context.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("sort,offset,expected", [
    ("name", 0, KEY), ("name", 1, "r:" + "c" * 32),
    ("name_desc", 0, "r:" + "c" * 32),
    ("newest", 0, KEY), ("oldest", 0, "r:" + "c" * 32),
    ("value_desc", 0, "r:" + "c" * 32), ("value_asc", 0, "r:" + "c" * 32),
])
async def test_mixed_keys_merge_before_sort_and_paging_with_bounded_legacy_prices(context, monkeypatch, sort, offset, expected):
    publish(monkeypatch)
    legacy_key = "r:" + "c" * 32
    context.connection.rows = [{**RECORD, "key": legacy_key, "name": "Zeta", "provider": "Legacy",
                                "release_date": "2020-01-01", "market_value_minor": 500}]
    new_record = {**RECORD, "name": "Alpha", "release_date": "2024-01-01"}

    async def browse(connection, **kwargs):
        assert kwargs["keys"] == [KEY] and kwargs["system_code"] == ""
        assert kwargs["limit"] == 100 and kwargs["offset"] == 0
        return {"items": [new_record], "has_more": False, "offset": 0, "total_count": 1}

    async def bounded_prices(connection, rows):
        assert [row["key"] for row in rows] == []  # Legacy example is already priced.
        return {}

    monkeypatch.setattr(browser.r2_first_service, "browse", browse)
    monkeypatch.setattr(browser, "read_shared_prices", bounded_prices)
    result = await product_request(context, keys=legacy_key + "," + KEY, sort=sort, limit=1, offset=offset)
    assert [row["key"] for row in result["items"]] == [expected]
    assert result["total_count"] == 2 and result["has_more"] == (offset == 0)
    assert result["catalogue_scope"] == "EXPLICIT_REFERENCE_KEYS"
    assert result["includes_r2_metadata"] is True
    sql_calls = [call for call in context.calls if call[0] == "sql"]
    assert len(sql_calls) == 1
    assert [legacy_key] in sql_calls[0][2] and [legacy_key, KEY] not in sql_calls[0][2]
    assert sql_calls[0][2][-2:] == (101, 0)
    assert "selected_page as materialized" in sql_calls[0][1]


@pytest.mark.asyncio
async def test_mixed_keys_do_not_return_partial_legacy_results_when_r2_is_unavailable(context, monkeypatch):
    publish(monkeypatch)

    async def unavailable(*args, **kwargs):
        raise HTTPException(503, "Current snapshot is unavailable")

    monkeypatch.setattr(browser.r2_first_service, "browse", unavailable)
    with pytest.raises(HTTPException) as error:
        await product_request(context, keys="r:" + "c" * 32 + "," + KEY)
    assert error.value.status_code == 503
    assert not any(call[0] in {"sql", "legacy_read"} for call in context.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("sources,system", [([SOURCE], "POKEMON_TCG"),
    ([{**SOURCE, "active": False}], "DISNEY_LORCANA"), ([], "DISNEY_LORCANA")])
async def test_unpublished_or_legacy_system_uses_unchanged_sql_route(context, monkeypatch, sources, system):
    publish(monkeypatch, sources)
    monkeypatch.setattr(browser.r2_first_service, "browse", forbidden)
    await product_request(context, system_code=system)
    assert any(call[0] == "sql" for call in context.calls)


@pytest.mark.asyncio
async def test_global_legacy_query_reports_separate_source_scope(context, monkeypatch):
    publish(monkeypatch)
    monkeypatch.setattr(browser.r2_first_service, "browse", forbidden)
    result = await product_request(context)
    assert result["catalogue_scope"] == "LEGACY_WITH_SEPARATE_R2_SYSTEMS"
    assert result["additional_catalogue_systems"] == ["DISNEY_LORCANA"]
    assert any(call[0] == "sql" for call in context.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cold", "stale", "corrupt"])
async def test_unavailable_published_source_returns_503_without_sql_fallback(context, monkeypatch, reason):
    publish(monkeypatch)

    async def unavailable(*args, **kwargs):
        raise HTTPException(503, "Published catalogue is " + reason)

    monkeypatch.setattr(browser.r2_first_service, "browse", unavailable)
    with pytest.raises(HTTPException) as error:
        await product_request(context, system_code="DISNEY_LORCANA")
    assert error.value.status_code == 503
    assert not any(call[0] in {"sql", "sql_row", "legacy_read", "legacy_prices"} for call in context.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["select", "intake"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_unknown_or_disabled_x_keys_never_fall_back_to_sql(context, monkeypatch, route, enabled):
    monkeypatch.setattr(browser.r2_first_service, "enabled", lambda: enabled)

    async def missing(connection, key):
        assert enabled and connection is context.connection and key == KEY
        return None

    monkeypatch.setattr(browser.r2_first_service, "resolve", missing if enabled else forbidden)
    monkeypatch.setattr(browser.r2_first_service, "materialize", forbidden)
    with pytest.raises(HTTPException) as error:
        if route == "select":
            await browser.select_product(browser.CatalogueSelection(key=KEY, confirmed=True),
                context.request, context.user, context.access)
        else:
            await browser.intake(browser.BrowseIntake(key=KEY, confirmed=True),
                context.request, context.user, context.access, str(uuid4()))
    assert error.value.status_code == 404
    assert not any(call[0] == "sql" for call in context.calls)
    assert all("request_receipts" in call[1] for call in context.calls if call[0] == "sql_row")


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["select", "intake"])
async def test_x_resolution_failure_is_503_not_missing_or_sql_fallback(context, monkeypatch, route):
    publish(monkeypatch)

    async def unavailable(connection, key):
        raise HTTPException(503, "Current manifest failed integrity verification")

    monkeypatch.setattr(browser.r2_first_service, "resolve", unavailable)
    monkeypatch.setattr(browser.r2_first_service, "materialize", forbidden)
    with pytest.raises(HTTPException) as error:
        if route == "select":
            await browser.select_product(browser.CatalogueSelection(key=KEY, confirmed=True),
                context.request, context.user, context.access)
        else:
            await browser.intake(browser.BrowseIntake(key=KEY, confirmed=True),
                context.request, context.user, context.access, str(uuid4()))
    assert error.value.status_code == 503
    assert not any(call[0] == "sql" for call in context.calls)
    assert all("request_receipts" in call[1] for call in context.calls if call[0] == "sql_row")


@pytest.mark.asyncio
async def test_x_selection_materializes_only_current_server_identity_in_authorized_transaction(context, monkeypatch):
    publish(monkeypatch)
    catalogue_id = uuid4()
    events = []

    async def resolve(connection, key):
        assert connection is context.connection and key == KEY
        events.append("resolve")
        return dict(RECORD)

    async def materialize(connection, item):
        assert connection is context.connection and item == RECORD
        events.append("materialize")
        return {"id": catalogue_id}

    monkeypatch.setattr(browser.r2_first_service, "resolve", resolve)
    monkeypatch.setattr(browser.r2_first_service, "materialize", materialize)
    monkeypatch.setattr(browser, "_create_inventory_intake", forbidden)
    monkeypatch.setattr(browser, "create_inventory_intake", forbidden)
    result = await browser.select_product(browser.CatalogueSelection(key=KEY, confirmed=True),
        context.request, context.user, context.access)
    assert result == {"catalogue_id": str(catalogue_id)}
    assert events == ["resolve", "materialize"]
    assert not any(call[0] in {"sql", "sql_row"} for call in context.calls)


@pytest.mark.asyncio
async def test_x_intake_canonical_inventory_and_receipt_share_owner_transaction(context, monkeypatch):
    publish(monkeypatch)
    catalogue_id, request_key = uuid4(), str(uuid4())
    payload = browser.BrowseIntake(key=KEY, condition="Near Mint", confirmed=True)
    events = []

    async def resolve(connection, key):
        assert connection is context.connection and key == KEY
        events.append("resolve")
        return dict(RECORD)

    async def materialize(connection, item):
        assert connection is context.connection and item == RECORD
        events.append("materialize")
        return {"id": catalogue_id}

    async def create(manual, request, user, idempotency_key, *, connection):
        assert connection is context.connection
        assert request is context.request and user is context.user
        assert idempotency_key == request_key
        assert manual.catalogue_id == catalogue_id and manual.new_catalogue is None
        assert manual.condition == "Near Mint" and manual.identity_confirmed is False
        assert manual.acquisition_cost_minor is None and manual.store_price_minor is None
        assert manual.notes == browser.browse_note(payload)
        events.append("create")
        return {"inventory": {"inventory_code": "INV-ONCE", "notes": manual.notes}, "replayed": False}

    monkeypatch.setattr(browser.r2_first_service, "resolve", resolve)
    monkeypatch.setattr(browser.r2_first_service, "materialize", materialize)
    monkeypatch.setattr(browser, "_create_inventory_intake", create)
    monkeypatch.setattr(browser, "create_inventory_intake", forbidden)
    result = await browser.intake(payload, context.request, context.user, context.access, request_key)
    assert result["inventory"]["inventory_code"] == "INV-ONCE"
    assert events == ["resolve", "materialize", "create"]
    assert sum(call[0] == "enter" for call in context.calls) == 1
    assert context.calls[-1][0] == "commit"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_x_receipt_replays_before_provider_resolution_even_when_disabled(context, monkeypatch, changed):
    payload = browser.BrowseIntake(key=KEY, condition="Near Mint", confirmed=True)
    context.connection.receipt = {"response": {"inventory": {"inventory_code": "INV-EXISTING",
        "notes": browser.browse_note(payload)}, "replayed": False}}
    for name in ("resolve", "sources", "read", "materialize"):
        monkeypatch.setattr(browser.r2_first_service, name, forbidden)
    monkeypatch.setattr(browser, "_create_inventory_intake", forbidden)
    if changed:
        with pytest.raises(HTTPException) as error:
            await browser.intake(payload.model_copy(update={"condition": "Lightly Played"}),
                context.request, context.user, context.access, str(uuid4()))
        assert error.value.status_code == 409
    else:
        result = await browser.intake(payload, context.request, context.user, context.access, str(uuid4()))
        assert result["replayed"] is True
        assert result["inventory"]["inventory_code"] == "INV-EXISTING"


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"seal_status": "SEALED"}, {"language": "Japanese"}])
async def test_x_physical_validation_happens_before_canonical_materialization(context, monkeypatch, changes):
    publish(monkeypatch)

    async def resolve(connection, key):
        return dict(RECORD)

    monkeypatch.setattr(browser.r2_first_service, "resolve", resolve)
    monkeypatch.setattr(browser.r2_first_service, "materialize", forbidden)
    payload = browser.BrowseIntake(key=KEY, confirmed=True, **changes)
    with pytest.raises(HTTPException) as error:
        await browser.intake(payload, context.request, context.user, context.access, str(uuid4()))
    assert error.value.status_code == 422
    assert context.calls[-1][0] == "rollback"


@pytest.mark.asyncio
async def test_x_intake_error_propagates_with_transaction_rollback(context, monkeypatch):
    publish(monkeypatch)

    async def resolve(connection, key):
        return dict(RECORD)

    async def materialize(connection, item):
        assert connection is context.connection
        return {"id": uuid4()}

    async def create(*args, connection):
        assert connection is context.connection
        raise HTTPException(409, "Inventory validation failed")

    monkeypatch.setattr(browser.r2_first_service, "resolve", resolve)
    monkeypatch.setattr(browser.r2_first_service, "materialize", materialize)
    monkeypatch.setattr(browser, "_create_inventory_intake", create)
    with pytest.raises(HTTPException) as error:
        await browser.intake(browser.BrowseIntake(key=KEY, confirmed=True),
            context.request, context.user, context.access, str(uuid4()))
    assert error.value.status_code == 409
    assert context.calls[-1][0] == "rollback"
    assert not any(call[0] == "commit" for call in context.calls)
