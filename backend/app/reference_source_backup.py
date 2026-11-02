"""Lossless, non-destructive reference-card backup for the staged R2 offload.

The live R2 catalogue intentionally omits source-only columns. This exporter
captures *every* PostgreSQL column in a consistent snapshot, verifies the R2
download, and type-restores every row into disposable PostgreSQL temp tables.
It never changes a source row or authorizes physical offload by itself.
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


SCHEMA = "drop-rate-reference-cards-source-backup-v1"
FIELDS = (
    "provider", "system_code", "language", "provider_id", "set_id", "name",
    "card_number", "number_key", "finish", "rarity", "image_url",
    "source_url", "evidence", "refreshed_at",
)
IDENTITY = ("provider", "system_code", "language", "provider_id")
MAX_ROWS = 100_000
MAX_RAW_BYTES = 128_000_000
MAX_LINE_BYTES = 1_000_000
BATCH_ROWS = 200
BATCH_BYTES = 2_000_000

FIELDS_SQL = """select attname from pg_attribute
 where attrelid='tcg.reference_cards'::regclass and attnum>0 and not attisdropped
 order by attnum"""
EXPORT_SQL = """select row_to_json(c)::text as canonical_row
 from tcg.reference_cards c
 order by c.provider,c.system_code,c.language,c.provider_id"""
RESTORE_TABLE_SQL = """create temporary table reference_cards_restore_check
 (like tcg.reference_cards including constraints) on commit drop"""
RESTORE_INSERT_SQL = """insert into pg_temp.reference_cards_restore_check
 select * from json_populate_recordset(null::pg_temp.reference_cards_restore_check,$1::json)"""
RESTORE_CHECK_SQL = """select row_to_json(c)::text as canonical_row
 from pg_temp.reference_cards_restore_check c
 order by c.provider,c.system_code,c.language,c.provider_id"""


def _no_constant(_value):
    raise ObjectStorageError("Non-finite backup JSON")


def _unique_fields(pairs):
    row = {}
    for name, value in pairs:
        if name in row:
            raise ObjectStorageError("Duplicate reference-card field")
        row[name] = value
    return row


def validate_row(line: bytes) -> tuple[str, str, str, str]:
    try:
        row = json.loads(line, parse_constant=_no_constant, object_pairs_hook=_unique_fields)
        if not isinstance(row, dict) or tuple(row) != FIELDS:
            raise ValueError("Unexpected source schema")
        if any(not isinstance(row[field], str) or not row[field] for field in IDENTITY):
            raise ValueError("Invalid source identity")
        for field in ("set_id", "name", "card_number", "number_key", "finish",
                      "rarity", "image_url", "source_url"):
            if row[field] is not None and not isinstance(row[field], str):
                raise ValueError("Invalid source text")
        value = row["refreshed_at"]
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Invalid source timestamp")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("Source timestamp lacks timezone")
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ObjectStorageError("Invalid reference-card source record") from exc
    return tuple(row[field] for field in IDENTITY)


async def _authorize(conn, actor: UUID, request_id: str) -> None:
    await conn.execute("select set_config('tcg.user_id',$1,true)", str(actor))
    await conn.execute("select set_config('tcg.request_id',$1,true)", request_id)
    await conn.execute("set local timezone='UTC'")
    await conn.execute("set local datestyle='ISO,YMD'")
    await require_platform_admin(conn)


async def export_snapshot(pool, actor: UUID, target: Path) -> dict:
    if not isinstance(actor, UUID):
        raise ValueError("A platform-administrator UUID is required")
    root = hashlib.sha256()
    ndjson_digest = hashlib.sha256()
    row_count = raw_bytes = 0
    previous = None
    with target.open("xb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
            async with pool.acquire(timeout=15) as conn:
                async with conn.transaction(isolation="repeatable_read", readonly=True):
                    await _authorize(conn, actor, "r2-source-backup-export")
                    columns = tuple(record["attname"] for record in await conn.fetch(FIELDS_SQL))
                    if columns != FIELDS:
                        raise ObjectStorageError("Reference-card source schema changed; backup refused")
                    async for record in conn.cursor(EXPORT_SQL, prefetch=BATCH_ROWS):
                        line = record["canonical_row"].encode("utf-8")
                        if len(line) + 1 > MAX_LINE_BYTES:
                            raise ObjectStorageError("Reference-card record exceeds backup line limit")
                        identity = validate_row(line)
                        if previous is not None and identity <= previous:
                            raise ObjectStorageError("Reference-card identities must be unique and ordered")
                        previous = identity
                        row_count += 1
                        raw_bytes += len(line) + 1
                        if row_count > MAX_ROWS or raw_bytes > MAX_RAW_BYTES:
                            raise ObjectStorageError("Reference-card source exceeds backup limits")
                        root.update(hashlib.sha256(line).hexdigest().encode("ascii"))
                        ndjson_digest.update(line + b"\n")
                        compressed.write(line + b"\n")
    digest, size = sha256_file(target)
    return {
        "schema": SCHEMA,
        "source": "tcg.reference_cards",
        "fields": list(FIELDS),
        "row_count": row_count,
        "raw_bytes": raw_bytes,
        "content_root_sha256": root.hexdigest(),
        "ndjson_sha256": ndjson_digest.hexdigest(),
        "gzip_sha256": digest,
        "gzip_bytes": size,
        "full_table_snapshot": True,
        "database_mutations": 0,
    }


async def _restore_batch(pool, actor: UUID, lines: list[bytes]) -> None:
    expected = {validate_row(line): line.decode("utf-8") for line in lines}
    if len(expected) != len(lines):
        raise ObjectStorageError("Duplicate reference-card identity in restore batch")
    async with pool.acquire(timeout=15) as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            await _authorize(conn, actor, "r2-source-backup-restore")
            await conn.execute(RESTORE_TABLE_SQL)
            payload = "[" + ",".join(line.decode("utf-8") for line in lines) + "]"
            await conn.execute(RESTORE_INSERT_SQL, payload)
            restored = await conn.fetch(RESTORE_CHECK_SQL)
            if len(restored) != len(lines):
                raise ObjectStorageError("Reference-card typed restore count differs")
            for record in restored:
                actual = record["canonical_row"]
                identity = validate_row(actual.encode("utf-8"))
                if expected.get(identity) != actual:
                    raise ObjectStorageError("Reference-card typed restore differs from archive")
        finally:
            await transaction.rollback()


async def verify_restore(pool, actor: UUID, downloaded: Path, manifest: dict) -> None:
    if (manifest.get("schema") != SCHEMA or manifest.get("fields") != list(FIELDS)
            or manifest.get("full_table_snapshot") is not True):
        raise ObjectStorageError("Unsupported reference-card source manifest")
    if sha256_file(downloaded) != (manifest["gzip_sha256"], manifest["gzip_bytes"]):
        raise ObjectStorageError("Downloaded reference-card archive checksum differs")
    root = hashlib.sha256()
    digest = hashlib.sha256()
    previous = None
    row_count = raw_bytes = batch_bytes = 0
    batch = []
    try:
        with gzip.open(downloaded, "rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                    raise ObjectStorageError("Backup line is oversized or unterminated")
                line = raw[:-1]
                identity = validate_row(line)
                if previous is not None and identity <= previous:
                    raise ObjectStorageError("Backup identities are duplicate or out of order")
                previous = identity
                row_count += 1
                raw_bytes += len(raw)
                if row_count > MAX_ROWS or raw_bytes > MAX_RAW_BYTES:
                    raise ObjectStorageError("Downloaded reference-card backup exceeds limits")
                root.update(hashlib.sha256(line).hexdigest().encode("ascii"))
                digest.update(raw)
                if batch and batch_bytes + len(raw) > BATCH_BYTES:
                    await _restore_batch(pool, actor, batch)
                    batch, batch_bytes = [], 0
                batch.append(line)
                batch_bytes += len(raw)
                if len(batch) == BATCH_ROWS:
                    await _restore_batch(pool, actor, batch)
                    batch, batch_bytes = [], 0
        if batch:
            await _restore_batch(pool, actor, batch)
    except (OSError, EOFError) as exc:
        raise ObjectStorageError("Cannot decompress reference-card source backup") from exc
    if (row_count != manifest["row_count"] or raw_bytes != manifest["raw_bytes"]
            or root.hexdigest() != manifest["content_root_sha256"]
            or digest.hexdigest() != manifest["ndjson_sha256"]):
        raise ObjectStorageError("Reference-card restore differs from manifest")


async def backup_reference_cards(pool, actor: UUID, *, upload=False, store=None) -> dict:
    """Manual only: always restore-check; optional R2 upload; NEVER delete SQL."""
    if type(upload) is not bool or not isinstance(actor, UUID):
        raise ValueError("Backup requires UUID actor and boolean upload")
    if upload:
        store = store if store is not None else configured_object_storage()
        if store is None:
            raise ObjectStorageError("Private R2 storage is not configured")
    with tempfile.TemporaryDirectory(prefix="drop-rate-r2-reference-source-") as directory:
        root = Path(directory)
        archive = root / "reference-cards.ndjson.gz"
        manifest = await export_snapshot(pool, actor, archive)
        if manifest["row_count"] == 0:
            return {**manifest, "status": "EMPTY_SOURCE", "uploaded": False}
        source = archive
        if upload:
            receipt = await asyncio.to_thread(
                store.put_verified_file, archive,
                category="exports", content_type="application/gzip",
            )
            source = root / "r2-readback.ndjson.gz"
            await asyncio.to_thread(
                store.download_verified_file, receipt["key"], source,
                expected_sha256=manifest["gzip_sha256"], expected_size=manifest["gzip_bytes"],
            )
        await verify_restore(pool, actor, source, manifest)
        result = {**manifest, "restoration_verified": True,
                  "restoration_method": "POSTGRES_TEMP_TABLE_EVERY_COLUMN_V1",
                  "verified_at": datetime.now(timezone.utc).isoformat(),
                  "status": "R2_RESTORE_VERIFIED" if upload else "LOCAL_RESTORE_VERIFIED",
                  "uploaded": upload, "rows_reclaimed": 0, "bytes_reclaimed": 0}
        if upload:
            result["archive_object"] = receipt
            manifest_path = root / "reference-cards.manifest.json"
            manifest_bytes = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
            manifest_path.write_bytes(manifest_bytes)
            manifest_receipt = await asyncio.to_thread(
                store.put_verified_file, manifest_path,
                category="exports", content_type="application/json",
            )
            copy = root / "r2-readback.manifest.json"
            await asyncio.to_thread(
                store.download_verified_file, manifest_receipt["key"], copy,
                expected_sha256=manifest_receipt["sha256"],
                expected_size=manifest_receipt["size_bytes"],
            )
            if copy.read_bytes() != manifest_bytes:
                raise ObjectStorageError("R2 manifest readback differs")
            result["manifest_object"] = manifest_receipt
        return result
