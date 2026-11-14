"""One-shot official Cardmarket whole-Pokémon crosswalk using production read ONLY.

Only the protected GitHub Actions job passes a Supabase database password.
The query references public canonical catalogue/price-source tables only,
never inventory, owners, auth, settlements or Shopify data. Output contains
aggregate coverage counts and hash receipts, no vendor prices or secrets.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import traceback
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import asyncpg
import httpx

from app.cardmarket_bulk_crosswalk import match_pokemon_bulk, MAX_LINKS
from app.cardmarket_bulk_rollout import approved_full_source_digest
from app.cardmarket_bulk_context import prepare_cardmarket_context
from app.fx import EcbHistoricalFxProvider
from scripts.audit_cardmarket_bulk_feed import _HOST, _read_source
from scripts.pilot_cardmarket_live_crosswalk import SOURCE_LINKS_SQL

PROJECT = "ozrxenrdladkooixutmm"


async def run() -> dict:
    password = os.getenv("SUPABASE_DB_PASSWORD", "")
    if not password or len(password) < 12:
        raise RuntimeError("Protected read-only database credential is absent")
    if "tcg.inventory_items" in SOURCE_LINKS_SQL or "tcg.owners" in SOURCE_LINKS_SQL:
        raise RuntimeError("Unexpected owner/physical data in read-only source query")
    dsn = ("postgresql://postgres." + PROJECT + ":" + quote(password, safe="") +
           "@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require")
    conn = await asyncpg.connect(
        dsn=dsn, command_timeout=90,
        server_settings={"application_name":"cardmarket-ci-source-crosswalk-readonly",
                         "default_transaction_read_only":"on",
                         "statement_timeout":"85000"})
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            if await conn.fetchval("show transaction_read_only") != "on":
                raise RuntimeError("READ ONLY transaction not enforced")
            rows = await conn.fetch(SOURCE_LINKS_SQL)
            if len(rows) > MAX_LINKS:
                raise RuntimeError("Source mapping bounded query limit exceeded")
            links = [dict(row) for row in rows]
    finally:
        await conn.close()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90, connect=15, pool=15), follow_redirects=False,
        headers={"User-Agent":"DropRateOfficialCardmarketReadonlyFullCrosswalk/1.0",
                 "Accept":"application/json"}
    ) as client:
        products, p_receipt = await _read_source(
            client, _HOST + "productList/products_singles_6.json")
        guides, g_receipt = await _read_source(
            client, _HOST + "priceGuide/price_guide_6.json")
    now = datetime.now(timezone.utc)
    match = match_pokemon_bulk(links=links,products_export=products,
                               price_export=guides,now=now)
    at = datetime.fromisoformat(guides["createdAt"].replace("Z","+00:00"))
    fx = await EcbHistoricalFxProvider().quote(
        base_currency="EUR",quote_currency="GBP",at=at-timedelta(days=1))
    prepared = prepare_cardmarket_context(
        candidates=match["candidates"],fx=fx,guide_at=at,now=datetime.now(timezone.utc),
        product_sha256=p_receipt["sha256"],guide_sha256=g_receipt["sha256"])
    by_language=Counter(c["language"] for c in match["candidates"])
    by_source=Counter(c["source_link"] for c in match["candidates"])
    digest = approved_full_source_digest(match["candidates"])
    return {
        "status":"READ_ONLY_FULL_REFERENCE_AUDIT_COMPLETE",
        "official_product_sha256":p_receipt["sha256"],
        "official_guide_sha256":g_receipt["sha256"],
        "guide_observed_at":at.isoformat(),
        "source_links_examined":match["trusted_source_links_examined"],
        "source_links_unique":match["unique_source_links"],
        "conflicting_product_ids":match["provider_ids_conflicting"],
        "conflicting_variant_slots":match["variant_price_slots_conflicting"],
        "candidate_count":match["candidate_count"],
        "canonical_references_covered":match["canonical_references_covered"],
        "exact_variant_candidates":match["exact_variant_candidate_count"],
        "by_language":dict(sorted(by_language.items())),
        "by_source":dict(sorted(by_source.items())),
        "match_rejections":match["rejections"],
        "regional_references_prepared":prepared["regional_reference_count"],
        "regional_variant_quotes_prepared":prepared["regional_variant_quote_count"],
        "preparation_rejections":prepared["rejections"],
        "fx_source":fx.source,
        "crosswalk_sha256":digest,
        "uk_individual_sold_transactions":0,
        "database_writes":0,"shopify_writes":0,"store_price_writes":0,
        "production_market_value_writes":0
    }


if __name__=="__main__":
    try:
        report=asyncio.run(run())
    except Exception as exc:
        # Show only static source filename / function / line for debugging.
        # Never print live SQL rows, exception strings, prices, or secrets.
        approved = {"ci_cardmarket_full_readonly.py", "cardmarket_bulk_crosswalk.py",
                    "cardmarket_bulk_context.py", "pilot_cardmarket_live_crosswalk.py",
                    "audit_cardmarket_bulk_feed.py"}
        frames = [
            {"module":Path(f.filename).name, "function":f.name, "line":f.lineno}
            for f in traceback.extract_tb(exc.__traceback__)
            if Path(f.filename).name in approved
        ]
        print(json.dumps({"status":"FAILED_CLOSED","error_type":type(exc).__name__,
                          "safe_frames":frames[-4:],
                          "database_writes":0,"shopify_writes":0}),flush=True)
        raise SystemExit(2) from None
    print("CARDMARKET_FULL_READONLY_RECEIPT "+json.dumps(report,sort_keys=True),flush=True)
