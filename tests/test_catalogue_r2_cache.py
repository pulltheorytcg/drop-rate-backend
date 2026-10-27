"""Shared input caching stays bounded, exact and separate from account state."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import catalogue_browser as browser
from app import catalogue_r2_cache as cache
from app import db
from app.object_storage import ObjectStorageError


SCOPE = cache.ReferenceScope("TCGdex", "POKEMON_TCG", "English", "base1")


def payload(*, name="Bulbasaur", scope=SCOPE):
    common = {key: value for key, value in scope.as_dict().items() if key != "set_id"}
    card = {**common, "provider_id": "base1-1", "set_id": scope.set_id, "name": name,
            "card_number": "1/102", "rarity": "Rare", "image_url": None,
            "source_url": "https://api.tcgdex.net/v2/en/cards/base1-1"}
    reference_set = {**scope.as_dict(), "name": "Base Set", "release_date": "1999-01-09"}
    price = {**common, "provider_id": "base1-1", "market_value_minor": 100,
             "market_value_high_minor": 150, "pricing_updated_at": "2026-10-26T00:00:00+00:00",
             "quotes": [{"fx_rate_to_gbp": "exact-decimal-marker"}],
             "expires_at": "2026-10-27T00:00:00+00:00", "refresh_revision": 3}
    return json.dumps({"schema": cache.SCHEMA, "scope": scope.as_dict(), "r": [card],
                       "s": [reference_set], "m": [price], "b": []}, sort_keys=True).replace(
                           '"exact-decimal-marker"', "1.234567890123456789").encode()


def fingerprint(raw):
    return {"source_sha256": hashlib.sha256(raw).hexdigest(), "raw_size_bytes": len(raw),
            "card_count": 1, "set_count": 1, "payload": raw.decode()}


def snapshot(raw=None, scope=SCOPE):
    raw = raw or payload(scope=scope)
    return cache.parse_reference_snapshot(raw, scope, hashlib.sha256(raw).hexdigest(), len(raw))


class Connection:
    def __init__(self, raw=None):
        self.raw = raw or payload()
        self.fingerprints = 0
        self.fail_fingerprint = False
        self.aborted = False
        self.savepoints = 0
        self.executed = []

    @asynccontextmanager
    async def transaction(self, **options):
        self.savepoints += 1
        try:
            yield
        except Exception:
            self.aborted = False
            raise

    async def fetchrow(self, query, *args):
        assert query == cache.SNAPSHOT_SQL
        assert args[:4] == SCOPE.values() and args[4] == 1001
        self.fingerprints += 1
        if self.fail_fingerprint:
            self.aborted = True
            raise TimeoutError("fixture database timeout")
        return {**fingerprint(self.raw), "payload": self.raw.decode() if args[5] else None}

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Storage:
    config = SimpleNamespace(prefix="drop-rate")

    def __init__(self, raw=None):
        self.raw = raw or payload()
        self.reads = []
        self.writes = []

    def read_verified_reference_snapshot(self, digest):
        self.reads.append(digest)
        return self.raw

    def put_verified_reference_snapshot(self, raw):
        self.writes.append(raw)
        digest = hashlib.sha256(raw).hexdigest()
        return {"key": f"drop-rate/catalogue-reference-inputs/{digest}.json.gz",
                "sha256": digest, "size_bytes": 250, "compressed_sha256": "a" * 64, "verified": True}


@pytest.fixture(autouse=True)
def empty_verified_cache():
    cache.clear_reference_snapshot_cache()
    yield
    cache.clear_reference_snapshot_cache()


@pytest.mark.parametrize("changes", [
    {"provider": None}, {"provider": ""}, {"system_code": "NARUTO"}, {"system_code": "COMICS"},
    {"language": ""}, {"set_id": ""}, {"set_id": "x" * 201}, {"product_type": "SEALED"},
    {"system_code": "MANGA"}, {"system_code": "MARVEL_COMICS"}, {"system_code": "DC_COMICS"},
    {"system_code": "OTHER_COMICS"}, {"system_code": "UNCONFIGURED_SYSTEM"},
    {"product_type": "COMIC"}, {"owned": "owned"}, {"owned": "not_owned"}, {"sort": "value_desc"},
    {"sort": "value_asc"}, {"q": "Bulbasaur"}, {"q": " "}, {"keys": []}, {"keys": ["r:123"]},
    {"slab_number": "1"}, {"slab_name": "Bulbasaur"}, {"slab_set": "Base Set"},
])
def test_unsupported_browse_profiles_cannot_use_exact_set_cache(changes):
    assert cache.reference_scope(**{**SCOPE.as_dict(), **changes}) is None


@pytest.mark.parametrize("product_type", ["", "CARD"])
@pytest.mark.parametrize("sort", sorted(cache.NON_VALUE_SORTS))
def test_exact_card_and_default_set_views_are_eligible(product_type, sort):
    assert cache.reference_scope(**SCOPE.as_dict(), product_type=product_type, sort=sort) == SCOPE


def test_original_postgres_quote_text_is_bound_without_float_reserialization():
    value = snapshot()
    query, arguments = browser.product_query(owner_id=uuid4(), **SCOPE.as_dict(), reference_snapshot=value)
    assert value.payload in arguments and "1.234567890123456789" in value.payload
    assert "jsonb_to_recordset" in query
    assert "from r2_cache_r r join r2_cache_s s" in query
    assert "from tcg.reference_sealed_products r join tcg.reference_sets s" in query
    assert "left join tcg.reference_sealed_market_prices m" in query
    assert "m.pricing_updated_at>=now()-interval '7 days'" in query
    assert "m.expires_at<=now()" in query
    assert "m.match_status='VERIFIED'" in query and "m.rights_status='VERIFIED'" in query
    assert "i.owner_id=$1" in query and "reference_mirror.source_url=page.image_url" in query


@pytest.mark.parametrize("changes", [{"set_id": "other"}, {"q": "Bulbasaur"},
                                      {"owned": "owned"}, {"sort": "value_desc"}])
def test_query_builder_itself_rejects_out_of_scope_snapshot(changes):
    with pytest.raises(ValueError, match="does not cover"):
        browser.product_query(owner_id=uuid4(), **{**SCOPE.as_dict(), **changes}, reference_snapshot=snapshot())


@pytest.mark.parametrize("change", ["private_column", "wrong_scope", "different_set", "duplicate_card", "foreign_price"])
def test_closed_payload_schema_excludes_private_state_and_cross_set_prices(change):
    value = json.loads(payload())
    if change == "private_column":
        value["r"][0]["owned_quantity"] = 25
    elif change == "wrong_scope":
        value["scope"]["language"] = "Japanese"
    elif change == "different_set":
        value["r"][0]["set_id"] = "other"
    elif change == "duplicate_card":
        value["r"].append(value["r"][0])
    else:
        value["m"][0]["provider_id"] = "other-printing"
    raw = json.dumps(value).encode()
    with pytest.raises(ObjectStorageError, match="schema"):
        cache.parse_reference_snapshot(raw, SCOPE, hashlib.sha256(raw).hexdigest(), len(raw))


@pytest.mark.asyncio
async def test_every_hit_fingerprints_live_source_and_changed_content_cannot_reuse_old_cache():
    connection, storage = Connection(), Storage()
    first = await cache.read_reference_snapshot(connection, SCOPE, storage=storage)
    second = await cache.read_reference_snapshot(connection, SCOPE, storage=storage)
    assert first.origin == "R2" and second.origin == "PROCESS"
    assert connection.fingerprints == 2 and len(storage.reads) == 1 and not storage.writes
    connection.raw = payload(name="Changed name with identical price timestamps")
    # Storage still contains the earlier object: content-hash mismatch must fall back.
    assert await cache.read_reference_snapshot(connection, SCOPE, storage=storage) is None
    assert connection.fingerprints == 3 and len(storage.reads) == 2
    assert storage.reads[-1] != storage.reads[0]
    storage.raw = connection.raw
    assert (await cache.read_reference_snapshot(connection, SCOPE, storage=storage)).sha256 == storage.reads[-1]


@pytest.mark.asyncio
async def test_failed_fingerprint_rolls_back_savepoint_and_does_not_attempt_r2():
    connection, storage = Connection(), Storage()
    connection.fail_fingerprint = True
    assert await cache.read_reference_snapshot(connection, SCOPE, storage=storage) is None
    assert connection.savepoints == 1 and connection.aborted is False
    assert not storage.reads and not storage.writes


@pytest.mark.parametrize("field,value", [("card_count", 0), ("card_count", 1001),
                                       ("set_count", 0), ("raw_size_bytes", 4_000_001)])
@pytest.mark.asyncio
async def test_incomplete_or_oversized_live_source_falls_back_before_storage(field, value):
    connection, storage = Connection(), Storage()

    async def bounded_out(*args):
        return {**fingerprint(connection.raw), field: value}

    connection.fetchrow = bounded_out
    assert await cache.read_reference_snapshot(connection, SCOPE, storage=storage) is None
    assert storage.reads == []


@pytest.mark.asyncio
async def test_unavailable_storage_is_a_live_fallback_with_no_cache_write():
    storage = Storage()

    def unavailable(digest):
        raise ObjectStorageError("fixture object unavailable")

    storage.read_verified_reference_snapshot = unavailable
    assert await cache.read_reference_snapshot(Connection(), SCOPE, storage=storage) is None
    assert not storage.writes and not cache._verified_inputs


@pytest.mark.asyncio
async def test_timed_out_read_keeps_its_slot_until_the_thread_finishes(monkeypatch):
    slots = threading.BoundedSemaphore(2)
    release, both_started, both_finished = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    counts = {"started": 0, "finished": 0}
    storage = Storage()

    def slow_read(digest):
        with lock:
            counts["started"] += 1
            if counts["started"] == 2:
                both_started.set()
        try:
            assert release.wait(2), "Fixture must release the blocked reads"
            return storage.raw
        finally:
            with lock:
                counts["finished"] += 1
                if counts["finished"] == 2:
                    both_finished.set()

    storage.read_verified_reference_snapshot = slow_read
    monkeypatch.setattr(cache, "_read_slots", slots)
    monkeypatch.setattr(cache, "READ_TIMEOUT_SECONDS", 0.03)
    requests = [asyncio.create_task(cache.read_reference_snapshot(Connection(), SCOPE, storage=storage))
                for _ in range(2)]
    try:
        assert await asyncio.to_thread(both_started.wait, 1)
        assert await asyncio.gather(*requests) == [None, None]
        assert await cache.read_reference_snapshot(Connection(), SCOPE, storage=storage) is None
        assert counts["started"] == 2, "Timed-out reads must not release capacity prematurely"
    finally:
        release.set()
        await asyncio.gather(*requests, return_exceptions=True)
    assert await asyncio.to_thread(both_finished.wait, 1)
    for _ in range(100):
        if slots.acquire(blocking=False):
            slots.release()
            break
        await asyncio.sleep(0.001)
    result = await cache.read_reference_snapshot(Connection(), SCOPE, storage=storage)
    assert result is not None and counts["started"] == 3


def test_process_cache_enforces_both_byte_and_key_budgets(monkeypatch):
    monkeypatch.setattr(cache, "MAX_CACHE_KEYS", 2)
    monkeypatch.setattr(cache, "MAX_CACHE_BYTES", 7)
    cache._remember("first", b"123")
    cache._remember("second", b"456")
    cache._remember("third", b"78")
    assert list(cache._verified_inputs) == ["second", "third"]
    cache._remember("fourth", b"123456")
    assert list(cache._verified_inputs) == ["fourth"] and cache._verified_input_bytes == 6


@pytest.mark.asyncio
async def test_warmer_checks_existing_admin_and_releases_snapshot_before_storage(monkeypatch):
    connection, storage, actor = Connection(), Storage(), uuid4()
    lease = {"open": False, "admin_checked": False}
    other = cache.ReferenceScope("TCGdex", "POKEMON_TCG", "Japanese", "base1")

    async def scopes(query, cursor, maximum, systems):
        assert query == cache.WARM_SCOPES_SQL and cursor is None and maximum == 2
        assert systems == list(cache.CACHE_SYSTEMS)
        assert lease["admin_checked"]
        return [SCOPE.as_dict(), other.as_dict()]

    connection.fetch = scopes

    @asynccontextmanager
    async def normal_user_connection(pool, user_id, request_id, **options):
        assert user_id == actor and options == {"readonly_snapshot": True}
        lease["open"] = True
        yield connection
        lease["open"] = False

    async def admin_check(current):
        assert current is connection and lease["open"]
        lease["admin_checked"] = True

    original_put = storage.put_verified_reference_snapshot

    def put(raw):
        assert not lease["open"]
        return original_put(raw)

    monkeypatch.setattr(cache, "user_connection", normal_user_connection)
    monkeypatch.setattr(cache, "require_platform_admin", admin_check)
    storage.put_verified_reference_snapshot = put
    report = await cache.warm_reference_snapshots(object(), actor, limit=1, storage=storage)
    assert report["verified"] == 1 and report["failed"] == report["database_writes"] == 0
    assert report["next_cursor"] == list(SCOPE.values()) and report["has_more"] is True
    assert len(storage.writes) == 1 and not connection.executed


@pytest.mark.asyncio
async def test_warmer_cannot_write_for_an_unauthorized_actor(monkeypatch):
    connection, storage = Connection(), Storage()

    @asynccontextmanager
    async def normal_user_connection(*args, **kwargs):
        yield connection

    async def denied(current):
        raise PermissionError("Actor is not a platform administrator")

    monkeypatch.setattr(cache, "user_connection", normal_user_connection)
    monkeypatch.setattr(cache, "require_platform_admin", denied)
    with pytest.raises(PermissionError):
        await cache.warm_reference_snapshots(object(), uuid4(), storage=storage)
    assert not storage.writes and connection.fingerprints == 0


@pytest.mark.asyncio
async def test_rejected_directory_row_is_skipped_and_its_raw_cursor_can_resume(monkeypatch):
    connection, storage = Connection(), Storage()
    rejected = {**SCOPE.as_dict(), "provider": "\u00a0"}
    rejected_cursor = [rejected[field] for field in cache.SCOPE_FIELDS]
    cursors = []

    async def scopes(query, cursor, maximum, systems):
        cursors.append(cursor)
        return [rejected, SCOPE.as_dict()] if cursor is None else [SCOPE.as_dict()]

    connection.fetch = scopes

    @asynccontextmanager
    async def normal_connection(*args, **kwargs):
        yield connection

    async def admin_check(current):
        pass

    monkeypatch.setattr(cache, "user_connection", normal_connection)
    monkeypatch.setattr(cache, "require_platform_admin", admin_check)
    first = await cache.warm_reference_snapshots(object(), uuid4(), limit=1, storage=storage)
    assert first["examined"] == first["skipped"] == 1 and first["verified"] == first["failed"] == 0
    assert first["next_cursor"] == rejected_cursor and first["has_more"] is True
    second = await cache.warm_reference_snapshots(object(), uuid4(), cursor=first["next_cursor"], limit=1, storage=storage)
    assert second["verified"] == 1 and second["next_cursor"] is None
    assert cursors == [None, rejected_cursor] and len(storage.writes) == 1


@pytest.mark.parametrize("field,value", [("sha256", "f" * 64), ("key", "drop-rate/private-media/other.webp"),
                                       ("compressed_sha256", None), ("size_bytes", 2_000_001)])
@pytest.mark.asyncio
async def test_warmer_does_not_cache_or_count_unbound_storage_receipts(monkeypatch, field, value):
    connection, storage = Connection(), Storage()

    async def scopes(*args):
        return [SCOPE.as_dict()]

    connection.fetch = scopes

    @asynccontextmanager
    async def normal_connection(*args, **kwargs):
        yield connection

    async def admin_check(current):
        pass

    original_put = storage.put_verified_reference_snapshot

    def bad_receipt(raw):
        return {**original_put(raw), field: value}

    monkeypatch.setattr(cache, "user_connection", normal_connection)
    monkeypatch.setattr(cache, "require_platform_admin", admin_check)
    storage.put_verified_reference_snapshot = bad_receipt
    report = await cache.warm_reference_snapshots(object(), uuid4(), storage=storage)
    assert report["failed"] == 1 and report["verified"] == 0 and not report["receipts"]
    assert not cache._verified_inputs


@pytest.mark.parametrize("changed,mismatch", [(False, False), (False, True), (True, False)])
@pytest.mark.asyncio
async def test_real_object_parity_probe_is_bounded_authorized_and_reports_no_private_rows(monkeypatch, changed, mismatch):
    actor, owner, storage = uuid4(), uuid4(), Storage()
    connection = Connection(payload(name="Changed after warm") if changed else None)
    queries = []

    @asynccontextmanager
    async def normal_connection(pool, user_id, request_id, **options):
        assert user_id == actor and options == {"readonly_snapshot": True}
        yield connection

    async def admin_check(current):
        assert current is connection
        return {"owner_id": owner}

    async def fetch(query, *args):
        queries.append(query)
        assert args[0] == owner and args[-2:] == (20, 0)
        return [{"private_fixture": "owner material must never enter receipts", "owned_quantity":
                 739 if mismatch and "r2_cache_r" in query else 738}]

    connection.fetch = fetch
    monkeypatch.setattr(cache, "user_connection", normal_connection)
    monkeypatch.setattr(cache, "require_platform_admin", admin_check)
    # An already warm process cache must not substitute for an actual R2 GET.
    cache._remember(snapshot().sha256, payload())
    result = await cache.verify_warmed_reference_snapshot(object(), actor, snapshot(), storage=storage)
    assert set(result) == {"status", "compared_rows", "equal", "database_elapsed_ms", "cache_elapsed_ms", "source_changed"}
    if changed:
        assert result["status"] == "SOURCE_CHANGED" and result["equal"] is None
        assert result["source_changed"] is True and not queries and not storage.reads
    else:
        assert result["status"] == ("MISMATCH" if mismatch else "MATCH")
        assert result["equal"] is (not mismatch) and result["compared_rows"] == 1
        assert result["database_elapsed_ms"] >= 0 and result["cache_elapsed_ms"] >= 0
        assert len(queries) == 2 and storage.reads == [snapshot().sha256]
    serialized = json.dumps(result)
    assert str(owner) not in serialized and str(actor) not in serialized
    assert "owned_quantity" not in serialized and "private_fixture" not in serialized
    assert "owner material" not in serialized


@pytest.mark.asyncio
async def test_parity_probe_requires_admin_before_reading_r2(monkeypatch):
    connection, storage = Connection(), Storage()

    @asynccontextmanager
    async def normal_connection(*args, **options):
        yield connection

    async def denied(current):
        raise PermissionError("not an administrator")

    monkeypatch.setattr(cache, "user_connection", normal_connection)
    monkeypatch.setattr(cache, "require_platform_admin", denied)
    result = await cache.verify_warmed_reference_snapshot(object(), uuid4(), snapshot(), storage=storage)
    assert result["status"] == "FAILED" and result["equal"] is False
    assert not storage.reads and connection.fingerprints == 0


@pytest.mark.parametrize("verify", [False, True])
@pytest.mark.asyncio
async def test_warmer_probes_only_first_successful_scope_when_explicitly_enabled(monkeypatch, verify):
    connection, storage, checked = Connection(), Storage(), []
    other = cache.ReferenceScope("TCGdex", "POKEMON_TCG", "Japanese", "base1")

    async def scopes(*args):
        return [SCOPE.as_dict(), other.as_dict()]

    async def source(query, *args):
        return fingerprint(payload(scope=cache.ReferenceScope(*args[:4])))

    connection.fetch, connection.fetchrow = scopes, source

    @asynccontextmanager
    async def normal_connection(*args, **kwargs):
        yield connection

    async def admin_check(current):
        return {"owner_id": uuid4()}

    async def probe(pool, actor, item, *, storage):
        checked.append(item.scope)
        return {"status": "MATCH", "equal": True, "compared_rows": 1,
                "database_elapsed_ms": 1, "cache_elapsed_ms": 1, "source_changed": False}

    monkeypatch.setattr(cache, "user_connection", normal_connection)
    monkeypatch.setattr(cache, "require_platform_admin", admin_check)
    monkeypatch.setattr(cache, "verify_warmed_reference_snapshot", probe)
    report = await cache.warm_reference_snapshots(object(), uuid4(), storage=storage,
                                                 verify_query_parity=verify)
    assert report["verified"] == 2 and report["failed"] == 0
    assert checked == ([SCOPE] if verify else [])
    assert ("query_parity" in report) is verify


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.asyncio
async def test_user_snapshot_context_preserves_normal_actor_and_request_settings(readonly):
    connection, actor, options = Connection(), uuid4(), []
    original = connection.transaction

    def transaction(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    connection.transaction = transaction

    @asynccontextmanager
    async def acquire():
        yield connection

    async with db.user_connection(SimpleNamespace(acquire=acquire), actor, "cache-test",
                                  readonly_snapshot=readonly) as current:
        assert current is connection
    assert options == ([{"isolation": "repeatable_read", "readonly": True}] if readonly else [{}])
    assert connection.executed == [
        ("select set_config('tcg.user_id', $1, true)", (str(actor),)),
        ("select set_config('tcg.request_id', $1, true)", ("cache-test",)),
    ]


@pytest.mark.asyncio
async def test_route_cache_sql_failure_uses_original_query_and_same_authenticated_snapshot(monkeypatch):
    actor, owner, queries, options = uuid4(), uuid4(), [], []
    connection = Connection()

    async def fetch(query, *args):
        queries.append(query)
        assert args[0] == owner
        if "r2_cache_r" in query:
            raise ValueError("fixture typed cache failure")
        return []

    connection.fetch = fetch

    @asynccontextmanager
    async def normal_connection(pool, user_id, request_id, **kwargs):
        assert user_id == actor
        options.append(kwargs)
        yield connection

    async def cached(current, scope):
        assert current is connection and scope == SCOPE
        return snapshot()

    async def no_shared(*args, **kwargs):
        return {}

    async def unchanged(current, rows):
        return rows

    monkeypatch.setenv("TCG_R2_CATALOGUE_CACHE_DELIVERY_ENABLED", "true")
    monkeypatch.setattr(browser, "user_connection", normal_connection)
    monkeypatch.setattr(browser, "read_reference_snapshot", cached)
    monkeypatch.setattr(browser, "read_shared_prices", no_shared)
    monkeypatch.setattr(browser, "add_reference_history", unchanged)
    monkeypatch.setattr(browser, "with_book_details", unchanged)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id="cache-route-test"))
    result = await browser.products(request, SimpleNamespace(user_id=actor), {"owner_id": owner},
        q="", **SCOPE.as_dict(), product_type="", owned="all", sort="newest", keys=None,
        slab_number="", slab_name="", slab_set="", limit=40, offset=0)
    assert result["items"] == [] and len(queries) == 2
    assert "r2_cache_r" in queries[0] and "tcg.reference_cards" in queries[1]
    assert options == [{"readonly_snapshot": True}] and connection.aborted is False
