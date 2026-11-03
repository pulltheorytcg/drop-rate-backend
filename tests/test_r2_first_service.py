"""R2 delivery unit tests using local immutable bytes and explicit fake SQL.

These are not live provider tests or substitutes for native RLS integration tests.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import HTTPException
import pytest
import pytest_asyncio

from app import r2_first_catalogue as codec
from app import r2_first_service as service


OWNER_A = UUID("11111111-1111-4111-8111-111111111111")
OWNER_B = UUID("22222222-2222-4222-8222-222222222222")
CATALOGUE_ID = UUID("33333333-3333-4333-8333-333333333333")


def row(provider_id="one", **changes):
    value = {"provider": "ygoprodeck", "system_code": "YUGIOH", "language": "English",
        "provider_id": provider_id, "product_type": "CARD", "name": "Fixture Card",
        "set_id": "ABC", "set_name": "Fixture Set", "card_number": "ABC-EN001",
        "rarity": "Rare", "finish": None, "release_date": None,
        "source_url": "https://db.ygoprodeck.com/api/v7/cardinfo.php"}
    value.update(changes)
    return value


class LocalObjects:
    def __init__(self):
        self.objects, self.reads, self.puts = {}, [], []
        self.assert_outside = lambda: None

    def put_verified_reference_snapshot(self, raw):
        self.assert_outside()
        digest = hashlib.sha256(raw).hexdigest()
        self.objects[digest] = raw
        self.puts.append(digest)
        return {"sha256": digest, "verified": True}

    def read_verified_reference_snapshot(self, digest):
        self.assert_outside()
        self.reads.append(digest)
        return self.objects[digest]


def publication(snapshot, **changes):
    manifest = snapshot.manifest
    value = {**{key: manifest[key] for key in ("provider", "system_code", "language",
        "source_url", "source_revision", "permission_ref", "record_count", "raw_bytes")},
        "manifest_sha256": snapshot.manifest_digest,
        "set_count": len(snapshot.sets()), "released_record_count": snapshot.search(limit=1)["total"],
        "active": True, "generation": 1, "published_by": OWNER_A,
        "published_at": datetime.now(timezone.utc)}
    value.update(changes)
    return value


class Connection:
    def __init__(self, publications=()):
        self.publications = list(publications)
        self.registry_exists = True
        self.calls = []
        self.owner_links = {OWNER_A: [], OWNER_B: []}
        self.canonical = {}
        self.in_transaction = False

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        assert "to_regclass" in sql, "Unexpected SQL fallback: " + sql
        return self.registry_exists

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if "select * from tcg_private.r2_first_catalogue_publications" in sql:
            return [deepcopy(p) for p in self.publications if p["active"]]
        assert "r2_first_catalogue_links" in sql and "i.owner_id=$1" in sql
        assert len(args) == 2
        owned = {r["reference_key"]: r for r in self.owner_links.get(args[0], [])}
        if isinstance(args[1], list):
            return [deepcopy(owned[key] if key in owned else {"reference_key": key,
                "catalogue_id": self.canonical[key], "owned_quantity": 0})
                for key in args[1] if key in owned or key in self.canonical]
        return deepcopy(self.owner_links.get(args[0], []))


@pytest_asyncio.fixture(autouse=True)
async def clean_runtime(monkeypatch):
    await service.close()
    assert service._leases == {} and service._retired == {}
    monkeypatch.setenv("TCG_R2_FIRST_CATALOGUE_ENABLED", "true")
    monkeypatch.setattr(service, "_load_semaphore", asyncio.Semaphore(1))
    yield
    await service.close()
    assert service._leases == {} and service._retired == {}


@pytest_asyncio.fixture
async def snapshots(monkeypatch):
    store, opened = LocalObjects(), []
    monkeypatch.setattr(service, "storage", lambda: store)

    async def make(rows=None, revision="fixture:one", **scope):
        args = {"provider": "ygoprodeck", "system_code": "YUGIOH", "language": "English",
            "source_url": "https://db.ygoprodeck.com/api/v7/cardinfo.php",
            "source_revision": revision, "permission_ref": "https://ygoprodeck.com/api-guide/"}
        args.update(scope)
        values = rows if rows is not None else [row()]
        values = [{**value, **{k: args[k] for k in ("provider", "system_code", "language")}} for value in values]
        prepared = codec.prepare_catalogue(values, **args)
        manifest = await codec.upload_and_verify(prepared, store)
        snapshot = await codec.load_catalogue(manifest, store)
        opened.append(snapshot)
        return snapshot

    make.store = store
    yield make
    for snapshot in opened:
        snapshot.close()


def cache(snapshot):
    service._cache[snapshot.manifest_digest] = snapshot
    return publication(snapshot)


def owned_link(key, quantity=1, value=None):
    return {"reference_key": key, "catalogue_id": CATALOGUE_ID,
        "owned_quantity": quantity, "owned_value_minor": value,
        "unknown_values": quantity if value is None else 0}


@pytest.mark.asyncio
async def test_feature_disabled_does_not_query_or_warm_anything(monkeypatch):
    monkeypatch.setenv("TCG_R2_FIRST_CATALOGUE_ENABLED", "false")
    connection = Connection()
    assert await service.sources(connection) == []
    assert await service.resolve(connection, "x:" + "a" * 64) is None
    assert connection.calls == [] and service._loading == {}


@pytest.mark.asyncio
async def test_missing_registry_is_explicit_503_not_postgres_catalogue_fallback():
    connection = Connection()
    connection.registry_exists = False
    with pytest.raises(HTTPException) as error:
        await service.read(connection)
    assert error.value.status_code == 503 and len(connection.calls) == 1
    assert "to_regclass" in connection.calls[0][0]


@pytest.mark.asyncio
async def test_partition_count_overflow_fails_closed(snapshots):
    snapshot = await snapshots()
    connection = Connection([publication(snapshot)] * (service.MAX_PARTITIONS + 1))
    with pytest.raises(HTTPException) as error:
        await service.read(connection)
    assert error.value.status_code == 503 and service._loading == {}


@pytest.mark.asyncio
async def test_cold_read_returns_503_and_schedules_only_one_load_without_sql_fallback(snapshots, monkeypatch):
    snapshot = await snapshots()
    connection = Connection([publication(snapshot)])
    entered = asyncio.Event()

    async def load(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_load", load)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await service.read(connection, system_code="YUGIOH")
        assert error.value.status_code == 503
        assert error.value.headers["Retry-After"] == "10"
    assert len(service._loading) == 1
    await entered.wait()
    assert all("r2_first_catalogue_publications" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_verified_load_rebuilds_cold_then_warm_reads_need_no_object_io(snapshots):
    snapshot = await snapshots()
    pub = publication(snapshot)
    connection = Connection([pub])
    await service._load(pub)
    reads = len(snapshots.store.reads)
    key = snapshot.search()["items"][0]["key"]
    result = await service.resolve(connection, key)
    assert result["name"] == "Fixture Card"
    assert result["source_manifest_sha256"] == snapshot.manifest_digest
    assert result["metadata_only"] and result["identity_review_required"]
    assert result["reference_verified"] is False
    assert result["image_url"] is None and result["market_value_minor"] is None
    assert len(snapshots.store.reads) == reads


@pytest.mark.asyncio
async def test_revoked_registry_row_never_serves_a_warm_cached_reference(snapshots):
    snapshot = await snapshots()
    connection = Connection([cache(snapshot)])
    key = snapshot.search()["items"][0]["key"]
    assert await service.resolve(connection, key) is not None
    connection.publications[0]["active"] = False
    assert await service.resolve(connection, key) is None
    assert await service.read(connection) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("permission_ref", "review:revoked"),
    ("source_revision", "other-revision"), ("record_count", 2), ("raw_bytes", 1)])
async def test_changed_registry_binding_does_not_fall_back_to_cached_approval(snapshots, field, value):
    snapshot = await snapshots()
    connection = Connection([cache(snapshot)])
    connection.publications[0][field] = value
    with pytest.raises(HTTPException) as error:
        await service.read(connection)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_missing_or_corrupt_r2_objects_are_backed_off_and_do_not_serve_partial_index(snapshots):
    snapshot = await snapshots()
    pub = publication(snapshot)
    part = snapshot.manifest["parts"][0]["sha256"]
    snapshots.store.objects[part] = b"corrupt"
    await service._load(pub)
    assert snapshot.manifest_digest not in service._cache
    assert snapshot.manifest_digest in service._failures
    with pytest.raises(HTTPException) as error:
        service._cached(pub)
    assert error.value.status_code == 503 and service._loading == {}


@pytest.mark.asyncio
async def test_prewarm_closes_sql_transaction_before_object_reads(snapshots, monkeypatch):
    snapshot = await snapshots()
    connection = Connection([publication(snapshot)])

    @asynccontextmanager
    async def context(pool, actor, operation, **kwargs):
        assert kwargs["readonly_snapshot"] is True
        connection.in_transaction = True
        try:
            yield connection
        finally:
            connection.in_transaction = False

    def outside():
        assert not connection.in_transaction

    monkeypatch.setattr(service, "user_connection", context)
    monkeypatch.setattr(service, "require_platform_admin", AsyncMock())
    snapshots.store.assert_outside = outside
    await service.prewarm(None, OWNER_A)
    assert snapshot.manifest_digest in service._cache


@pytest.mark.asyncio
async def test_eviction_waits_for_active_request_lease(snapshots, monkeypatch):
    first = await snapshots(revision="first")
    next_snapshot = await snapshots(revision="next")
    cache(first)
    with service._borrow([first]):
        await service._load(publication(next_snapshot))
        assert first.manifest_digest not in service._cache
        assert first.search()["total"] == 1
        assert id(first) in service._retired
    with pytest.raises(codec.R2FirstCatalogueError, match="unavailable"):
        first.search()


@pytest.mark.asyncio
async def test_future_references_cannot_resolve_into_physical_intake(snapshots):
    snapshot = await snapshots([row(release_date="9999-01-01")])
    connection = Connection([cache(snapshot)])
    key = snapshot.search(include_upcoming=True)["items"][0]["key"]
    assert await service.resolve(connection, key) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("sort,expected", [
    ("name", ["a1", "b2", "b1", "a2"]),
    ("name_desc", ["a2", "b1", "b2", "a1"]),
    ("number", ["b1", "a1", "b2", "a2"]),
    ("newest", ["b2", "a1", "b1", "a2"]),
    ("oldest", ["b1", "a1", "b2", "a2"]),
])
async def test_merge_sorts_globally_and_pages_after_all_source_filters(snapshots, sort, expected):
    first = await snapshots([
        row("a1", name="Alpha A", card_number="002", release_date="2020-01-01"),
        row("a2", name="Zulu", card_number="004", release_date=None)], provider="first")
    second = await snapshots([
        row("b1", name="Beta", card_number="001", release_date="2019-01-01"),
        row("b2", name="Alpha B", card_number="003", release_date="2021-01-01")], provider="second")
    # Reverse publication order to prove the source order does not define pages.
    connection = Connection([cache(second), cache(first)])
    result = await service.browse(connection, owner_id=OWNER_A, sort=sort, limit=2, offset=1)
    assert [r["provider_id"] for r in result["items"]] == expected[1:3]
    assert result["total_count"] == 4 and result["has_more"] is True
    assert result["price_sort_available"] is False


@pytest.mark.asyncio
async def test_name_desc_ties_keep_ascending_stable_keys_across_partitions(snapshots):
    first = await snapshots([row("a", name="Same Name")], provider="first")
    second = await snapshots([row("b", name="Same Name")], provider="second")
    connection = Connection([cache(first), cache(second)])
    result = await service.browse(connection, owner_id=OWNER_A, sort="name_desc")
    assert [r["key"] for r in result["items"]] == sorted(r["key"] for r in result["items"])


@pytest.mark.asyncio
async def test_first_page_does_not_materialize_all_matching_rows_in_memory(snapshots, monkeypatch):
    first = await snapshots([row(str(n), name=f"Card {n:04}") for n in range(0, 1000, 2)], provider="first")
    second = await snapshots([row(str(n), name=f"Card {n:04}") for n in range(1, 1000, 2)], provider="second")
    counts = []
    for snapshot in (first, second):
        original = snapshot.search

        def counted(*args, _original=original, **kwargs):
            page = _original(*args, **kwargs)
            counts.append(len(page["items"]))
            return page

        monkeypatch.setattr(snapshot, "search", counted)
    connection = Connection([cache(first), cache(second)])
    counts.clear()
    result = await service.browse(connection, owner_id=OWNER_A, limit=7, offset=3)
    assert [r["name"] for r in result["items"]] == [f"Card {n:04}" for n in range(3, 10)]
    assert result["total_count"] == 1000
    assert max(counts) <= 100 and sum(counts) <= 200


@pytest.mark.asyncio
async def test_owner_filters_and_overlays_never_mutate_shared_catalogue_cache(snapshots):
    snapshot = await snapshots([row("one", name="Alpha"), row("two", name="Beta")])
    connection = Connection([cache(snapshot)])
    before = snapshot.search()["items"]
    alpha, beta = before
    connection.owner_links[OWNER_A] = [owned_link(alpha["key"], quantity=3)]
    connection.owner_links[OWNER_B] = [owned_link(beta["key"], quantity=1)]
    for owner, wanted, count in ((OWNER_A, alpha, 3), (OWNER_B, beta, 1)):
        result = await service.browse(connection, owner_id=owner, owned="owned", limit=1)
        assert result["total_count"] == 1 and result["items"][0]["key"] == wanted["key"]
        assert result["items"][0]["owned_quantity"] == result["items"][0]["owned_count"] == count
    other = await service.browse(connection, owner_id=OWNER_A, owned="not_owned")
    assert [r["key"] for r in other["items"]] == [beta["key"]]
    assert snapshot.search()["items"] == before
    assert all("owner_id" not in r and "owned_count" not in r for r in before)


@pytest.mark.asyncio
async def test_saved_keys_query_and_owner_predicates_apply_before_total_and_pagination(snapshots):
    snapshot = await snapshots([row("a", name="Alpha"), row("b", name="Beta"), row("c", name="Gamma")])
    connection = Connection([cache(snapshot)])
    values = snapshot.search()["items"]
    alpha, beta, gamma = values
    connection.owner_links[OWNER_A] = [owned_link(beta["key"])]
    result = await service.browse(connection, owner_id=OWNER_A,
        keys=[alpha["key"], beta["key"]], q="a", owned="not_owned", limit=1)
    assert result["total_count"] == 1 and result["has_more"] is False
    assert result["items"][0]["key"] == alpha["key"]
    assert await service.browse(connection, owner_id=OWNER_A, keys=[]) == {
        "items": [], "has_more": False, "offset": 0, "total_count": 0}
    assert (await service.browse(connection, owner_id=OWNER_A, keys=["not-a-key"]))["items"] == []


@pytest.mark.asyncio
async def test_excessively_deep_pages_fail_before_any_catalogue_read():
    connection = Connection()
    with pytest.raises(HTTPException) as error:
        await service.browse(connection, owner_id=OWNER_A, offset=10001)
    assert error.value.status_code == 422 and connection.calls == []


@pytest.mark.asyncio
async def test_owned_key_overflow_requires_narrower_scope_not_silent_truncation():
    connection = Connection()
    connection.owner_links[OWNER_A] = [owned_link("x:" + "a" * 64)] * 10001
    with pytest.raises(HTTPException) as error:
        await service._owned_links(connection, OWNER_A, "YUGIOH")
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_set_summaries_use_only_the_requested_owners_live_inventory(snapshots):
    snapshot = await snapshots([row("a"), row("b", set_id="DEF", set_name="Other Set")])
    connection = Connection([cache(snapshot)])
    first_key = snapshot.search(set_id="ABC")["items"][0]["key"]
    connection.owner_links[OWNER_A] = [owned_link(first_key, quantity=2, value=600)]
    a = await service.sets(connection, owner_id=OWNER_A, system_code="YUGIOH", q="Fixture")
    b = await service.sets(connection, owner_id=OWNER_B, system_code="YUGIOH", q="Fixture")
    assert a["items"][0]["owned_count"] == 1 and a["items"][0]["owned_value_minor"] == 600
    assert b["items"][0]["owned_count"] == 0 and b["items"][0]["owned_value_minor"] is None


@pytest.mark.asyncio
async def test_all_unknown_owned_values_remain_null_not_a_fabricated_zero(snapshots):
    snapshot = await snapshots()
    connection = Connection([cache(snapshot)])
    key = snapshot.search()["items"][0]["key"]
    connection.owner_links[OWNER_A] = [owned_link(key, quantity=2, value=None)]
    result = await service.sets(connection, owner_id=OWNER_A, system_code="YUGIOH")
    assert result["items"][0]["owned_count"] == 1
    assert result["items"][0]["unknown_values"] == 2
    assert result["items"][0]["owned_value_minor"] is None


class CanonicalConnection:
    def __init__(self, digest, existing=None, insert_conflict=False):
        self.digest, self.existing, self.insert_conflict = digest, existing, insert_conflict
        self.calls = []
        self.catalogue = {"id": CATALOGUE_ID, "name": "Authoritative Card"}

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        assert "r2_first_catalogue_publications" in sql and "and active" in sql
        assert any("pg_advisory_xact_lock_shared" in statement for statement, _ in self.calls)
        return self.digest

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        assert "pg_advisory_xact_lock" in sql or "insert into tcg_private.r2_first_catalogue_links" in sql

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "join tcg.catalogue_products" in sql:
            return self.existing
        if "insert into tcg.catalogue_products" in sql:
            return None if self.insert_conflict else self.catalogue
        if "where identity_key=$1" in sql:
            return self.catalogue
        raise AssertionError("Unexpected SQL: " + sql)


@pytest.fixture
def authoritative(monkeypatch):
    current = service._view({**row(name="Authoritative Card"), "key": "x:" + "a" * 64}, "b" * 64)
    monkeypatch.setattr(service, "current_access_context", AsyncMock(return_value={"user_id": OWNER_A, "owner_id": OWNER_A}))
    monkeypatch.setattr(service, "resolve", AsyncMock(return_value=current))
    from app import catalogue_browser
    captured = []

    def reference_product(item):
        captured.append(deepcopy(item))
        return SimpleNamespace(product_type=item["product_type"], game=item["game"], name=item["name"],
            set_name=item["set_name"], card_number=item["card_number"], variant=item["provider_id"],
            rarity=item["rarity"], language=item["language"])

    monkeypatch.setattr(catalogue_browser, "reference_product", reference_product)
    return current, captured


@pytest.mark.asyncio
async def test_materialization_rechecks_source_and_ignores_forged_display_fields(authoritative):
    current, captured = authoritative
    connection = CanonicalConnection(current["source_manifest_sha256"])
    result = await service.materialize(connection, {**current, "name": "Forged Title", "language": "Japanese"})
    assert result["id"] == CATALOGUE_ID and captured == [current]
    inserts = [(sql, args) for sql, args in connection.calls if "insert into tcg.catalogue_products" in sql]
    assert len(inserts) == 1 and inserts[0][1][3] == "Authoritative Card"
    assert "identity_status" not in inserts[0][0] and "owner_id" not in inserts[0][0]
    link = [(sql, args) for sql, args in connection.calls if "insert into tcg_private.r2_first_catalogue_links" in sql]
    assert len(link) == 1 and link[0][1][-1] == OWNER_A
    assert all("inventory_items" not in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_repeated_materialization_reuses_exact_canonical_identity(authoritative):
    current, _ = authoritative
    existing = {"id": CATALOGUE_ID, "name": "Existing Card"}
    connection = CanonicalConnection(current["source_manifest_sha256"], existing=existing)
    assert await service.materialize(connection, current) == existing
    assert not any("insert into" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_concurrent_identity_insert_conflict_selects_the_same_existing_row(authoritative):
    current, _ = authoritative
    connection = CanonicalConnection(current["source_manifest_sha256"], insert_conflict=True)
    assert (await service.materialize(connection, current))["id"] == CATALOGUE_ID
    assert any("where identity_key=$1" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [("revoked", 404), ("stale", 409), ("approval_race", 409), ("unsupported", 422)])
async def test_materialization_revoked_stale_or_unreviewable_identity_never_inserts(authoritative, monkeypatch, failure, status):
    current, _ = authoritative
    item = deepcopy(current)
    connection = CanonicalConnection(current["source_manifest_sha256"])
    if failure == "revoked":
        monkeypatch.setattr(service, "resolve", AsyncMock(return_value=None))
    elif failure == "stale":
        item["source_manifest_sha256"] = "c" * 64
    elif failure == "approval_race":
        connection.digest = None
    elif failure == "unsupported":
        current["product_type"] = "FIGURE"
    with pytest.raises(HTTPException) as error:
        await service.materialize(connection, item)
    assert error.value.status_code == status
    assert not any("insert into" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_materialization_requires_active_membership_before_resolving_or_writing(authoritative, monkeypatch):
    current, _ = authoritative
    monkeypatch.setattr(service, "current_access_context", AsyncMock(side_effect=HTTPException(403, "Membership required")))
    connection = CanonicalConnection(current["source_manifest_sha256"])
    with pytest.raises(HTTPException) as error:
        await service.materialize(connection, current)
    assert error.value.status_code == 403 and connection.calls == []
    service.resolve.assert_not_awaited()
