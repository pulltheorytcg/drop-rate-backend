"""Private, lossless R2 source checkpoint for Drop Rate's operational data.

Scope: 11 explicitly reviewed tcg tables; excluded audit and market-observation
JSON can contain credential-like text and needs independent protected treatment.
Never copy Auth sessions, MFA keys or payment-card data. This is NOT a D1 import or a
production cutover. All source SQL uses one read-only repeatable-read snapshot.

Railway-only. Never print private source row JSON, R2 object URLs or tokens.
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


SCHEMA = "drop-rate-cloudflare-private-operational-source-v1"


def _progress(stage: str, table: str, rows: int) -> None:
    """Public-safe checkpoint only: fixed stage, approved table and row count.

    NEVER output a row value, owner ID, price, R2 key, token or object URL.
    """
    if stage not in {"SOURCE_READY", "RLS_TABLE_BLOCKED", "TYPED_VERIFY_START",
                     "TYPED_VERIFY_PROGRESS", "TYPED_VERIFY_DONE",
                     "R2_TABLE_VERIFIED", "R2_MANIFEST_VERIFIED"}:
        raise ObjectStorageError("Unexpected private migration progress stage")
    if table not in TABLE_PKS and table != "ALL":
        raise ObjectStorageError("Unexpected private migration progress table")
    if type(rows) is not int or not 0 <= rows <= MAX_ROWS_PER_TABLE:
        raise ObjectStorageError("Unexpected private migration progress count")
    print(f"DROP_RATE_PRIVATE_MIGRATION stage={stage} table={table} rows={rows}",flush=True)

# ONLY tables whose credentials / provider tokens are absent by schema review.
# Use a separate reviewed transfer for auth sessions, OAuth, Stripe, eBay
# credential tables, and any future unknown relation.
TABLE_PKS = {
    "owners": ("id",),
    "owner_memberships": ("id",),
    "inventory_items": ("id",),
    "orders": ("id",),
    "order_items": ("id",),
    "financial_ledger_entries": ("id",),
    "refund_events": ("id",),
    "shopify_webhook_events": ("id",),
    "media_assets": ("id",),
    "media_object_mirrors": ("id",),
    "reference_image_mirrors": ("provider", "system_code", "language", "provider_id"),
}
APPROVED_COLUMNS_PATH = (Path(__file__).resolve().parent.parent
                         / "data/cloudflare_exit_approved_columns_20261106.json")
_APPROVAL = json.loads(APPROVED_COLUMNS_PATH.read_text(encoding="utf-8"))
if (_APPROVAL.get("format") != "drop-rate-approved-operational-source-columns-v1"
        or _APPROVAL.get("project_id") != "ozrxenrdladkooixutmm"
        or set(_APPROVAL.get("tables", {})) != set(TABLE_PKS)):
    raise ObjectStorageError("Approved source column manifest does not match reviewed table scope")
APPROVED_COLUMNS = _APPROVAL["tables"]

# Read-only 6 Nov exact source baseline; live counts may grow but MUST NOT
# silently shrink behind RLS or partial export. Investigate before changing.
MIN_ROWS = {
    "owners": 6, "owner_memberships": 6, "inventory_items": 621,
    "orders": 3, "order_items": 3, "financial_ledger_entries": 13,
    "refund_events": 3, "shopify_webhook_events": 14,
    "media_assets": 515, "media_object_mirrors": 401,
    "reference_image_mirrors": 66222,
}
if set(MIN_ROWS) != set(TABLE_PKS):
    raise ObjectStorageError("Missing private backup source row-count safety floor")

MAX_ROWS_PER_TABLE = 130_000
MAX_RAW_BYTES_PER_TABLE = 250_000_000
MAX_GZIP_BYTES_PER_TABLE = 120_000_000
MAX_LINE_BYTES = 1_000_000
BATCH_ROWS = 100
BATCH_BYTES = 2_000_000


def _safe_table(name: str) -> str:
    if name not in TABLE_PKS:
        raise ObjectStorageError("Operational source not approved for R2 archival")
    return name


def _identity(line: bytes, name: str, fields: list[str]) -> tuple:
    if len(line) > MAX_LINE_BYTES:
        raise ObjectStorageError("Oversize operational source row")
    try:
        obj = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(obj, dict) or list(obj) != fields:
            raise ValueError("Unexpected column shape")
        pk = tuple(obj[k] for k in TABLE_PKS[name])
        if any(not isinstance(x, (str, int)) or isinstance(x, bool)
               or x == "" for x in pk):
            raise ValueError("Invalid source key")
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError) as exc:
        raise ObjectStorageError("Invalid operational source record") from exc
    return pk


async def _authorize(conn, actor: UUID, request_id: str) -> None:
    await conn.execute("select set_config('tcg.user_id',$1,true)", str(actor))
    await conn.execute("select set_config('tcg.request_id',$1,true)", request_id)
    await conn.execute("set local timezone='UTC'")
    await conn.execute("set local datestyle='ISO,YMD'")
    await require_platform_admin(conn)


async def _source_schema(conn, name: str) -> list[str]:
    name = _safe_table(name)
    metadata = [dict(name=r["attname"], type=r["data_type"])
                for r in await conn.fetch(
        """select attname, format_type(atttypid,atttypmod) as data_type
         from pg_attribute
         where attrelid=$1::regclass and attnum>0 and not attisdropped
         order by attnum""", f"tcg.{name}")]
    if metadata != APPROVED_COLUMNS[name]:
        raise ObjectStorageError("Unapproved source schema drift: export is blocked")
    cols = [row["name"] for row in metadata]
    if not cols or not set(TABLE_PKS[name]).issubset(cols):
        raise ObjectStorageError("Operational source columns/primary key absent")
    return cols


def _source_select(name: str) -> str:
    _safe_table(name)
    pks = ",".join(f't."{p}"' for p in TABLE_PKS[name])
    return f'select row_to_json(t)::text as canonical_row from tcg."{name}" t order by {pks}'


async def export_table(conn, name: str, target: Path) -> dict:
    """Export a full table from an already authorised repeatable-read snapshot."""
    name = _safe_table(name)
    fields = await _source_schema(conn, name)
    count_expected = await conn.fetchval(f'select count(*) from tcg."{name}"')
    if (type(count_expected) is not int
            or not MIN_ROWS[name] <= count_expected <= MAX_ROWS_PER_TABLE):
        raise ObjectStorageError(
            f"Source count below independently checked baseline or above safe bound "
            f"table={name} visible={count_expected} minimum={MIN_ROWS[name]}")
    count = raw_bytes = 0
    sha = hashlib.sha256()
    identities: set[tuple] = set()
    with target.open("xb") as file:
        with gzip.GzipFile(fileobj=file, mode="wb", filename="", mtime=0) as gz:
            async for record in conn.cursor(_source_select(name), prefetch=BATCH_ROWS):
                line = record["canonical_row"].encode("utf-8")
                pk = _identity(line, name, fields)
                if pk in identities:
                    raise ObjectStorageError("Duplicate source primary key")
                identities.add(pk)
                count += 1
                raw_bytes += len(line) + 1
                if count > MAX_ROWS_PER_TABLE or raw_bytes > MAX_RAW_BYTES_PER_TABLE:
                    raise ObjectStorageError("Operational source exceeded safety bounds")
                sha.update(line + b"\n")
                gz.write(line + b"\n")
    if count != count_expected:
        raise ObjectStorageError("Source cursor truncated relative to snapshot")
    zipped_sha, zipped_size = sha256_file(target)
    if zipped_size > MAX_GZIP_BYTES_PER_TABLE:
        raise ObjectStorageError("Operational R2 archive exceeds safe object limit")
    return {
        "table": name, "source": f"tcg.{name}", "fields": fields,
        "primary_key": list(TABLE_PKS[name]), "rows": count,
        "raw_bytes": raw_bytes, "source_ndjson_sha256": sha.hexdigest(),
        "gzip_sha256": zipped_sha, "gzip_bytes": zipped_size,
        "private": True, "no_source_writes": True,
    }


async def verify_typed_roundtrip(pool, actor: UUID, downloaded: Path, proof: dict) -> None:
    """Read ALL R2 bytes and re-construct original PostgreSQL composite types.

    Only SELECT and a read-only transaction; no temp tables, SQL writes or
    'restored into production' claim.
    """
    name = _safe_table(proof.get("table"))
    fields = proof.get("fields")
    if (not isinstance(fields, list)
            or proof.get("source") != f"tcg.{name}"
            or proof.get("primary_key") != list(TABLE_PKS[name])
            or sha256_file(downloaded) != (proof.get("gzip_sha256"), proof.get("gzip_bytes"))):
        raise ObjectStorageError("R2 operational source proof not bound to its table")
    digest = hashlib.sha256()
    rows = raw_bytes = 0
    unique: set[tuple] = set()
    batch: list[bytes] = []
    batch_bytes = 0

    async def check_chunk(chunks: list[bytes]) -> None:
        payload = "[" + ",".join(c.decode("utf-8") for c in chunks) + "]"
        expected = {_identity(c, name, fields): c.decode("utf-8") for c in chunks}
        if len(expected) != len(chunks):
            raise ObjectStorageError("Duplicate identity in R2 verification chunk")
        async with pool.acquire(timeout=15) as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                await _authorize(conn, actor, "r2-full-exit-typed-readback")
                now_cols = await _source_schema(conn, name)
                if now_cols != fields:
                    raise ObjectStorageError("Source table schema changed during restore proof")
                restored = await conn.fetch(
                    f"select row_to_json(r)::text as canonical_row "
                    f"from json_populate_recordset(null::tcg.\"{name}\",$1::json) r",
                    payload,
                )
        if len(restored) != len(chunks):
            raise ObjectStorageError("PostgreSQL typed replay dropped source records")
        for record in restored:
            actual = record["canonical_row"]
            key = _identity(actual.encode("utf-8"), name, fields)
            if expected.get(key) != actual:
                raise ObjectStorageError("PostgreSQL typed replay differs from R2 source")

    try:
        with gzip.open(downloaded, "rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                    raise ObjectStorageError("Malformed or oversized source archive line")
                line = raw[:-1]
                key = _identity(line, name, fields)
                if key in unique:
                    raise ObjectStorageError("Duplicate R2 source key")
                unique.add(key)
                digest.update(raw)
                rows += 1
                raw_bytes += len(raw)
                if rows % 5000 == 0:
                    _progress("TYPED_VERIFY_PROGRESS",name,rows)
                if rows > MAX_ROWS_PER_TABLE or raw_bytes > MAX_RAW_BYTES_PER_TABLE:
                    raise ObjectStorageError("Source archive exceeds safe bounds")
                if batch and (len(batch) >= BATCH_ROWS
                              or batch_bytes + len(raw) > BATCH_BYTES):
                    await check_chunk(batch)
                    batch, batch_bytes = [], 0
                batch.append(line)
                batch_bytes += len(raw)
            if batch:
                await check_chunk(batch)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise ObjectStorageError("Compressed R2 source cannot be verified") from exc
    if (rows != proof.get("rows") or raw_bytes != proof.get("raw_bytes")
            or digest.hexdigest() != proof.get("source_ndjson_sha256")):
        raise ObjectStorageError("R2 typed replay/source digest differs")


async def backup_operational_sources(pool, actor: UUID, *, upload: bool = False,
                                     storage=None) -> dict:
    if not isinstance(actor, UUID) or type(upload) is not bool:
        raise ObjectStorageError("A UUID maintenance actor and explicit upload mode are required")
    if upload:
        storage = storage or configured_object_storage()
        if storage is None:
            raise ObjectStorageError("Verified private R2 object storage not configured")
    results: list[dict] = []
    blocked: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="drop-rate-private-exit-") as d:
        root = Path(d)
        # ONE PostgreSQL MVCC snapshot across owners, sales, money, media and audit.
        async with pool.acquire(timeout=15) as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                await _authorize(conn, actor, "cloudflare-private-exit-export")
                for name in TABLE_PKS:
                    # A valid platform-admin login does NOT necessarily have
                    # full SELECT visibility in every legacy RLS policy.
                    # Never archive an incomplete table as if it were whole.
                    visible = await conn.fetchval(f'select count(*) from tcg."{name}"')
                    if type(visible) is not int or visible < MIN_ROWS[name]:
                        _progress("RLS_TABLE_BLOCKED",name,visible if type(visible) is int else 0)
                        blocked.append({
                            "table": name, "visible_rows": visible,
                            "minimum_source_rows": MIN_ROWS[name],
                            "reason": "RLS_FULL_TABLE_VISIBILITY_NOT_PROVEN",
                        })
                        continue
                    proof = await export_table(conn, name, root / (name + ".ndjson.gz"))
                    results.append(proof)
                    _progress("SOURCE_READY",name,proof["rows"])
        if not results:
            raise ObjectStorageError("No complete approved source tables are visible")
        # Only after the consistent SQL snapshot has closed do we write to R2.
        for proof in results:
            name = proof["table"]
            original = root / (name + ".ndjson.gz")
            source = original
            if upload:
                receipt = await asyncio.to_thread(
                    storage.put_verified_file, original, category="exports",
                    content_type="application/gzip")
                if (not isinstance(receipt, dict) or receipt.get("verified") is not True
                        or receipt.get("sha256") != proof["gzip_sha256"]
                        or receipt.get("size_bytes") != proof["gzip_bytes"]):
                    raise ObjectStorageError("R2 source upload receipt is inconsistent")
                source = root / (name + ".download.ndjson.gz")
                await asyncio.to_thread(
                    storage.download_verified_file, receipt["key"], source,
                    expected_sha256=proof["gzip_sha256"],
                    expected_size=proof["gzip_bytes"])
                proof["archive_object"] = receipt
            _progress("TYPED_VERIFY_START",name,proof["rows"])
            await verify_typed_roundtrip(pool, actor, source, proof)
            proof["typed_roundtrip_verified"] = True
            _progress("TYPED_VERIFY_DONE",name,proof["rows"])
            if upload:
                _progress("R2_TABLE_VERIFIED",name,proof["rows"])
        checkpoint = {
            "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "relations": results, "relation_count": len(results),
            "expected_relations": len(TABLE_PKS),
            "blocked_relations": blocked,
            "complete_approved_scope": not blocked,
            "total_source_rows": sum(r["rows"] for r in results),
            "restoration_method": "PG_READ_ONLY_JSON_POPULATE_RECORDSET_EVERY_COLUMN",
            "sql_source_mutations": 0, "supabase_retired": False,
            "d1_source_rows_migrated": 0,
            "auth_sessions_exported": False,
            "operational_cutover_authorized": False,
        }
        if upload:
            path = root / "checkpoint.manifest.json"
            payload = (json.dumps(checkpoint,sort_keys=True,separators=(",",":"))+"\n").encode()
            path.write_bytes(payload)
            proof = await asyncio.to_thread(storage.put_verified_file, path,
                                             category="exports",content_type="application/json")
            if not isinstance(proof,dict) or proof.get("verified") is not True:
                raise ObjectStorageError("R2 checkpoint manifest upload failed")
            returned = root / "checkpoint.download.manifest.json"
            await asyncio.to_thread(storage.download_verified_file,
                proof["key"], returned, expected_sha256=proof["sha256"],
                expected_size=proof["size_bytes"])
            if returned.read_bytes() != payload:
                raise ObjectStorageError("R2 checkpoint manifest readback differs")
            checkpoint["manifest_object"] = proof
            _progress("R2_MANIFEST_VERIFIED","ALL",len(results))
    # Report only source row COUNTS and integrity digests, not any customer row.
    return {
        "status": ("PRIVATE_OPERATIONAL_R2_SOURCE_RESTORE_PROVEN" if not blocked
                    else "PRIVATE_OPERATIONAL_R2_PARTIAL_SOURCE_VERIFIED") if upload
                  else ("LOCAL_OPERATIONAL_SOURCE_TYPED_ROUNDTRIP_VERIFIED" if not blocked
                    else "LOCAL_OPERATIONAL_PARTIAL_SOURCE_VERIFIED"),
        "verified_relations": len(results),
        "expected_relations": len(TABLE_PKS),
        "complete_approved_scope": not blocked,
        "blocked_relations": blocked,
        "source_counts": {r["table"]:r["rows"] for r in results},
        "source_sha256": {r["table"]:r["source_ndjson_sha256"] for r in results},
        "r2_uploaded": upload,
        "manifest_sha256": checkpoint.get("manifest_object",{}).get("sha256") if upload else None,
        "manifest_size_bytes": checkpoint.get("manifest_object",{}).get("size_bytes") if upload else None,
        "postgres_writes": 0, "customer_data_imported_to_d1": False,
        "operational_cutover_authorized": False,
        "auth_sessions_exported": False,
    }
