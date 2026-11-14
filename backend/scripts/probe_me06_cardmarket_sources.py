"""Read-only newest Pokémon Cardmarket source proof, no database secrets or writes.

RUN: PYTHONPATH=backend python backend/scripts/probe_me06_cardmarket_sources.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import httpx

from app.new_pokemon_price_source import select_samples, detail_evidence, release_listing_evidence, SET_ID
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
        packaging, n_hash = await _read_source(client,_HOST+"productList/products_nonsingles_6.json")
    receipt = detail_evidence(manifest,details,products,guides,now=datetime.now(timezone.utc))
    receipt["release_presence"] = release_listing_evidence(manifest,products,packaging,now=datetime.now(timezone.utc))
    receipt["source_sha256"] = {"products":p_hash["sha256"],"guide":g_hash["sha256"],"non_singles":n_hash["sha256"]}
    receipt["requests"] = {"tcgdex":len(details)+1,"cardmarket":3}
    return receipt



async def release_only() -> dict:
    """Source-title availability with zero TCGdex calls after upstream errors.

    The pinned name was independently verified in the first live me06 probe.
    This deliberately does not fetch guide amounts or match single printings.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0,connect=15.0,pool=15.0),
        follow_redirects=False,
        headers={"User-Agent":"DropRateOfficialReleaseProbe/1.0",
                 "Accept":"application/json"},
    ) as client:
        products, p_hash = await _read_source(
            client,_HOST+"productList/products_singles_6.json")
        nonsingles, n_hash = await _read_source(
            client,_HOST+"productList/products_nonsingles_6.json")
    report=release_listing_evidence(
        {"id":SET_ID,"name":"Delta Reign"},products,nonsingles,
        now=datetime.now(timezone.utc))
    return {"status":"RELEASE_TITLE_SOURCE_ONLY_NOT_A_PRICE",
            "set_id":SET_ID,"set_name":"Delta Reign",
            "pinned_set_title_proof":"SOURCE_ONLY_TC GDEX_ME06_20261114".replace(" ",""),
            "release_presence":report,
            "source_sha256":{"singles":p_hash["sha256"],
                             "nonsingles":n_hash["sha256"]},
            "requests":{"tcgdex":0,"cardmarket":2},
            "db_writes":0,"uk_sold_market_values":0}


if __name__ == "__main__":
    import argparse
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--release-only",action="store_true",
                     help="Official Cardmarket set-title diagnostic, no TCGdex calls")
    args=cli.parse_args()
    try:
        report=asyncio.run(release_only() if args.release_only else run())
        print("POKEMON_ME06_PRICE_SOURCE_PROBE "+json.dumps(report,sort_keys=True),flush=True)
    except Exception as exc:
        print("POKEMON_ME06_PRICE_SOURCE_PROBE "+json.dumps({
            "status":"FAILED_CLOSED","error_type":type(exc).__name__,
            "db_writes":0,"uk_sold_market_values":0
        }),flush=True)
        raise SystemExit(2) from None
