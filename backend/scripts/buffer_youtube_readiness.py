"""Operator-run, read-only Buffer YouTube readiness probe.

This script never creates, edits, schedules or deletes Buffer content. It is safe
to run temporarily in a deployment pre-check because output is restricted to
non-secret channel metadata and fixed error codes.
"""
from __future__ import annotations

import asyncio
import json
import os

from app.buffer_channel_readiness import BufferReadinessError, get_youtube_readiness
from app.social_pilot import MANIFEST_PATH


PREFIX = "DROP_RATE_BUFFER_YOUTUBE_READINESS "


async def run() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    organization_id = manifest["organization_id"]
    key = os.environ.get("TCG_BUFFER_API_KEY", "").strip()

    try:
        result = await get_youtube_readiness(
            key,
            organization_id=organization_id,
        )
        return {
            "probe_version": "buffer-youtube-readiness-v1",
            "organization_id": organization_id,
            **result,
        }
    except BufferReadinessError as exc:
        return {
            "probe_version": "buffer-youtube-readiness-v1",
            "organization_id": organization_id,
            "ready": False,
            "reason": exc.code,
            "blockers": [],
            "channel": None,
        }


if __name__ == "__main__":
    # Do not print environment values, provider bodies, request headers or stack traces.
    print(PREFIX + json.dumps(asyncio.run(run()), sort_keys=True, separators=(",", ":")), flush=True)
