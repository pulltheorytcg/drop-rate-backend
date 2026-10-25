"""Write a verified, *non-destructive* reference-price history copy to S3/R2.

This is a manual/worker entry point. It does not truncate history, mark a
Google Drive receipt, alter live prices, or export customer/account data.
The eventual n8n scheduler should invoke a governed backend job, not connect
to Supabase as a superuser or receive object-store secret keys.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.access_control import require_platform_admin
from app.db import create_pool
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage
from app.settings import get_settings


HISTORY_FIELDS = (
    "id", "reference_kind", "provider", "system_code", "language",
    "provider_id", "quotes", "quote_digest", "market_value_minor",
    "market_value_high_minor", "pricing_updated_at", "recorded_at",
)
HISTORY_SQL = "select " + ", ".join(HISTORY_FIELDS) + " from tcg.reference_market_history order by id"


async def export_snapshot(pool, actor: UUID, target: Path, *, max_rows: int) -> dict:
    """Use a consistent, read-only, RLS-authorised snapshot and bounded disk file."""
    digest = hashlib.sha256()
    row_count = 0
    with target.open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
            async with pool.acquire() as connection:
                async with connection.transaction(isolation="repeatable_read", readonly=True):
                    await connection.execute("select set_config('tcg.user_id', $1, true)", str(actor))
                    await connection.execute("select set_config('tcg.request_id', $1, true)", "cold-archive-export")
                    await require_platform_admin(connection)
                    async for row in connection.cursor(HISTORY_SQL, prefetch=200):
                        row_count += 1
                        if row_count > max_rows:
                            raise ObjectStorageError("Reference-history export exceeds configured row limit")
                        encoded = (json.dumps(
                            {name: row[name] for name in HISTORY_FIELDS},
                            default=str,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ) + "\n").encode("utf-8")
                        digest.update(encoded)
                        compressed.write(encoded)
    gzip_sha, gzip_size = sha256_file(target)
    return {
        "schema": "drop-rate-reference-history-ndjson-gzip-v1",
        "row_count": row_count,
        "ndjson_sha256": digest.hexdigest(),
        "gzip_sha256": gzip_sha,
        "gzip_bytes": gzip_size,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "full_table_snapshot": True,
        "database_mutations": 0,
        "restoration_verified": False,
    }


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            length += len(chunk)
    return digest.hexdigest(), length


async def run(*, apply: bool, max_rows: int) -> dict:
    settings = get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise ObjectStorageError("An existing platform-admin maintenance actor is required")
    actor = UUID(settings.catalogue_maintenance_actor_user_id)
    config = ObjectStorageConfig.from_env() if apply else None
    if apply and config is None:
        raise ObjectStorageError("Private object storage is not enabled")

    with tempfile.TemporaryDirectory(prefix="drop-rate-reference-history-") as temp_dir:
        archive_path = Path(temp_dir) / "reference-history.ndjson.gz"
        pool = await create_pool(settings)
        try:
            manifest = await export_snapshot(pool, actor, archive_path, max_rows=max_rows)
        finally:
            await pool.close()
        if manifest["row_count"] == 0:
            return {**manifest, "status": "NO_HISTORY", "uploaded": False}
        if not apply:
            return {**manifest, "status": "DRY_RUN", "uploaded": False}

        store = S3ObjectStorage(config)
        archive_receipt = await asyncio.to_thread(
            store.put_verified_file,
            archive_path,
            category="reference-history",
            content_type="application/gzip",
        )
        manifest["archive_object"] = archive_receipt
        manifest_path = Path(temp_dir) / "reference-history.manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        receipt = await asyncio.to_thread(
            store.put_verified_file,
            manifest_path,
            category="reference-history",
            content_type="application/json",
        )
        return {**manifest, "manifest_object": receipt, "status": "BYTES_VERIFIED", "uploaded": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload privately and verify round trip")
    parser.add_argument("--max-rows", type=int, default=1_000_000)
    args = parser.parse_args()
    if args.max_rows < 1:
        parser.error("--max-rows must be positive")
    print(json.dumps(asyncio.run(run(apply=args.apply, max_rows=args.max_rows)), sort_keys=True))
