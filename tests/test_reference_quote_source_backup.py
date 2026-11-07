"""Live price quote evidence must be restorable before considering physical offload."""

from contextlib import asynccontextmanager
import gzip
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app import reference_quote_source_backup as backup
from app.object_storage import ObjectStorageError


def row(name="reference_market_prices", **changes):
    value = {
        "provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "Japanese",
        "provider_id": "sample-001", "quotes": [{"source": "test", "price": 9007199254740993}],
        "market_value_minor": 101, "market_value_high_minor": 151,
        "pricing_updated_at": "2026-11-02T09:01:00+00:00",
        "checked_at": "2026-11-02T09:01:00+00:00",
        "expires_at": "2026-11-03T09:01:00+00:00",
    }
    if name == "reference_market_prices":
        value["refresh_revision"] = 3
    value.update(changes)
    assert tuple(value) == backup.TABLE_FIELDS[name]
    return value


def line(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.mark.parametrize("name", backup.TABLE_FIELDS)
def test_price_rows_require_exact_shape_and_preserve_large_json_integers(name):
    expected = ("TCGdex", "POKEMON_TCG", "Japanese", "sample-001")
    assert backup.validate_row(line(row(name)), name) == expected
    assert json.loads(line(row(name)))["quotes"][0]["price"] == 9007199254740993
    with pytest.raises(ValueError):
        backup.validate_row(line(row(name)), "not-a-real-table")


@pytest.mark.parametrize("change", [
    lambda r: r.pop("quotes"),
    lambda r: r.update(extra_field=True),
    lambda r: r.update(provider=""),
    lambda r: r.update(quotes={"not": "array"}),
    lambda r: r.update(quotes=[5]),
    lambda r: r.update(quotes=[{}] * 41),
    lambda r: r.update(market_value_minor=True),
    lambda r: r.update(market_value_high_minor=-5),
    lambda r: r.update(market_value_high_minor=10),
    lambda r: r.update(checked_at="2026-11-02"),
    lambda r: r.update(expires_at="2026-11-01T09:01:00+00:00"),
    lambda r: r.update(pricing_updated_at=None),
])
def test_invalid_quote_provenance_rejected(change):
    value = row()
    change(value)
    with pytest.raises(ObjectStorageError):
        backup.validate_row(line(value), "reference_market_prices")


def test_invalid_refresh_revision_and_json_constants_rejected():
    with pytest.raises(ObjectStorageError):
        backup.validate_row(line(row(refresh_revision=-1)), "reference_market_prices")
    sample = line(row()).decode("utf-8")
    with pytest.raises(ObjectStorageError):
        backup.validate_row(sample.replace('"provider":"TCGdex"',
            '"provider":"TCGdex","provider":"wrong"').encode(), "reference_market_prices")
    with pytest.raises(ObjectStorageError):
        backup.validate_row(sample.replace('"market_value_minor":101',
            '"market_value_minor":NaN').encode(), "reference_market_prices")


def make_archive(path: Path, values, name):
    raw = b"".join(line(item) + b"\n" for item in values)
    compressed = gzip.compress(raw, mtime=0)
    path.write_bytes(compressed)
    root = hashlib.sha256()
    for item in raw.splitlines():
        root.update(hashlib.sha256(item).hexdigest().encode())
    return {"schema": backup.SCHEMA, "source": f"tcg.{name}",
            "fields": list(backup.TABLE_FIELDS[name]), "full_table_snapshot": True,
            "row_count": len(values), "raw_bytes": len(raw),
            "content_root_sha256": root.hexdigest(),
            "ndjson_sha256": hashlib.sha256(raw).hexdigest(),
            "gzip_sha256": hashlib.sha256(compressed).hexdigest(),
            "gzip_bytes": len(compressed)}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", backup.TABLE_FIELDS)
async def test_restore_validates_every_row_in_bounded_batches(monkeypatch, tmp_path, name):
    values = [row(name, provider_id=f"sample-{i:04}") for i in range(401)]
    target = tmp_path / "source.gz"
    manifest = make_archive(target, values, name)
    sizes = []

    async def restore(_pool, _actor, table, lines):
        assert table == name
        sizes.append(len(lines))

    monkeypatch.setattr(backup, "_restore_batch", restore)
    await backup.verify_restore(object(), uuid4(), name, target, manifest)
    assert sizes == [200, 200, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["order", "manifest", "gzip", "source"])
async def test_restore_fails_closed_on_corruption(monkeypatch, tmp_path, problem):
    name = "reference_market_prices"
    values = [row(provider_id="sample-0001"), row(provider_id="sample-0002")]
    if problem == "order":
        values.reverse()
    target = tmp_path / "source.gz"
    manifest = make_archive(target, values, name)
    if problem == "manifest":
        manifest["ndjson_sha256"] = "0" * 64
    if problem == "gzip":
        target.write_bytes(b"truncated-gzip")
    if problem == "source":
        manifest["source"] = "tcg.reference_cards"

    async def fake_restore(*_args):
        pass

    monkeypatch.setattr(backup, "_restore_batch", fake_restore)
    with pytest.raises(ObjectStorageError):
        await backup.verify_restore(object(), uuid4(), name, target, manifest)


@pytest.mark.asyncio
async def test_typed_restore_mismatch_rollback_and_admin_required(monkeypatch):
    calls = []
    sample = line(row())

    class Transaction:
        async def start(self):
            calls.append("start")
        async def rollback(self):
            calls.append("rollback")

    class Connection:
        def transaction(self):
            return Transaction()
        async def execute(self, sql, *args):
            calls.append(sql)
            if sql == backup.RESTORE_INSERT_SQL:
                assert args[0] == "[" + sample.decode() + "]"
        async def fetch(self, sql):
            assert sql == backup.RESTORE_CHECK_SQL
            return [{"canonical_row": sample.decode() + " "}]

    class Pool:
        @asynccontextmanager
        async def acquire(self, **_kwargs):
            yield Connection()

    async def authorized(_conn):
        calls.append("admin-checked")

    monkeypatch.setattr(backup, "require_platform_admin", authorized)
    with pytest.raises(ObjectStorageError, match="typed restore differs"):
        await backup._restore_batch(Pool(), uuid4(), "reference_market_prices", [sample])
    assert calls[-1] == "rollback"
    assert "admin-checked" in calls
    assert any("like tcg.reference_market_prices" in call for call in calls)


@pytest.mark.asyncio
async def test_schema_drift_stops_export_before_cursor(monkeypatch, tmp_path):
    class Transaction:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
    class Connection:
        def transaction(self, **kwargs):
            assert kwargs == {"isolation": "repeatable_read", "readonly": True}
            return Transaction()
        async def execute(self, *_args):
            pass
        async def fetch(self, _sql):
            return [{"attname": "wrong_column"}]
        def cursor(self, *_args, **_kwargs):
            pytest.fail("Schema drift must stop before reading quote contents")
    class Pool:
        @asynccontextmanager
        async def acquire(self, **_kwargs):
            yield Connection()
    async def admin(_connection):
        pass
    monkeypatch.setattr(backup, "require_platform_admin", admin)
    with pytest.raises(ObjectStorageError, match="schema changed"):
        await backup.export_snapshot(Pool(), uuid4(), "reference_market_prices", tmp_path / "bad.gz")


@pytest.mark.asyncio
async def test_upload_requires_two_verified_archives_and_manifests(monkeypatch):
    receipts = []

    async def export(_pool, _actor, name, path):
        return make_archive(path, [row(name)], name)

    class Store:
        def __init__(self):
            self.data = {}
        def put_verified_file(self, path, *, category, content_type):
            assert category == "exports"
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            key = f"drop-rate/exports/{digest}{''.join(path.suffixes)}"
            self.data[key] = content
            receipts.append(key)
            return {"key": key, "size_bytes": len(content), "sha256": digest, "verified": True}
        def download_verified_file(self, key, destination, *, expected_sha256, expected_size):
            content = self.data[key]
            assert hashlib.sha256(content).hexdigest() == expected_sha256
            assert len(content) == expected_size
            destination.write_bytes(content)

    async def restore_any(_pool, _actor, name, source, manifest):
        assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["gzip_sha256"]

    monkeypatch.setattr(backup, "export_snapshot", export)
    monkeypatch.setattr(backup, "verify_restore", restore_any)
    result = await backup.backup_reference_quote_sources(object(), uuid4(), upload=True, store=Store())
    assert result["status"] == "R2_RESTORE_VERIFIED"
    assert result["total_rows"] == 2
    assert result["bytes_reclaimed"] == result["rows_reclaimed"] == 0
    assert result["live_prices_untouched"] and not result["physical_offload_authorized"]
    assert len(receipts) == 4
    assert set(source["source"] for source in result["sources"]) == {
        "tcg.reference_market_prices", "tcg.reference_catalogue_prices",
    }


@pytest.mark.asyncio
async def test_corrupt_r2_download_never_claims_success(monkeypatch):
    class Store:
        def put_verified_file(self, path, **_kwargs):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            return {"key": f"drop-rate/exports/{digest}.ndjson.gz", "sha256": digest,
                    "size_bytes": len(data), "verified": True}
        def download_verified_file(self, *_args, **_kwargs):
            raise ObjectStorageError("R2 remote bytes differ")

    async def export(_pool, _actor, name, path):
        return make_archive(path, [row(name)], name)

    monkeypatch.setattr(backup, "export_snapshot", export)
    with pytest.raises(ObjectStorageError, match="remote bytes"):
        await backup.backup_reference_quote_sources(object(), uuid4(), upload=True, store=Store())


@pytest.mark.asyncio
async def test_untrusted_r2_receipt_never_accepted(monkeypatch):
    class Store:
        def put_verified_file(self, path, **_kwargs):
            return {"key": "not-verified", "sha256": "0" * 64, "size_bytes": 1}
        def download_verified_file(self, *_args, **_kwargs):
            pytest.fail("No readback may follow a false object receipt")

    async def export(_pool, _actor, name, path):
        return make_archive(path, [row(name)], name)

    monkeypatch.setattr(backup, "export_snapshot", export)
    with pytest.raises(ObjectStorageError, match="storage receipt differs"):
        await backup.backup_reference_quote_sources(object(), uuid4(), upload=True, store=Store())


@pytest.mark.asyncio
async def test_dry_run_does_not_touch_r2(monkeypatch):
    calls = []

    async def export(_pool, _actor, name, path):
        calls.append(name)
        return make_archive(path, [row(name)], name)

    async def restore(*_args):
        pass

    monkeypatch.setattr(backup, "export_snapshot", export)
    monkeypatch.setattr(backup, "verify_restore", restore)
    result = await backup.backup_reference_quote_sources(object(), uuid4())
    assert result["status"] == "LOCAL_RESTORE_VERIFIED"
    assert calls == list(backup.TABLE_FIELDS)
    assert result["bytes_reclaimed"] == 0
