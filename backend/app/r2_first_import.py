"""Explicitly enabled, bounded public-source → private R2 metadata ingestion.

No reference_cards/reference_sets/market table bulk writes. The final SQL
transaction is a compare-and-swap publication pointer plus automatic audit.
Existing data and old immutable R2 generations are retained for rollback.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from uuid import UUID

import httpx
from fastapi import HTTPException

from . import r2_first_catalogue as codec, r2_first_service as service
from .access_control import require_platform_admin
from .db import user_connection, DATABASE_WRITE_READY_SQL
from .r2_first_sources import fetch_source, source_descriptor, SourcePermissionError

log = logging.getLogger(__name__)
APPROVED_METADATA_SOURCES = frozenset({"ygoprodeck", "lorcast", "mtgjson", "cardcollectorcapital", "reviewed_figures"})
REFRESH_SECONDS = 172800  # Provider bulk cache is two days. No per-scan requests.
SOURCE_REFRESH_SECONDS = {"lorcast": 604800, "mtgjson": 604800, "cardcollectorcapital": 604800,
                          "reviewed_figures": 604800}


def configured_sources():
    raw = os.getenv("TCG_R2_FIRST_IMPORT_SOURCES", "").strip()
    requested = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if set(requested) - APPROVED_METADATA_SOURCES:
        raise SourcePermissionError("One or more requested source permissions need review")
    return requested


def _permission(manifest):
    descriptor = source_descriptor(manifest["provider"], manifest["language"])
    if (manifest["provider"] not in APPROVED_METADATA_SOURCES
            or descriptor.permission_status != "METADATA_ACCESS_DOCUMENTED"
            or manifest["language"] != descriptor.catalogue_language
            or (descriptor.system_code, descriptor.source_url, descriptor.permission_ref) !=
               (manifest["system_code"], manifest["source_url"], manifest["permission_ref"])):
        raise SourcePermissionError("This source partition has not passed permission review")


async def publish_verified(pool, actor, snapshot, *, expected_generation=0, active=True):
    """Switch only to a fully verified generation; same method permits rollback.

