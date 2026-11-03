"""Independent figure-reference feed with verified R2 copies and SQL fallback.

Only closed, owner-free reference projections leave PostgreSQL. A source image
is *not* a shop/physical-item image; no URL is delivered unless its R2 copy has
an approved rights receipt. Values are nullable, source-derived GBP guides.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import os
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_platform_admin_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .object_storage import ObjectStorageError, configured_object_storage


router = APIRouter(prefix="/api/v1/reference-figures", tags=["reference-figures"])
log = logging.getLogger(__name__)
SYSTEMS = frozenset({"FUNKO_POP", "COLLECTIBLE_FIGURES"})
SCHEMA = "drop-rate-figure-references-v1"
PART_ROWS = 250
MAX_PARTS = 600
MAX_PART_BYTES = 4_000_000
MAX_TOTAL_BYTES = 160_000_000
FIELDS = (
    "provider", "system_code", "language", "provider_id", "name", "manufacturer",
    "franchise", "series_name", "figure_number", "manufacturer_sku", "barcode_gtin",
    "edition", "variant", "exclusive_to", "release_date", "source_url",
    "image_r2_key", "market_value_gbp_minor", "expires_at",
)
KEYS = ("provider", "system_code", "language", "provider_id")
STATE_SQL = """select generation, published_generation, manifest
 from tcg_private.reference_figures_r2_publication where system_code=$1"""
REFERENCE_SQL = """select f.provider,f.system_code,f.language,f.provider_id,f.name,f.manufacturer,
 f.franchise,f.series_name,f.figure_number,f.manufacturer_sku,f.barcode_gtin,
 f.edition,f.variant,f.exclusive_to,f.release_date,f.source_url,
 case when f.image_rights_status='APPROVED' and f.image_rights_evidence_url is not null
   then f.image_r2_key else null end as image_r2_key,
 v.market_value_gbp_minor,v.expires_at
 from tcg.reference_figure_products f
 left join tcg.reference_figure_market_values v using(provider,system_code,language,provider_id)
 where f.system_code=$1
 order by f.provider,f.system_code,f.language,f.provider_id"""
_loaded: dict[tuple[str, int, str], tuple[dict, ...]] = {}
_load_lock = asyncio.Lock()


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"true", "1"}


def _public_row(row: dict) -> dict:
    """Reject private columns, invalid prices and forged media keys."""
    if set(row) != set(FIELDS):
        raise ObjectStorageError("Unexpected figure reference projection")
    if any(not isinstance(row[k], str) or not row[k].strip() for k in KEYS):
        raise ObjectStorageError("Incomplete figure reference identity")
    if row["system_code"] not in SYSTEMS or not row["name"] or not row["manufacturer"]:
        raise ObjectStorageError("Unsupported figure reference")
    if not isinstance(row["source_url"], str) or not row["source_url"].startswith("https://"):
        raise ObjectStorageError("Figure source must be HTTPS")
    value = row["market_value_gbp_minor"]
    if value is not None and (type(value) is not int or value <= 0 or not row["expires_at"]):
        raise ObjectStorageError("Invalid figure market value")
    key = row["image_r2_key"]
    if key is not None and (not isinstance(key, str) or not re.fullmatch(
            r"drop-rate/private-media/[a-f0-9]{64}\.webp", key)):
        raise ObjectStorageError("Figure image is not an approved private R2 media key")
    for field in ("release_date", "expires_at"):
        value = row[field]
        if isinstance(value, (date, datetime)):
            row[field] = value.isoformat()
        elif value is not None and not isinstance(value, str):
            raise ObjectStorageError("Unexpected figure reference date")
    return row


def _payload(rows: list[dict]) -> bytes:
    return json.dumps(rows, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def pack(system_code: str, generation: int, records) -> tuple[dict, list[bytes]]:
    """Create deterministic, bounded content-addressed publication parts."""
    if system_code not in SYSTEMS or type(generation) is not int or generation <= 0:
        raise ValueError("Unknown figure system or generation")
    rows = [_public_row(dict(record)) for record in records]
    rows.sort(key=lambda row: tuple(row[key] for key in KEYS))
    identities = [tuple(row[key] for key in KEYS) for row in rows]
    if len(identities) != len(set(identities)) or any(row["system_code"] != system_code for row in rows):
        raise ObjectStorageError("Figure reference identities are ambiguous")
    parts, descriptors, total = [], [], 0
    for offset in range(0, len(rows), PART_ROWS):
        chunk = rows[offset:offset + PART_ROWS]
        raw = _payload(chunk)
        if not 0 < len(raw) <= MAX_PART_BYTES:
            raise ObjectStorageError("Figure reference part exceeds capacity")
        parts.append(raw)
        descriptors.append({"sha256": _digest(raw), "rows": len(chunk), "raw_bytes": len(raw)})
        total += len(raw)
    manifest = {"schema": SCHEMA, "system_code": system_code, "generation": generation,
                "count": len(rows), "raw_bytes": total, "parts": descriptors}
    validate_manifest(manifest)
    return manifest, parts


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "system_code", "generation", "count", "raw_bytes", "parts"}:
        raise ObjectStorageError("Invalid figure R2 manifest")
    if manifest["schema"] != SCHEMA or manifest["system_code"] not in SYSTEMS:
        raise ObjectStorageError("Unexpected figure R2 publication")
    if (type(manifest["generation"]) is not int or manifest["generation"] <= 0
            or type(manifest["count"]) is not int or manifest["count"] < 0
            or type(manifest["raw_bytes"]) is not int or manifest["raw_bytes"] < 0
            or not isinstance(manifest["parts"], list)
            or len(manifest["parts"]) > MAX_PARTS):
        raise ObjectStorageError("Unbounded figure R2 manifest")
    seen = set()
    for part in manifest["parts"]:
        if (not isinstance(part, dict) or set(part) != {"sha256", "rows", "raw_bytes"}
                or not isinstance(part["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", part["sha256"])
                or part["sha256"] in seen
                or type(part["rows"]) is not int or not 0 < part["rows"] <= PART_ROWS
                or type(part["raw_bytes"]) is not int
                or not 0 < part["raw_bytes"] <= MAX_PART_BYTES):
            raise ObjectStorageError("Invalid figure R2 part")
        seen.add(part["sha256"])
    if (sum(p["rows"] for p in manifest["parts"]) != manifest["count"]
            or sum(p["raw_bytes"] for p in manifest["parts"]) != manifest["raw_bytes"]
            or manifest["raw_bytes"] > MAX_TOTAL_BYTES):
        raise ObjectStorageError("Incomplete figure R2 publication")
    return manifest


def unpack(manifest: dict, raw_parts: list[bytes]) -> tuple[dict, ...]:
    validate_manifest(manifest)
    if len(raw_parts) != len(manifest["parts"]):
        raise ObjectStorageError("Missing figure reference part")
    result, identities = [], set()
    for descriptor, raw in zip(manifest["parts"], raw_parts, strict=True):
        if (len(raw) != descriptor["raw_bytes"] or _digest(raw) != descriptor["sha256"]):
            raise ObjectStorageError("Corrupt figure reference part")
        try:
            items = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ObjectStorageError("Invalid figure reference JSON") from exc
        if not isinstance(items, list) or len(items) != descriptor["rows"]:
            raise ObjectStorageError("Figure reference row count differs")
        for item in items:
            row = _public_row(item) if isinstance(item, dict) else None
            if row is None or row["system_code"] != manifest["system_code"]:
                raise ObjectStorageError("Cross-system figure reference")
            identity = tuple(row[key] for key in KEYS)
            if identity in identities:
                raise ObjectStorageError("Duplicate figure reference across R2 parts")
            identities.add(identity)
            result.append(row)
    if len(result) != manifest["count"]:
        raise ObjectStorageError("Incomplete figure reference data")
    return tuple(sorted(result, key=lambda row: tuple(row[key] for key in KEYS)))


async def prepare_publication(connection, system_code: str) -> tuple[dict, list[bytes]]:
    """Read one short, immutable DB snapshot; do not perform network I/O here."""
    if system_code not in SYSTEMS:
        raise ValueError("Unsupported figure system")
    state = await connection.fetchrow(STATE_SQL, system_code)
    if state is None:
        raise ObjectStorageError("Figure R2 migration or registry is missing")
    generation = state["generation"]
    rows = await connection.fetch(REFERENCE_SQL, system_code)
    return pack(system_code, generation, rows)


async def upload_publication(storage, manifest: dict, parts: list[bytes]) -> dict:
    """Verify every uploaded byte after the DB snapshot transaction is closed."""
    if storage is None:
        raise ObjectStorageError("R2 is not configured")
    validate_manifest(manifest)
    # Put/read-back occurs *before* the DB points at these objects. No deletes.
    for descriptor, raw in zip(manifest["parts"], parts, strict=True):
        receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, raw)
        if (receipt["sha256"] != descriptor["sha256"] or not receipt["verified"]):
            raise ObjectStorageError("Figure R2 write receipt does not match")
        observed = await asyncio.to_thread(storage.read_verified_reference_snapshot, descriptor["sha256"])
        if observed != raw:
            raise ObjectStorageError("Figure R2 readback differs")
    unpack(manifest, parts)
    return manifest


async def _read_r2(storage, manifest: dict) -> tuple[dict, ...]:
    data = []
    for part in manifest["parts"]:
        data.append(await asyncio.to_thread(storage.read_verified_reference_snapshot, part["sha256"]))
    return unpack(manifest, data)


async def _select_rows(connection, system_code: str, query: str, limit: int, offset: int):
    return [dict(row) for row in await connection.fetch(
        """select * from (""" + REFERENCE_SQL.replace("order by f.provider,f.system_code,f.language,f.provider_id", "") + """
        ) r where ($2::text='' or r.name ilike '%' || $2 || '%'
                 or r.series_name ilike '%' || $2 || '%'
                 or r.figure_number ilike '%' || $2 || '%')
        order by r.provider,r.system_code,r.language,r.provider_id
        limit $3 offset $4""", system_code, query, limit + 1, offset)]


def _display_row(row: dict, storage, now: datetime) -> dict:
    item = dict(row)
    if item.get("market_value_gbp_minor") is not None:
        expires = item.get("expires_at")
        try:
            date_value = datetime.fromisoformat(expires) if isinstance(expires, str) else expires
            if date_value is None or date_value.tzinfo is None or date_value <= now:
                item["market_value_gbp_minor"] = None
        except (TypeError, ValueError):
            item["market_value_gbp_minor"] = None
    key = item.pop("image_r2_key", None)
    item["image_url"] = None
    if key and storage:
        try:
            item["image_url"] = storage.signed_media_url(key, expires_seconds=1800)
        except ObjectStorageError:
            pass
    item.pop("expires_at", None)
    return item


@router.get("")
async def list_figure_references(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    system_code: str = Query(default="FUNKO_POP", max_length=80),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    if not _flag("TCG_REFERENCE_FIGURES_ENABLED"):
        raise HTTPException(404, "Figure reference catalogue is not enabled")
    if system_code not in SYSTEMS:
        raise HTTPException(422, "Unknown figure reference system")
    query = q.strip()
    storage = configured_object_storage()
    rows = None
    source = "POSTGRES_FALLBACK"
    async with user_connection(request.app.state.db_pool, user.user_id,
                               request.state.request_id, readonly_snapshot=True) as conn:
        if _flag("TCG_REFERENCE_FIGURES_R2_DELIVERY_ENABLED") and storage:
            state = await conn.fetchrow(STATE_SQL, system_code)
            if state and state["generation"] == state["published_generation"] and state["manifest"]:
                try:
                    manifest = validate_manifest(state["manifest"])
                    if manifest["generation"] != state["generation"] or manifest["system_code"] != system_code:
                        raise ObjectStorageError("Stale figure R2 publication")
                    cache_key = (system_code, state["generation"], _digest(_payload(manifest)))
                    if cache_key not in _loaded:
                        async with _load_lock:
                            if cache_key not in _loaded:
                                content = await _read_r2(storage, manifest)
                                _loaded.clear()  # At most one verified generation in process memory.
                                _loaded[cache_key] = content
                    rows = [row for row in _loaded[cache_key]
                            if not query or query.casefold() in (row["name"] or "").casefold()
                            or query.casefold() in (row["series_name"] or "").casefold()
                            or query.casefold() in (row["figure_number"] or "").casefold()]
                    rows = rows[offset:offset + limit + 1]
                    source = "R2_VERIFIED"
                except (ObjectStorageError, KeyError, TypeError, ValueError) as exc:
                    log.warning("FIGURE_R2_FALLBACK type=%s", type(exc).__name__)
        if rows is None:
            rows = await _select_rows(conn, system_code, query, limit, offset)
    now = datetime.now(timezone.utc)
    items = [_display_row(row, storage, now) for row in rows[:limit]]
    return jsonable_encoder({"items": items, "has_more": len(rows) > limit,
                             "offset": offset, "source": source,
                             "disclaimer": "Reference data only; not owned stock or Shopify listings"})


@router.post("/admin/publish")
async def publish_figure_references(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    admin: Annotated[dict, Depends(require_platform_admin_request)],
    system_code: str = Query(max_length=80),
):
    if not _flag("TCG_REFERENCE_FIGURES_R2_PUBLISH_ENABLED"):
        raise HTTPException(404, "Figure R2 publication is not enabled")
    if system_code not in SYSTEMS:
        raise HTTPException(422, "Unknown figure reference system")
    storage = configured_object_storage()
    if storage is None:
        raise HTTPException(503, "R2 is not configured")
    # Read under a bounded snapshot, release the connection during R2 I/O.
    async with user_connection(request.app.state.db_pool, user.user_id,
                               request.state.request_id, readonly_snapshot=True) as conn:
        manifest, parts = await prepare_publication(conn, system_code)
    await upload_publication(storage, manifest, parts)
    # The compare-and-set denies a stale snapshot if an import or a valuation
    # changed either source table during the verified upload.
    async with user_connection(request.app.state.db_pool, user.user_id,
                               request.state.request_id) as conn:
        published = await conn.fetchval("""update tcg_private.reference_figures_r2_publication
          set published_generation=$2,manifest=$3::jsonb,published_at=clock_timestamp()
          where system_code=$1 and generation=$2 returning published_generation""",
          system_code, manifest["generation"], json.dumps(manifest))
    if published is None:
        raise HTTPException(409, "Figure references changed during R2 publication; retry")
    return {"system_code": system_code, "generation": published,
            "references": manifest["count"], "parts": len(manifest["parts"]),
            "readback_verified": True}
