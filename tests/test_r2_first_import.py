"""Worker/publication unit tests: local bytes and fake SQL, never production I/O.

Database-native grants, RLS and audit-trigger tests live in the separate SQL
integration suite. These tests check worker ordering, failure isolation and CAS.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import HTTPException
import pytest
import pytest_asyncio

from app import r2_first_catalogue as codec
from app import r2_first_import as worker
from app.r2_first_sources import FetchedSource, SourceError, SourcePermissionError, source_descriptor


ACTOR = UUID("11111111-1111-4111-8111-111111111111")


def record(provider_id="one", **changes):
    value = {"provider": "ygoprodeck", "system_code": "YUGIOH", "language": "English",
        "provider_id": provider_id, "product_type": "CARD", "name": "Fixture Card",
        "set_id": "ABC", "set_name": "Fixture Set", "card_number": "ABC-EN001",
        "rarity": "Rare", "finish": None, "release_date": None,
        "source_url": source_descriptor("ygoprodeck").source_url}
    value.update(changes)
    return value


def bundle(rows=None, revision="fixture:one", **changes):
    descriptor = source_descriptor("ygoprodeck")
    args = {"provider": descriptor.provider, "system_code": descriptor.system_code,
        "language": "English", "source_url": descriptor.source_url,
        "source_revision": revision, "permission_ref": descriptor.permission_ref}
    args.update(changes)
    return codec.prepare_catalogue(rows if rows is not None else [record()], **args)


def publication(snapshot, generation=1, active=True, age_days=3):
    manifest = snapshot.manifest
    return {**{k: manifest[k] for k in ("provider", "system_code", "language", "source_url",
        "source_revision", "permission_ref", "record_count")},
        "manifest_sha256": snapshot.manifest_digest, "set_count": len(snapshot.sets()),
        "released_record_count": snapshot.search(limit=1)["total"], "raw_bytes": manifest["raw_bytes"],
        "generation": generation, "active": active, "published_by": ACTOR,
        "published_at": datetime.now(timezone.utc) - timedelta(days=age_days)}


class LocalObjects:
    def __init__(self, database=None):
        self.objects, self.puts, self.reads = {}, [], []
        self.database = database
        self.fail_write_number = None
        self.fail_read_number = None

    def _outside_transaction(self):
        if self.database is not None:
            assert not self.database.in_transaction, "Object I/O held a SQL transaction"

    def put_verified_reference_snapshot(self, raw):
        self._outside_transaction()
        digest = hashlib.sha256(raw).hexdigest()
        self.puts.append(digest)
        if len(self.puts) == self.fail_write_number:
            raise OSError("synthetic upload failure")
        self.objects[digest] = raw
        return {"sha256": digest, "verified": True}

    def read_verified_reference_snapshot(self, digest):
        self._outside_transaction()
        self.reads.append(digest)
        if len(self.reads) == self.fail_read_number:
            raise OSError("synthetic readback failure")
        return self.objects[digest]


class Database:
    def __init__(self):
        self.old = None
        self.statements = []
        self.in_transaction = False
        self.writable = self.admin = True
        self.capacity = 0
        self.other_bytes = 0
        self.fail_publication = False
        self.transactions = []

    async def fetchval(self, sql, *args):
        self.statements.append((sql, args))
        if sql == worker.DATABASE_WRITE_READY_SQL:
            return self.writable
        if "count(*)" in sql:
            return self.capacity
        if "sum(raw_bytes)" in sql:
            return self.other_bytes
        raise AssertionError("Unexpected fetchval: " + sql)

    async def fetchrow(self, sql, *args):
        self.statements.append((sql, args))
        assert "r2_first_catalogue_publications" in sql
        return deepcopy(self.old)

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        if "pg_advisory" in sql:
            return "SELECT 1"
        if "insert into tcg_private.r2_first_catalogue_publications" in sql or "update tcg_private.r2_first_catalogue_publications" in sql:
            self.old = dict(zip(("provider", "system_code", "language", "manifest_sha256",
                "source_revision", "permission_ref", "source_url", "record_count", "set_count",
                "generation", "active", "published_by", "released_record_count", "raw_bytes"), args, strict=True))
            self.old["published_at"] = datetime.now(timezone.utc)
            if self.fail_publication:
                raise RuntimeError("synthetic transaction failure")
            return "INSERT 1"
        raise AssertionError("Unexpected execute: " + sql)


@pytest.fixture
def database(monkeypatch):
    db = Database()

    @asynccontextmanager
    async def connection(pool, actor, operation, **kwargs):
        assert actor == ACTOR
        assert not db.in_transaction
        db.transactions.append(operation)
        backup = deepcopy(db.old)
        db.in_transaction = True
        try:
            yield db
        except BaseException:
            db.old = backup
            raise
        finally:
            db.in_transaction = False

    async def require_admin(connection):
        assert connection is db
        if not db.admin:
            raise HTTPException(403, "Admin required")

    monkeypatch.setattr(worker, "user_connection", connection)
    monkeypatch.setattr(worker, "require_platform_admin", require_admin)
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", "ygoprodeck")
    return db


@pytest_asyncio.fixture
async def snapshot_factory():
    snapshots = []

    async def make(**kwargs):
        prepared = bundle(**kwargs)
        store = LocalObjects()
        manifest = await codec.upload_and_verify(prepared, store)
        snapshot = await codec.load_catalogue(manifest, store)
        snapshots.append(snapshot)
        return snapshot

    yield make
    for snapshot in snapshots:
        snapshot.close()


def test_import_sources_default_off_and_duplicate_names_do_not_duplicate_jobs(monkeypatch):
    monkeypatch.delenv("TCG_R2_FIRST_IMPORT_SOURCES", raising=False)
    assert worker.configured_sources() == ()
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", " ygoprodeck,ygoprodeck, ")
    assert worker.configured_sources() == ("ygoprodeck",)


@pytest.mark.parametrize("names", ["lorcanajson", "scryfall", "riftcodex", "ygoprodeck,unknown"])
def test_unreviewed_import_sources_cannot_be_enabled_by_configuration(monkeypatch, names):
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", names)
    with pytest.raises(SourcePermissionError):
        worker.configured_sources()


@pytest.mark.asyncio
async def test_publication_is_a_small_cas_write_and_retries_are_idempotent(database, snapshot_factory):
    snapshot = await snapshot_factory()
    first = await worker.publish_verified(None, ACTOR, snapshot)
    assert first["status"] == "PUBLISHED" and first["generation"] == 1
    assert database.old["manifest_sha256"] == snapshot.manifest_digest
    second = await worker.publish_verified(None, ACTOR, snapshot, expected_generation=0)
    assert second["status"] == "CURRENT" and second["generation"] == 1
    writes = [sql for sql, _ in database.statements if "insert into" in sql or "update tcg_private" in sql]
    assert len(writes) == 1
    assert all("reference_cards" not in sql and "market_observations" not in sql for sql, _ in database.statements)


@pytest.mark.asyncio
async def test_cas_conflict_does_not_overwrite_another_generation(database, snapshot_factory):
    old, new = await snapshot_factory(), await snapshot_factory(revision="fixture:new")
    database.old = publication(old, generation=5)
    before = deepcopy(database.old)
    with pytest.raises(HTTPException) as error:
        await worker.publish_verified(None, ACTOR, new, expected_generation=4)
    assert error.value.status_code == 409 and database.old == before


@pytest.mark.asyncio
async def test_same_manifest_refreshes_release_counts_with_a_new_audited_generation(database, snapshot_factory):
    snapshot = await snapshot_factory()
    database.old = publication(snapshot, generation=5)
    # A previously upcoming row becomes released without changing the source bytes.
    database.old["released_record_count"] = 0
    database.old["set_count"] = 0
    result = await worker.publish_verified(None, ACTOR, snapshot, expected_generation=5)
    assert result["status"] == "PUBLISHED" and result["generation"] == 6
    assert database.old["manifest_sha256"] == snapshot.manifest_digest
    assert database.old["released_record_count"] == 1 and database.old["set_count"] == 1
    retry = await worker.publish_verified(None, ACTOR, snapshot, expected_generation=5)
    assert retry["status"] == "CURRENT" and retry["generation"] == 6


@pytest.mark.asyncio
async def test_explicit_verified_rollback_advances_generation_and_retains_old_bytes(database, snapshot_factory):
    previous = await snapshot_factory(revision="fixture:previous")
    latest = await snapshot_factory(revision="fixture:latest")
    database.old = publication(latest, generation=7)
    result = await worker.publish_verified(None, ACTOR, previous, expected_generation=7)
    assert result["status"] == "PUBLISHED" and result["generation"] == 8
    assert database.old["manifest_sha256"] == previous.manifest_digest
    assert latest.search()["total"] == previous.search()["total"] == 1


@pytest.mark.asyncio
async def test_deactivation_is_auditable_cas_not_deletion(database, snapshot_factory):
    snapshot = await snapshot_factory()
    database.old = publication(snapshot, generation=3)
    result = await worker.publish_verified(None, ACTOR, snapshot, expected_generation=3, active=False)
    assert result["status"] == "DEACTIVATED" and result["generation"] == 4
    assert database.old["active"] is False
    assert database.old["manifest_sha256"] == snapshot.manifest_digest


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration,status", [("writable", 503), ("admin", 403)])
async def test_publication_requires_writable_database_and_admin(database, snapshot_factory, configuration, status):
    snapshot = await snapshot_factory()
    setattr(database, configuration, False)
    with pytest.raises(HTTPException) as error:
        await worker.publish_verified(None, ACTOR, snapshot)
    assert error.value.status_code == status and database.old is None


@pytest.mark.asyncio
async def test_registry_permission_mismatch_is_rejected_before_sql(database, snapshot_factory):
    snapshot = await snapshot_factory(permission_ref="https://unreviewed.example.com/permission")
    with pytest.raises(SourcePermissionError):
        await worker.publish_verified(None, ACTOR, snapshot)
    assert database.statements == [] and database.old is None


@pytest.mark.asyncio
async def test_publication_transaction_error_keeps_old_pointer(database, snapshot_factory):
    old, new = await snapshot_factory(), await snapshot_factory(revision="fixture:new")
    database.old = publication(old, generation=2)
    before = deepcopy(database.old)
    database.fail_publication = True
    with pytest.raises(RuntimeError):
        await worker.publish_verified(None, ACTOR, new, expected_generation=2)
    assert database.old == before


@pytest.mark.asyncio
async def test_partition_capacity_is_checked_before_first_insert(database, snapshot_factory):
    snapshot = await snapshot_factory()
    database.capacity = worker.service.MAX_PARTITIONS
    with pytest.raises(HTTPException) as error:
        await worker.publish_verified(None, ACTOR, snapshot)
    assert error.value.status_code == 409 and database.old is None


@pytest.mark.asyncio
async def test_aggregate_byte_budget_is_checked_under_global_publication_lock(database, snapshot_factory):
    snapshot = await snapshot_factory()
    database.other_bytes = worker.service.MAX_ACTIVE_RAW_BYTES
    with pytest.raises(HTTPException) as error:
        await worker.publish_verified(None, ACTOR, snapshot)
    assert error.value.status_code == 409 and database.old is None
    statements = [sql for sql, _ in database.statements]
    assert any("pg_advisory_xact_lock(847220122)" in sql for sql in statements)


def fetched(rows=None):
    descriptor = source_descriptor("ygoprodeck")
    return FetchedSource(descriptor.provider, descriptor.system_code, descriptor.source_url,
        "sha256:" + "a" * 64, "a" * 64, rows if rows is not None else [record()])


@pytest.mark.asyncio
async def test_import_downloads_and_verifies_all_bytes_outside_sql_before_publication(database, monkeypatch):
    async def fetch(*args, **kwargs):
        assert not database.in_transaction
        assert database.old is None
        assert kwargs["approved_sources"] == worker.APPROVED_METADATA_SOURCES
        return fetched()

    monkeypatch.setattr(worker, "fetch_source", fetch)
    store = LocalObjects(database)
    result = await worker.import_source(None, ACTOR, "ygoprodeck", object_store=store, client=object())
    assert result["status"] == "PUBLISHED" and result["record_count"] == 1
    assert result["sql_bulk_rows_written"] == 0 and result["metadata_only"] is True
    assert len(store.puts) == 2 and len(store.reads) >= 3
    assert database.transactions == ["r2-first-import-preflight", "r2-first-publication"]
    assert database.old["manifest_sha256"] == store.puts[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status", [("disabled", "DISABLED"), ("fresh", "CURRENT")])
async def test_disabled_or_recent_source_is_not_refetched(database, snapshot_factory, monkeypatch, case, status):
    snapshot = await snapshot_factory()
    database.old = publication(snapshot, active=case != "disabled", age_days=0)
    fetch = AsyncMock(side_effect=AssertionError("Must not fetch"))
    monkeypatch.setattr(worker, "fetch_source", fetch)
    result = await worker.import_source(None, ACTOR, "ygoprodeck", object_store=LocalObjects(), client=object())
    assert result["status"] == status
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_source_disabled_configuration_prevents_even_sql_preflight(database, monkeypatch):
    monkeypatch.delenv("TCG_R2_FIRST_IMPORT_SOURCES", raising=False)
    with pytest.raises(SourcePermissionError):
        await worker.import_source(None, ACTOR, "ygoprodeck", client=object())
    assert database.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration,status", [("writable", 503), ("admin", 403)])
async def test_import_preflight_refusal_never_starts_provider_or_r2_io(database, monkeypatch, configuration, status):
    setattr(database, configuration, False)
    fetch = AsyncMock(side_effect=AssertionError("Preflight refusal must not fetch"))
    monkeypatch.setattr(worker, "fetch_source", fetch)
    store = LocalObjects(database)
    with pytest.raises(HTTPException) as error:
        await worker.import_source(None, ACTOR, "ygoprodeck", object_store=store, client=object())
    assert error.value.status_code == status and database.old is None
    assert store.puts == store.reads == []
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_generation_change_during_download_keeps_winning_pointer_and_closes_local_snapshot(database, snapshot_factory, monkeypatch):
    old, winning = await snapshot_factory(), await snapshot_factory(revision="winning-generation")
    database.old = publication(old, generation=5)
    winner = publication(winning, generation=6)

    async def fetch(*args, **kwargs):
        assert not database.in_transaction
        database.old = deepcopy(winner)
        return fetched()

    monkeypatch.setattr(worker, "fetch_source", fetch)
    original_load = codec.load_catalogue
    opened = []

    async def capture_load(*args, **kwargs):
        snapshot = await original_load(*args, **kwargs)
        opened.append(snapshot)
        return snapshot

    monkeypatch.setattr(worker.codec, "load_catalogue", capture_load)
    with pytest.raises(HTTPException) as error:
        await worker.import_source(None, ACTOR, "ygoprodeck", object_store=LocalObjects(database), client=object())
    assert error.value.status_code == 409 and database.old == winner
    assert len(opened) == 1
    with pytest.raises(codec.R2FirstCatalogueError, match="unavailable"):
        opened[0].search()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fetch", "empty", "malformed", "partial_put", "readback", "cold_reconstruction"])
async def test_failed_or_empty_import_never_replaces_previous_generation(database, snapshot_factory, monkeypatch, failure):
    snapshot = await snapshot_factory()
    database.old = publication(snapshot, generation=5)
    before = deepcopy(database.old)
    store = LocalObjects(database)
    response = fetched()
    if failure == "empty":
        response = fetched([])
    elif failure == "malformed":
        response = fetched([{**record(), "image_url": "https://private.example.com/not-permitted"}])
    fetch = AsyncMock(return_value=response)
    if failure == "fetch":
        fetch.side_effect = SourceError("Synthetic provider failure")
    monkeypatch.setattr(worker, "fetch_source", fetch)
    if failure == "partial_put":
        store.fail_write_number = 2
    elif failure == "readback":
        store.fail_read_number = 1
    elif failure == "cold_reconstruction":
        monkeypatch.setattr(worker.codec, "load_catalogue", AsyncMock(side_effect=codec.R2FirstCatalogueError("Cold verification failed")))
    with pytest.raises((SourceError, codec.R2FirstCatalogueError)):
        await worker.import_source(None, ACTOR, "ygoprodeck", object_store=store, client=object())
    assert database.old == before
    assert database.transactions == ["r2-first-import-preflight"]
    if failure in {"empty", "malformed", "fetch"}:
        assert store.puts == []


class LockConnection:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.operations = []

    async def fetchval(self, sql):
        self.operations.append(sql)
        assert "pg_try_advisory_lock" in sql
        return self.acquired

    async def execute(self, sql):
        self.operations.append(sql)
        assert "pg_advisory_unlock" in sql


def pool_for(lock):
    @asynccontextmanager
    async def acquire():
        yield lock
    return SimpleNamespace(acquire=acquire)


@pytest.mark.asyncio
async def test_overlap_lock_skips_import_instead_of_duplicating_provider_requests(monkeypatch):
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", "ygoprodeck")
    importer = AsyncMock()
    monkeypatch.setattr(worker, "import_source", importer)
    lock = LockConnection(acquired=False)
    assert await worker.run_once(pool_for(lock), ACTOR) == [{"status": "ALREADY_RUNNING"}]
    importer.assert_not_called()
    assert len(lock.operations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_worker_session_lock_is_released_after_success_or_failure(monkeypatch, failure):
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", "ygoprodeck")
    importer = AsyncMock(return_value={"status": "PUBLISHED"})
    if failure:
        importer.side_effect = SourceError("Synthetic provider failure")
    monkeypatch.setattr(worker, "import_source", importer)
    lock, pool = LockConnection(), None
    pool = pool_for(lock)
    if failure:
        with pytest.raises(SourceError):
            await worker.run_once(pool, str(ACTOR))
    else:
        assert await worker.run_once(pool, str(ACTOR)) == [{"status": "PUBLISHED"}]
    importer.assert_awaited_once_with(pool, ACTOR, "ygoprodeck")
    assert len(lock.operations) == 2 and "pg_advisory_unlock" in lock.operations[-1]


@pytest.mark.asyncio
async def test_worker_default_off_does_not_acquire_database_or_download(monkeypatch):
    monkeypatch.delenv("TCG_R2_FIRST_IMPORT_SOURCES", raising=False)
    assert await worker.run_once(None, ACTOR) == []
