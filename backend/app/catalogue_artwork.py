"""Small, bounded browse thumbnails; recognition and detail retain originals."""
from __future__ import annotations

import asyncio
import io
import time
from collections import OrderedDict

from PIL import Image

from .recognition_images import ReferenceImagePayload, reference_image_bytes

MAX_BYTES = 32_000_000
MAX_ENTRIES = 1024
TTL = 6 * 60 * 60
_cache: OrderedDict[str, tuple[float, ReferenceImagePayload]] = OrderedDict()
_inflight: dict[str, asyncio.Task] = {}


def thumbnail(payload):
    with Image.open(io.BytesIO(payload.data)) as source:
        source.thumbnail((384, 540), Image.Resampling.LANCZOS)
        image = source.convert('RGBA' if 'A' in source.getbands() else 'RGB')
        output = io.BytesIO()
        image.save(output, format='WEBP', quality=78, method=3)
    return ReferenceImagePayload('image/webp', output.getvalue())


async def reference_thumbnail(url):
    cached = _cache.get(url)
    if cached and cached[0] > time.monotonic():
        _cache.move_to_end(url)
        return cached[1]

    async def fetch():
        try:
            original = await reference_image_bytes(url)
            if original is None:
                return None
            payload = await asyncio.to_thread(thumbnail, original)
            _cache[url] = (time.monotonic() + TTL, payload)
            _cache.move_to_end(url)
            total = sum(len(row[1].data) for row in _cache.values())
            while len(_cache) > MAX_ENTRIES or total > MAX_BYTES:
                _, removed = _cache.popitem(last=False)
                total -= len(removed[1].data)
            return payload
        finally:
            _inflight.pop(url, None)

    task = _inflight.get(url)
    if task is None:
        if len(_inflight) >= 64:
            return None
        task = asyncio.create_task(fetch())
        _inflight[url] = task
    return await asyncio.shield(task)


async def close_artwork_tasks():
    tasks = list(_inflight.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _inflight.clear()
