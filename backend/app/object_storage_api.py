"""Admin-only, read-only object storage readiness probe.

Access is restricted by the parent FastAPI router dependency. n8n must use a
governed backend action, not direct S3 credentials, when automation is enabled.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from .object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage

router = APIRouter(prefix="/api/v1/object-storage", tags=["object-storage"])


@router.get("/status")
async def status(probe: bool = Query(default=False)) -> dict:
    try:
        config = ObjectStorageConfig.from_env()
    except ObjectStorageError:
        return {"enabled": True, "status": "INVALID_CONFIGURATION"}
    if config is None:
        return {"enabled": False, "status": "NOT_CONFIGURED"}
    if not probe:
        return {"enabled": True, "status": "CONFIGURED_NOT_VERIFIED"}
    try:
        await asyncio.to_thread(S3ObjectStorage(config).connectivity)
    except Exception:
        # Provider errors may embed endpoint or token data: do not expose them.
        return {"enabled": True, "status": "CONNECTIVITY_FAILED"}
    return {"enabled": True, "status": "REACHABLE"}