The caller must load snapshot through codec.load_catalogue (R2 readback) first.
No network access occurs while holding the short SQL transaction/row lock.
"""
    manifest = snapshot.manifest
    _permission(manifest)
    digest = snapshot.manifest_digest
    set_count = len(await asyncio.to_thread(snapshot.sets))
    released_count = (await asyncio.to_thread(snapshot.search, limit=1))["total"]
    scope = tuple(manifest[name] for name in ("provider", "system_code", "language"))
    async with user_connection(pool, actor, "r2-first-publication") as connection:
        await require_platform_admin(connection)
        if not await connection.fetchval(DATABASE_WRITE_READY_SQL):
            raise HTTPException(503, "Database is read-only; publication was not changed")
        await connection.execute("select pg_advisory_xact_lock(847220122)")
        await connection.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",
                                 "r2-first-publication:" + json.dumps(scope))
        old = await connection.fetchrow("""
            select * from tcg_private.r2_first_catalogue_publications
            where provider=$1 and system_code=$2 and language=$3 for update
            """, *scope)
        generation = int(old["generation"]) if old else 0
        unchanged = (old and old["manifest_sha256"] == digest and old["active"] == active
                     and old["released_record_count"] == released_count
                     and old["set_count"] == set_count and old["raw_bytes"] == manifest["raw_bytes"])
        if generation != expected_generation:
            # A retry of an already committed generation is harmless.
            if unchanged:
                return {"status": "CURRENT", "generation": generation, "manifest_sha256": digest,
                        "record_count": manifest["record_count"], "set_count": set_count}
            raise HTTPException(409, "Catalogue generation changed; publication not overwritten")
        if unchanged:
            return {"status": "CURRENT", "generation": generation, "manifest_sha256": digest,
                    "record_count": manifest["record_count"], "set_count": set_count}
        other_bytes = await connection.fetchval("""
            select coalesce(sum(raw_bytes),0) from tcg_private.r2_first_catalogue_publications
            where active and (provider,system_code,language)<>($1,$2,$3)
            """, *scope)
        if active and int(other_bytes)+manifest["raw_bytes"] > service.MAX_ACTIVE_RAW_BYTES:
            raise HTTPException(409, "Aggregate catalogue index budget needs review")
        values = (*scope, digest, manifest["source_revision"], manifest["permission_ref"],
                  manifest["source_url"], manifest["record_count"], set_count,
                  generation+1, active, actor, released_count, manifest["raw_bytes"])
        if old:
            await connection.execute("""
                update tcg_private.r2_first_catalogue_publications set manifest_sha256=$4,
                  source_revision=$5,permission_ref=$6,source_url=$7,record_count=$8,set_count=$9,
                  generation=$10,active=$11,published_by=$12,published_at=now(),
                  released_record_count=$13,raw_bytes=$14
                where provider=$1 and system_code=$2 and language=$3
                """, *values)
        else:
            if await connection.fetchval(
                    "select count(*) from tcg_private.r2_first_catalogue_publications") >= service.MAX_PARTITIONS:
                raise HTTPException(409, "Catalogue partition capacity needs review")
            await connection.execute("""
                insert into tcg_private.r2_first_catalogue_publications
                (provider,system_code,language,manifest_sha256,source_revision,permission_ref,
                 source_url,record_count,set_count,generation,active,published_by,released_record_count,raw_bytes)
                values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """, *values)
    return {"status": "PUBLISHED" if active else "DEACTIVATED", "generation": generation+1,
            "manifest_sha256": digest, "record_count": manifest["record_count"], "set_count": set_count}


async def import_source(pool, actor, source, *, object_store=None, client=None):
    descriptor = source_descriptor(source)
    if source not in configured_sources():
        raise SourcePermissionError("Source import is not explicitly enabled")
    # Access and current generation are read before any public HTTP/R2 writes.
    async with user_connection(pool, actor, "r2-first-import-preflight") as connection:
        await require_platform_admin(connection)
        if not await connection.fetchval(DATABASE_WRITE_READY_SQL):
            raise HTTPException(503, "Database is read-only; import not started")
        old = await connection.fetchrow("""
            select * from tcg_private.r2_first_catalogue_publications
            where provider=$1 and system_code=$2 and language=$3
            """, descriptor.provider, descriptor.system_code, descriptor.catalogue_language)
        if old and not old["active"]:
            return {"status": "DISABLED", "source": source}
        refresh_seconds = SOURCE_REFRESH_SECONDS.get(source, REFRESH_SECONDS)
        if old and old["published_at"] > datetime.now(timezone.utc)-timedelta(seconds=refresh_seconds):
            return {"status": "CURRENT", "source": source, "record_count": old["record_count"],
                    "manifest_sha256": old["manifest_sha256"], "generation": old["generation"]}
    if client is None:
        async with httpx.AsyncClient() as public_client:
            fetched = await fetch_source(source, public_client, approved_sources=APPROVED_METADATA_SOURCES)
    else:
        fetched = await fetch_source(source, client, approved_sources=APPROVED_METADATA_SOURCES)
    bundle = await asyncio.to_thread(codec.prepare_catalogue, fetched.records,
        provider=fetched.provider, system_code=fetched.system_code, language=descriptor.catalogue_language,
        source_url=fetched.source_url, source_revision=fetched.source_revision,
        permission_ref=descriptor.permission_ref)
    # The validated shards now hold the normalized facts. Do not retain the
    # full provider object graph during upload and cold index reconstruction.
    del fetched
    object_store = object_store or service.storage()
    manifest = await codec.upload_and_verify(bundle, object_store)
    del bundle
    # Prove cold reconstruction and search before making this generation active.
    snapshot = await codec.load_catalogue(manifest, object_store)
    try:
        smoke = await asyncio.to_thread(snapshot.search, limit=1)
        if smoke['total'] and not smoke['items']:
            raise codec.R2FirstCatalogueError('Reconstructed search failed')
        report = await publish_verified(pool, actor, snapshot,
                                        expected_generation=int(old["generation"]) if old else 0)
        return {**report, "source": source, "sql_bulk_rows_written": 0,
                "metadata_only": True, "raw_bytes": manifest["raw_bytes"],
                "cold_search_verified": True, "searchable_records": smoke['total']}
    finally:
        snapshot.close()


async def run_once(pool, actor):
    requested = configured_sources()
    if not requested:
        return []
    # A dedicated session-level advisory lock prevents overlapping deployments
    # from downloading/importing the same source. No open SQL transaction spans
    # HTTP/R2 work. A dropped session releases its lock; CAS still protects writes.
    async with pool.acquire() as lock_connection:
        acquired = await lock_connection.fetchval("select pg_try_advisory_lock(847220121)")
        if not acquired:
            return [{"status": "ALREADY_RUNNING"}]
        try:
            reports = []
            for source in requested:
                try:
                    report = await import_source(pool, UUID(str(actor)), source)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # One denied/unavailable feed cannot hide successfully
                    # verified sources or starve later independent imports.
                    # There is no immediate retry, and no good pointer is erased.
                    report = {"status": "FAILED", "source": source,
                              "error_type": type(exc).__name__}
                reports.append(report)
                log.warning("R2_FIRST_IMPORT %s", json.dumps(report, sort_keys=True))
            return reports
        finally:
            await lock_connection.execute("select pg_advisory_unlock(847220121)")


async def run_loop(pool, actor):
    while True:
        try:
            await run_once(pool, actor)
            if service.enabled():
                await service.prewarm(pool, UUID(str(actor)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Failed or denied sources never retry rapidly or erase a good pointer.
            log.error("R2_FIRST_IMPORT_FAILED type=%s", type(exc).__name__)
        await asyncio.sleep(REFRESH_SECONDS)
