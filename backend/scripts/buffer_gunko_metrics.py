"""Read-only metrics check for the two completed Gunko pilot posts."""
from __future__ import annotations

import asyncio
import json
import os

from app.buffer_post_metrics import BufferMetricsError, get_post_metrics


PREFIX = "DROP_RATE_GUNKO_METRICS "
POSTS = (
    {
        "post_id": "6ac29d1f6ae9cbb01a564d9f",
        "channel_id": "6ac1a5deea19ca0bde6c81b7",
        "service": "instagram",
    },
    {
        "post_id": "6ac29d1ffe1389e4133cde22",
        "channel_id": "6ac1a66eea19ca0bde6c89ac",
        "service": "tiktok",
    },
)


async def run() -> dict:
    key = os.environ.get("TCG_BUFFER_API_KEY", "").strip()
    results = []
    for item in POSTS:
        try:
            result = await get_post_metrics(
                key,
                post_id=item["post_id"],
                expected_channel_id=item["channel_id"],
                expected_service=item["service"],
            )
            results.append(result)
        except BufferMetricsError as exc:
            results.append(
                {
                    "post_id": item["post_id"],
                    "channel_id": item["channel_id"],
                    "service": item["service"],
                    "error": exc.code,
                }
            )
    return {
        "probe_version": "gunko-post-metrics-v1",
        "results": results,
    }


if __name__ == "__main__":
    print(
        PREFIX + json.dumps(asyncio.run(run()), sort_keys=True, separators=(",", ":")),
        flush=True,
    )
