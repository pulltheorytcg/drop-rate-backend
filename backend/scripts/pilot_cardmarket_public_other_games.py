"""Bounded read-only official daily files for Yu-Gi-Oh! and Disney Lorcana.

This is public-source discovery, NOT a price refresh or data publication.
No credentials, Supabase, R2, Shopify or individual price rows are output.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import httpx

from app.cardmarket_public_feed_availability import GAMES, SourceRejected, source_availability

ROOT = "https://downloads.s3.cardmarket.com/productCatalog"
MAX_FILE_BYTES = 48_000_000
MAX_TOTAL_BYTES = 130_000_000


async def get_public_json(client, url):
    if not url.startswith(ROOT + "/"):
        raise SourceRejected("Unexpected Cardmarket download URL")
    digest = hashlib.sha256()
    chunks, total = [], 0
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        if str(response.url) != url:
            raise SourceRejected("Unexpected redirect or source host")
        declared = response.headers.get("content-length")
        if declared and declared.isdecimal() and int(declared) > MAX_FILE_BYTES:
            raise SourceRejected("Source exceeds file byte bound")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise SourceRejected("Source exceeds file byte bound")
            digest.update(chunk)
            chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except ValueError as exc:
        raise SourceRejected("Invalid official JSON payload") from exc
    if not isinstance(payload, dict):
        raise SourceRejected("Official JSON root must be an object")
    return payload, {"sha256": digest.hexdigest(), "bytes": total}


async def probe():
    now = datetime.now(timezone.utc)
    results, total_bytes = [], 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=15,pool=15),
                                 headers={"Accept":"application/json",
                                          "User-Agent":"DropRatePublicPricingPilot/1.0"}) as client:
        for game, config in GAMES.items():
            game_id = config["id"]
            product_url = f"{ROOT}/productList/products_singles_{game_id}.json"
            guide_url = f"{ROOT}/priceGuide/price_guide_{game_id}.json"
            products, p_receipt = await get_public_json(client, product_url)
            guides, g_receipt = await get_public_json(client, guide_url)
            total_bytes += p_receipt["bytes"] + g_receipt["bytes"]
            if total_bytes > MAX_TOTAL_BYTES:
                raise SourceRejected("Multiple game files exceed combined byte bound")
            result = source_availability(game=game, catalogue=products, guides=guides,
                                         now=datetime.now(timezone.utc))
            result["source_receipts"] = {"products":p_receipt,"guide":g_receipt}
            results.append(result)
    return {"status": "NO_PUBLICATION", "public_game_sources": results,
            "exact_printing_valuations": 0, "database_writes":0, "r2_writes":0,
            "shopify_writes":0}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), sort_keys=True))
