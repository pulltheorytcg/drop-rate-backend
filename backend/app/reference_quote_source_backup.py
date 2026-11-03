"""Lossless, manual R2 shadow backup of both current reference price tables.

This is a prerequisite for a future physical quote offload, not an offload:
pricing writes, live quote reads, ownership, and PostgreSQL rows stay intact.
Each full-table snapshot is read under a repeatable-read transaction, stored
privately by content hash, downloaded, and type-restored in rolled-back temp
tables before a verified manifest is published.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import UUID

from .access_control import require_platform_admin
from .object_storage import ObjectStorageError, configured_object_storage, sha256_file


SCHEMA = "drop-rate-reference-price-source-backup-v1"
IDENTITY = ("provider", "system_code", "language", "provider_id")
COMMON_FIELDS = IDENTITY + (
    "quotes", "market_value_minor", "market_value_high_minor", "pricing_updated_at",
    "checked_at", "expires_at",
)
TABLE_FIELDS = {
    "reference_market_prices": COMMON_FIELDS + ("refresh_revision",),
    "reference_catalogue_prices": COMMON_FIELDS,
}
MAX_ROWS = 100_000
MAX_RAW_BYTES = 128_000_000
MAX_LINE_BYTES = 1_000_000
BATCH_ROWS = 200
BATCH_BYTES = 2_000_000


def _table(name: str) -> str:
    if name not in TABLE_FIELDS:
        raise ValueError("Unsupported reference price source")
    return name


def _columns_sql(name: str) -> str:
    _table(name)
    return ("select attname from pg_attribute "
            f"where attrelid='tcg.{name}'::regclass and attnum>0 and not attisdropped "
            "order by attnum")


def _order(alias: str) -> str:
    return ",".join(f'{alias}.{field} COLLATE "C"' for field in IDENTITY)


def _export_sql(name: str) -> str:
    _table(name)
    return (f"select row_to_json(p)::text as canonical_row from tcg.{name} p "
            f"order by {_order('p')}")


def _restore_create_sql(name: str) -> str:
    _table(name)
    return ("create temporary table reference_quote_restore_check "
            f"(like tcg.{name} including constraints) on commit drop")


RESTORE_INSERT_SQL = ("insert into pg_temp.reference_quote_restore_check "
                      "select * from json_populate_recordset("
                      "null::pg_temp.reference_quote_restore_check,$1::json)")
RESTORE_CHECK_SQL = ("select row_to_json(p)::text as canonical_row "
                     "from pg_temp.reference_quote_restore_check p "
                     f"order by {_order('p')}")


def _verify_receipt(receipt: dict, digest: str, size: int, suffix: str) -> None:
    """Require the object-store readback receipt for the expected exact bytes."""
    if (not isinstance(receipt, dict) or receipt.get("verified") is not True
            or receipt.get("sha256") != digest or receipt.get("size_bytes") != size
            or not isinstance(receipt.get("key"), str)
            or not receipt["key"].endswith(f"/exports/{digest}{suffix}")):
        raise ObjectStorageError("Reference quote R2 storage receipt differs from source")


def _reject_constant(_value):
    raise ObjectStorageError("Non-finite reference quote JSON")


def _unique_object(pairs):
    result = {}
    for field, value in pairs:
        if field in result:
            raise ObjectStorageError("Duplicate reference quote field")
        result[field] = value
    return result


def _timestamp(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid price timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Price timestamp must be timezone-aware")
    return result


def validate_row(line: bytes, name: str) -> tuple[str, str, str, str]:
    """Enforce an exact, typed table shape without changing PostgreSQL JSON."""
    _table(name)
    try:
        row = json.loads(line, parse_constant=_reject_constant,
                         object_pairs_hook=_unique_object)
        if not isinstance(row, dict) or tuple(row) != TABLE_FIELDS[name]:
            raise ValueError("Source column schema drift")
        if any(not isinstance(row[field], str) or not row[field] for field in IDENTITY):
            raise ValueError("Invalid reference identity")
        quotes = row["quotes"]
        if not isinstance(quotes, list) or len(quotes) > 40 or any(
                not isinstance(quote, dict) for quote in quotes):
            raise ValueError("Invalid reference quotes")
        low, high = row["market_value_minor"], row["market_value_high_minor"]
        for value in (low, high):
            if value is not None and (type(value) is not int or not 0 < value < 2**63):
                raise ValueError("Invalid monetary value")
        if (low is None) != (high is None) or (low is not None and high < low):
            raise ValueError("Invalid price range")
        if low is not None and (not quotes or row["pricing_updated_at"] is None):
            raise ValueError("Price lacks quote provenance")
        checked = _timestamp(row["checked_at"])
        if _timestamp(row["expires_at"]) <= checked:
            raise ValueError("Invalid expiry")
        _timestamp(row["pricing_updated_at"], optional=True)
        if name == "reference_market_prices" and (
                type(row["refresh_revision"]) is not int or row["refresh_revision"] < 0):
            raise ValueError("Invalid refresh revision")
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError) as exc:
        raise ObjectStorageError("Invalid reference price source record") from exc
    return tuple(row[field] for field in IDENTITY)


async def _authorize(connection, actor: UUID, request_id: str):
    await connection.execute("select set_config('tcg.user_id',$1,true)", str(actor))
    await connection.execute("select set_config('tcg.request_id',$1,true)", request_id)
    await connection.execute("set local timezone='UTC'")
    await connection.execute("set local datestyle='ISO,YMD'")
    await require_platform_admin(connection)


async def export_snapshot(pool, actor: UUID, name: str, target: Path) -> dict:
    _table(name)
    if not isinstance(actor, UUID):
        raise ValueError("A platform-administrator UUID is required")
    root, ndjson = hashlib.sha256(), hashlib.sha256()
    count = raw_size = 0
    previous = None
    with target.open("xb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
            async with pool.acquire(timeout=15) as connection:
                async with connection.transaction(isolation="repeatable_read", readonly=True):
                    await _authorize(connection, actor, "r2-reference-quote-shadow-export")
                    columns = tuple(row["attname"] for row in await connection.fetch(_columns_sql(name)))
                    if columns != TABLE_FIELDS[name]:
                        raise ObjectStorageError("Reference price source schema changed; export refused")
                    async for record in connection.cursor(_export_sql(name), prefetch=BATCH_ROWS):
                        line = record["canonical_row"].encode("utf-8")
                        if len(line) + 1 > MAX_LINE_BYTES:
                            raise ObjectStorageError("Reference quote record exceeds line limit")
                        identity = validate_row(line, name)
                        if previous is not None and identity <= previous:
                            raise ObjectStorageError("Reference quote identities must be unique and ordered")
                        previous = identity
                        count += 1
                        raw_size += len(line) + 1
                        if count > MAX_ROWS or raw_size > MAX_RAW_BYTES:
                            raise ObjectStorageError("Reference price source exceeds backup limits")
                        root.update(hashlib.sha256(line).hexdigest().encode("ascii"))
                        ndjson.update(line + b"\n")
                        compressed.write(line + b"\n")
    digest, size = sha256_file(target)
    return {"schema": SCHEMA, "source": f"tcg.{name}",
            "fields": list(TABLE_FIELDS[name]), "full_table_snapshot": True,
            "row_count": count, "raw_bytes": raw_size,
            "content_root_sha256": root.hexdigest(), "ndjson_sha256": ndjson.hexdigest(),
            "gzip_sha256": digest, "gzip_bytes": size, "database_mutations": 0}


async def _restore_batch(pool, actor: UUID, name: str, lines: list[bytes]) -> None:
    expected = {validate_row(line, name): line.decode("utf-8") for line in lines}
    if len(expected) != len(lines):
        raise ObjectStorageError("Duplicate reference quote identity in restore batch")
    async with pool.acquire(timeout=15) as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            await _authorize(connection, actor, "r2-reference-quote-shadow-restore")
            await connection.execute(_restore_create_sql(name))
            payload = "[" + ",".join(line.decode("utf-8") for line in lines) + "]"
            await connection.execute(RESTORE_INSERT_SQL, payload)
            restored = await connection.fetch(RESTORE_CHECK_SQL)
            if len(restored) != len(lines):
                raise ObjectStorageError("Reference quote typed restore count differs")
            for record in restored:
                actual = record["canonical_row"]
                identity = validate_row(actual.encode("utf-8"), name)
                if expected.get(identity) != actual:
                    raise ObjectStorageError("Reference quote typed restore differs from archive")
        finally:
            await transaction.rollback()


async def verify_restore(pool, actor: UUID, name: str, downloaded: Path, manifest: dict) -> None:
    _table(name)
    if (manifest.get("schema") != SCHEMA or manifest.get("source") != f"tcg.{name}"
            or manifest.get("fields") != list(TABLE_FIELDS[name])
            or manifest.get("full_table_snapshot") is not True):
        raise ObjectStorageError("Unsupported reference quote backup manifest")
    if sha256_file(downloaded) != (manifest["gzip_sha256"], manifest["gzip_bytes"]):
        raise ObjectStorageError("Downloaded reference quote archive checksum differs")
    root, ndjson = hashlib.sha256(), hashlib.sha256()
    previous = None
    count = raw_size = batch_size = 0
    batch = []
    try:
        with gzip.open(downloaded, "rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                    raise ObjectStorageError("Reference quote archive line is invalid")
                line = raw[:-1]
                identity = validate_row(line, name)
                if previous is not None and identity <= previous:
                    raise ObjectStorageError("Reference quote archive identities are not ordered")
                previous = identity
                count += 1
                raw_size += len(raw)
                if count > MAX_ROWS or raw_size > MAX_RAW_BYTES:
                    raise ObjectStorageError("Downloaded reference quote source exceeds limits")
                root.update(hashlib.sha256(line).hexdigest().encode("ascii"))
                ndjson.update(raw)
                if batch and batch_size + len(raw) > BATCH_BYTES:
                    await _restore_batch(pool, actor, name, batch)
                    batch, batch_size = [], 0
                batch.append(line)
                batch_size += len(raw)
                if len(batch) == BATCH_ROWS:
                    await _restore_batch(pool, actor, name, batch)
                    batch, batch_size = [], 0
        if batch:
            await _restore_batch(pool, actor, name, batch)
    except (OSError, EOFError) as exc:
        raise ObjectStorageError("Cannot decompress reference quote backup") from exc
    if (count != manifest["row_count"] or raw_size != manifest["raw_bytes"]
            or root.hexdigest() != manifest["content_root_sha256"]
            or ndjson.hexdigest() != manifest["ndjson_sha256"]):
        raise ObjectStorageError("Reference quote restore differs from manifest")


async def backup_reference_quote_sources(pool, actor: UUID, *, upload=False, store=None) -> dict:
    """Restoration proof of both entire tables. Absolutely no permanent SQL writes."""
    if type(upload) is not bool or not isinstance(actor, UUID):
        raise ValueError("Backup requires UUID actor and boolean upload")
    if upload:
        store = store if store is not None else configured_object_storage()
        if store is None:
            raise ObjectStorageError("Private R2 storage is not configured")
    results = []
    with tempfile.TemporaryDirectory(prefix="drop-rate-r2-quote-shadow-") as directory:
        root = Path(directory)
        for name in TABLE_FIELDS:
            archive = root / f"{name}.ndjson.gz"
            manifest = await export_snapshot(pool, actor, name, archive)
            if manifest["row_count"] == 0:
                raise ObjectStorageError("Cannot claim full-table backup of an empty price source")
            readback = archive
            if upload:
                receipt = await asyncio.to_thread(store.put_verified_file, archive,
                    category="exports", content_type="application/gzip")
                _verify_receipt(receipt, manifest["gzip_sha256"], manifest["gzip_bytes"],
                                ".ndjson.gz")
                readback = root / f"{name}.r2-readback.ndjson.gz"
                await asyncio.to_thread(store.download_verified_file, receipt["key"], readback,
                    expected_sha256=manifest["gzip_sha256"], expected_size=manifest["gzip_bytes"])
            await verify_restore(pool, actor, name, readback, manifest)
            manifest.update(restoration_verified=True,
                restoration_method="POSTGRES_TEMP_TABLE_EVERY_COLUMN_V1",
                verified_at=datetime.now(timezone.utc).isoformat(),
                rows_reclaimed=0, bytes_reclaimed=0)
            if upload:
                manifest["archive_object"] = receipt
                path = root / f"{name}.manifest.json"
                content = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
                path.write_bytes(content)
                manifest_receipt = await asyncio.to_thread(store.put_verified_file, path,
                    category="exports", content_type="application/json")
                _verify_receipt(manifest_receipt, hashlib.sha256(content).hexdigest(),
                                len(content), ".manifest.json")
                copy = root / f"{name}.r2-readback.manifest.json"
                await asyncio.to_thread(store.download_verified_file, manifest_receipt["key"], copy,
                    expected_sha256=manifest_receipt["sha256"],
                    expected_size=manifest_receipt["size_bytes"])
                if copy.read_bytes() != content:
                    raise ObjectStorageError("Reference quote manifest readback differs")
                manifest["manifest_object"] = manifest_receipt
            results.append(manifest)
    return {"status": "R2_RESTORE_VERIFIED" if upload else "LOCAL_RESTORE_VERIFIED",
            "uploaded": upload, "sources": results,
            "total_rows": sum(source["row_count"] for source in results),
            "rows_reclaimed": 0, "bytes_reclaimed": 0,
            "live_prices_untouched": True, "physical_offload_authorized": False}
