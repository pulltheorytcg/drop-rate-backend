"""Founder-only, atomic replacement of an uncommitted import preview.

The private database capability deliberately does not grant the runtime role
general DELETE access or permission to rewrite import source metadata.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder

MAX_REBUILD_CANDIDATES = 10_000
MAX_REBUILD_BYTES = 32 * 1024 * 1024


def rebuild_enabled(request: Request) -> bool:
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "import_preview_rebuild_enabled", False) is True


def validate_rebuild_batch(batch: Any, *, version: int, source_sha256: str) -> None:
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch["version"] != version:
        raise HTTPException(status_code=409, detail={
            "message": "Import batch changed; reload it before rebuilding",
            "current_version": batch["version"],
        })
    if batch["status"] != "PREVIEW" or batch.get("committed_at") is not None:
        raise HTTPException(status_code=409, detail="Only uncommitted PREVIEW batches can be rebuilt")
    if batch.get("automatic_intake") or batch.get("last_auto_apply_version") is not None:
        raise HTTPException(status_code=409, detail="Seller Hub automatic-intake batches cannot be rebuilt")
    if batch["source_sha256"] != source_sha256:
        raise HTTPException(status_code=409, detail="Rebuilding requires the exact original file content")
    if not batch.get("filename") or not batch["filename"].lower().endswith((".csv", ".tsv")):
        raise HTTPException(status_code=409, detail="This legacy batch has no supported source filename")


async def replace_preview(connection: asyncpg.Connection, *, actor_id: UUID,
                          owner_id: UUID, batch_id: UUID, version: int,
                          source_sha256: str, preview: dict) -> dict:
    candidates = preview["candidates"]
    if not 1 <= len(candidates) <= MAX_REBUILD_CANDIDATES:
        raise HTTPException(status_code=422, detail="Rebuild is limited to 10,000 preview rows including reconciliation rows")
    encoded = json.dumps(jsonable_encoder(candidates), separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_REBUILD_BYTES:
        raise HTTPException(status_code=422, detail="Rebuilt preview exceeds the supported size")
    result = await connection.fetchval(
        """select tcg_private.replace_import_preview(
            $1::uuid,$2::uuid,$3::uuid,$4::integer,$5::text,$6::text,
            $7::integer,$8::integer,$9::jsonb,$10::jsonb
        )""",
        actor_id, owner_id, batch_id, version, source_sha256, preview["adapter"],
        preview["source_rows"], preview["physical_units"],
        json.dumps(preview["warnings"]), encoded,
    )
    return json.loads(result) if isinstance(result, str) else dict(result)
