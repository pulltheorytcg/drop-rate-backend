"""Read-only newest Pokémon Cardmarket source proof, no database secrets or writes.

RUN: PYTHONPATH=backend python backend/scripts/probe_me06_cardmarket_sources.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import httpx

from app.new_pokemon_price_source import select_samples, detail_evidence, SET_ID
from app.reference_feeds import ReferenceFeeds
from scripts.audit_cardmarket_bulk_feed import _read_source, _HOST


async def run() -> dict:
    feed = ReferenceFeeds()
    try:
        manifest = await feed.get(f"https://api.tcgdex.net/v2/en/sets/{SET_ID}")
        samples = select_samples(manifest)
        details = []
        # Small sequential bounded source-ID sample; do not crawl the entire set.
        for sample in samples:
            details.append(await feed.get(
                f"https://api.tcgdex.net/v2/en/cards/{sample['id']}"))
    finally:
        await feed.close()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0,connect=15.0,pool=15.0),
        follow_redirects=False,
        headers={"User-Agent":"DropRateOfficialSourceAudit/1.0","Accept":"application/json"}
    ) as client:
        products, p_hash = await _read_source(client,_HOST+"productList/products_singles_6.json")
        guides, g_hash = await _read_source(client,_HOST+"priceGuide/price_guide_6.json")
    receipt = detail_evidence(manifest,details,products,guides,now=datetime.now(timezone.utc))
    receipt["source_sha256"] = {"products":p_hash["sha256"],"guide":g_hash["sha256"]}
    receipt["requests"] = {"tcgdex":len(details)+1,"cardmarket":2}
    return receipt


if __name__ == "__main__":
    try:
        print("POKEMON_ME06_PRICE_SOURCE_PROBE "+json.dumps(asyncio.run(run()),sort_keys=True),flush=True)
    except Exception as exc:
        print("POKEMON_ME06_PRICE_SOURCE_PROBE "+json.dumps({
            "status":"FAILED_CLOSED","error_type":type(exc).__name__,
            "db_writes":0,"uk_sold_market_values":0
        }),flush=True)
        raise SystemExit(2) from None
