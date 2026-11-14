"""Read-only live Cardmarket x existing Drop Rate Pokémon source-ID pilot.

Requires the *existing* Supabase maintenance actor; never a user-supplied owner.
Run only as a standalone maintenance job, not as an API startup or cron.
No production DB writes, Shopify/owner changes, media or market publication.

PYTHONPATH=backend python backend/scripts/pilot_cardmarket_live_crosswalk.py --read-only
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import httpx

from app.access_control import require_platform_admin
from app.cardmarket_bulk_crosswalk import MAX_LINKS, match_pokemon_bulk
from app.cardmarket_public_pilot import PilotError
from app.db import user_connection
from scripts.audit_cardmarket_bulk_feed import _HOST, _read_source

# This query reads only existing canonical reference and source evidence.
# It never joins physical inventory or owner data and cannot update a price.
SOURCE_LINKS_SQL = """
select r.provider,r.system_code,r.language,r.provider_id,r.name,r.set_id,s.name set_name,
       r.card_number,q.data->>'product_id' as cardmarket_id,
       q.data->>'source' as source,q.data->>'finish' as finish,
       q.data->>'variant_id' as variant_id,
       q.data->>'source_field' as source_field,
       q.data->>'match_basis' as match_basis
from tcg.reference_cards r
join tcg.reference_sets s using(provider,system_code,language,set_id)
join lateral (
    select jsonb_array_elements(m.quotes) as data
    from tcg.reference_market_prices m
    where m.provider=r.provider and m.system_code=r.system_code
      and m.language=r.language and m.provider_id=r.provider_id
    union all
    select jsonb_array_elements(c.quotes) as data
    from tcg.reference_catalogue_prices c
    where c.provider=r.provider and c.system_code=r.system_code
      and c.language=r.language and c.provider_id=r.provider_id
) q on true
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
  and q.data->>'source' in (
      'TCGDEX_CARDMARKET','TCGDEX_CARDMARKET_VARIANT','CARDMARKET_CATALOGUE'
  )
order by r.language,r.provider_id,q.data->>'product_id',q.data->>'source'
limit 120001
"""


async def _fetch_links() -> list[dict]:
    dsn = os.getenv("TCG_DATABASE_URL", "").strip()
    actor = os.getenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID", "").strip()
    if not dsn or not actor:
        raise PilotError("Existing maintenance database actor configuration missing")
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=1, command_timeout=65,
        server_settings={"default_transaction_read_only": "on",
                         "statement_timeout": "60000",
                         "application_name": "cardmarket-readonly-crosswalk-pilot"},
    )
    try:
        async with user_connection(
            pool, UUID(actor), "cardmarket-live-crosswalk-readonly",
            readonly_snapshot=True
        ) as conn:
            await require_platform_admin(conn)
            if await conn.fetchval("show transaction_read_only") != "on":
                raise PilotError("Missing explicit READ ONLY snapshot")
            rows = await conn.fetch(SOURCE_LINKS_SQL)
            if len(rows) > MAX_LINKS:
                raise PilotError("Too many source links for bounded review")
            # Release the RLS-protected lease before fetching public source bytes.
            return [dict(row) for row in rows]
    finally:
        await pool.close()


async def run() -> dict:
    links = await _fetch_links()
    timeout = httpx.Timeout(90.0, connect=15.0, pool=15.0)
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False,
        headers={"User-Agent": "DropRateReadOnlyCardmarketCrosswalk/1.0",
                 "Accept": "application/json"}
    ) as client:
        products, catalogue_receipt = await _read_source(
            client, _HOST + "productList/products_singles_6.json")
        guide, guide_receipt = await _read_source(
            client, _HOST + "priceGuide/price_guide_6.json")
    report = match_pokemon_bulk(
        links=links, products_export=products, price_export=guide,
        now=datetime.now(timezone.utc))
    # Never print source EUR guide amounts or unpublished private crosswalks.
    canonical = sorted({
        (c["language"], c["provider_id"], c["cardmarket_id"],
         c["finish"], c["source_field"], c["match_basis"])
        for c in report.pop("candidates")
    })
    report["candidate_crosswalk_sha256"] = hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    report["official_source_receipts"] = {
        "products": catalogue_receipt, "guide": guide_receipt
    }
    report["provider_requests"] = 2
    report["published_uk_market_values"] = 0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    if not args.read_only:
        raise SystemExit("Read-only required")
    try:
        report = asyncio.run(run())
    except (PilotError, ValueError, asyncpg.PostgresError, httpx.HTTPError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED",
                          "error_type": type(exc).__name__,
                          "database_writes": 0, "shopify_writes": 0},
                         sort_keys=True), flush=True)
        raise SystemExit(2) from None
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
