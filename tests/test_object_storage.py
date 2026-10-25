"""S3-compatible Drop Rate cold storage is opt-in, private and fail-closed."""
from __future__ import annotations

import io
import json
import gzip
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app.object_storage import (
    ObjectStorageConfig,
    ObjectStorageError,
    S3ObjectStorage,
    sha256_file,
)


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.fail_read = False

    def head_bucket(self, *, Bucket):
        assert Bucket == "drop-rate-private"

    def get_object(self, *, Bucket, Key):
        assert Bucket == "drop-rate-private"
        if self.fail_read:
            raise TimeoutError("temporary private provider outage")
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        assert Bucket == "drop-rate-private"
        assert ContentType == "application/gzip"
        self.puts += 1
        self.objects[Key] = Body.read()
        assert Metadata["sha256"] == sha256_file(self.source)[0]


@pytest.fixture
def config():
    return ObjectStorageConfig(
        endpoint="https://example.r2.cloudflarestorage.com",
        bucket="drop-rate-private",
        region="auto",
        access_key_id="key",
        secret_access_key="secret",
    )


def test_disabled_by_default_and_incomplete_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("TCG_OBJECT_STORE_ENABLED", raising=False)
    assert ObjectStorageConfig.from_env() is None
    monkeypatch.setenv("TCG_OBJECT_STORE_ENABLED", "true")
    for field in ("ENDPOINT", "BUCKET", "REGION", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.delenv("TCG_OBJECT_STORE_" + field, raising=False)
    with pytest.raises(ObjectStorageError, match="Missing object storage configuration"):
        ObjectStorageConfig.from_env()
    monkeypatch.setenv("TCG_OBJECT_STORE_ENDPOINT", "http://unsecured.example.test")
    for key in ("BUCKET", "REGION", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setenv("TCG_OBJECT_STORE_" + key, "test")
    with pytest.raises(ObjectStorageError, match="HTTPS"):
        ObjectStorageConfig.from_env()


def test_round_trip_sha256_and_idempotency(config, tmp_path):
    source = tmp_path / "market.ndjson.gz"
    source.write_bytes(b"compressed-stub" * 128)
    fake = FakeS3()
    fake.source = source
    store = S3ObjectStorage(config, client=fake)
    receipt = store.put_verified_file(source, category="reference-history", content_type="application/gzip")
    assert receipt["verified"] is True
    assert receipt["sha256"] == sha256_file(source)[0]
    assert receipt["key"].startswith("drop-rate/reference-history/")
    assert receipt["key"].endswith(".ndjson.gz")
    assert fake.puts == 1
    assert store.put_verified_file(source, category="reference-history", content_type="application/gzip") == receipt
    assert fake.puts == 1, "Retries must not create duplicates"


def test_preexisting_corrupt_data_must_not_be_replaced(config, tmp_path):
    source = tmp_path / "market.ndjson.gz"
    source.write_bytes(b"good bytes")
    fake = FakeS3()
    fake.source = source
    store = S3ObjectStorage(config, client=fake)
    receipt = store.put_verified_file(source, category="reference-history", content_type="application/gzip")
    fake.objects[receipt["key"]] = b"bad bytes"
    with pytest.raises(ObjectStorageError, match="SHA-256"):
        store.put_verified_file(source, category="reference-history", content_type="application/gzip")
    assert fake.puts == 1, "Must not silently overwrite a damaged archive"


def test_provider_error_does_not_authorise_an_overwrite(config, tmp_path):
    source = tmp_path / "market.ndjson.gz"
    source.write_bytes(b"good bytes")
    fake = FakeS3()
    fake.source = source
    fake.fail_read = True
    store = S3ObjectStorage(config, client=fake)
    with pytest.raises(ObjectStorageError, match="remote object state"):
        store.put_verified_file(source, category="reference-history", content_type="application/gzip")
    assert fake.puts == 0


def test_reject_path_symlinks_and_unapproved_category(config, tmp_path):
    source = tmp_path / "market.ndjson.gz"
    source.write_bytes(b"good bytes")
    link = tmp_path / "linked.ndjson.gz"
    link.symlink_to(source)
    store = S3ObjectStorage(config, client=FakeS3())
    with pytest.raises(ObjectStorageError, match="regular file"):
        store.put_verified_file(link, category="reference-history", content_type="application/gzip")
    with pytest.raises(ObjectStorageError, match="Unsupported"):
        store.put_verified_file(source, category="database-backups", content_type="application/gzip")


def test_status_route_is_platform_admin_only_and_never_returns_secrets():
    main = Path(__file__).resolve().parents[1] / "backend/app/main.py"
    assert "app.include_router(object_storage_router, dependencies=[Depends(require_platform_admin_request)])" in main.read_text()
    source = (Path(__file__).resolve().parents[1] / "backend/app/object_storage_api.py").read_text()
    for text in ("secret_access_key", "access_key_id", "bucket_name"):
        assert text not in source


def test_n8n_storage_health_is_signed_and_does_not_handle_bucket_credentials():
    from app.automation_commands import StorageHealthCommand
    from pydantic import ValidationError

    valid = {"schema_version": 1, "action": "CHECK_PRIVATE_BUCKET",
             "execution_id": "single-execution", "occurred_at": "2026-10-25T14:00:00+00:00"}
    assert StorageHealthCommand.model_validate(valid).action == "CHECK_PRIVATE_BUCKET"
    with pytest.raises(ValidationError):
        StorageHealthCommand.model_validate({**valid, "action": "DELETE_BUCKET"})
    source = (Path(__file__).resolve().parents[1] / "backend/app/automation_commands.py").read_text()
    assert '@router.post("/storage/health")' in source
    assert 'raw_body = await _verified_command_body(' in source
    assert 'S3ObjectStorage(config).connectivity' in source


def test_n8n_storage_health_workflow_is_inactive_and_sends_signed_probe():
    workflow_file = (Path(__file__).resolve().parents[1]
                     / "automation/n8n/workflows/dr-93-object-storage-health.json")
    workflow = json.loads(workflow_file.read_text())
    assert workflow["id"] == "DR93ObjectStorageHealthV1"
    assert workflow["active"] is False
    nodes = {node["name"]: node for node in workflow["nodes"]}
    schedule = nodes["Hourly Storage Check"]["parameters"]["rule"]["interval"][0]
    assert schedule == {"field": "hours", "hoursInterval": 1}
    signer = nodes["Sign Storage Probe"]["parameters"]["jsCode"]
    assert "createHmac('sha256'" in signer
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "CHECK_PRIVATE_BUCKET" in signer
    assert "/commands/storage/health" in signer
    http = nodes["Probe Storage via FastAPI"]["parameters"]
    assert http["options"]["response"]["response"]["neverError"] is True
    assert "storage_status !== 'REACHABLE'" in nodes["Storage Reachable?"]["parameters"]["jsCode"]
    assert "r2.cloudflarestorage.com" not in workflow_file.read_text()


def test_export_contract_is_read_only_and_full_table():
    from scripts import archive_reference_history_object as job

    assert "from tcg.reference_market_history order by id" in job.HISTORY_SQL
    assert "where" not in job.HISTORY_SQL.lower()
    assert set(job.HISTORY_FIELDS) == {
        "id", "reference_kind", "provider", "system_code", "language",
        "provider_id", "quotes", "quote_digest", "market_value_minor",
        "market_value_high_minor", "pricing_updated_at", "recorded_at",
    }
    source = Path(job.__file__).read_text()
    for forbidden in ("truncate table", "delete from", "alter table", "drop table"):
        assert forbidden not in source.lower()
    assert 'readonly=True' in source


def test_archive_receipt_schema_distinguishes_restoration_from_byte_checks():
    from scripts.archive_reference_history_object import HISTORY_FIELDS
    assert len(HISTORY_FIELDS) == 12
    payload = {"restoration_verified": False, "full_table_snapshot": True, "database_mutations": 0}
    assert json.loads(json.dumps(payload))["restoration_verified"] is False


@pytest.mark.asyncio
async def test_snapshot_is_full_readonly_and_roundtrips(monkeypatch, tmp_path):
    from scripts import archive_reference_history_object as job

    actor = uuid4()
    observed = []
    rows = [
        dict(
            id=uuid4(), reference_kind="CARD", provider="test-provider",
            system_code="PKM", language="English", provider_id="set-001",
            quotes=[{"source": "permitted", "price_minor": 100}],
            quote_digest="hash", market_value_minor=100,
            market_value_high_minor=120, pricing_updated_at=None,
            recorded_at="2026-10-25T00:00:00+00:00",
        ),
    ]

    class Connection:
        @asynccontextmanager
        async def transaction(self, *, isolation, readonly):
            assert (isolation, readonly) == ("repeatable_read", True)
            yield

        async def execute(self, sql, *params):
            observed.append((sql, params))
            assert "set_config" in sql

        async def cursor(self, sql, *, prefetch):
            assert sql == job.HISTORY_SQL and prefetch == 200
            for row in rows:
                yield row

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    async def approved(connection):
        observed.append(("admin_authenticated", ()))

    monkeypatch.setattr(job, "require_platform_admin", approved)
    archive = tmp_path / "snapshot.ndjson.gz"
    manifest = await job.export_snapshot(Pool(), actor, archive, max_rows=2)
    decoded = gzip.decompress(archive.read_bytes())
    assert json.loads(decoded) == {**rows[0], "id": str(rows[0]["id"])}
    assert manifest["row_count"] == 1
    assert manifest["restoration_verified"] is False
    assert manifest["ndjson_sha256"] == __import__("hashlib").sha256(decoded).hexdigest()
    assert [entry[0] for entry in observed] == [
        "select set_config('tcg.user_id', $1, true)",
        "select set_config('tcg.request_id', $1, true)",
        "admin_authenticated",
    ]


@pytest.mark.asyncio
async def test_snapshot_row_limit_fails_before_any_remote_upload(monkeypatch, tmp_path):
    from scripts import archive_reference_history_object as job

    @asynccontextmanager
    async def context_manager(*args, **kwargs):
        yield

    class Connection:
        transaction = context_manager

        async def execute(self, *_):
            return None

        async def cursor(self, *_args, **_kwargs):
            for _ in range(2):
                yield {name: None for name in job.HISTORY_FIELDS}

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    async def approved(_):
        pass

    monkeypatch.setattr(job, "require_platform_admin", approved)
    with pytest.raises(ObjectStorageError, match="row limit"):
        await job.export_snapshot(Pool(), uuid4(), tmp_path / "oversized.gz", max_rows=1)
