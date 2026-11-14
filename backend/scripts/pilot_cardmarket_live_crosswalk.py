"""Controlled Cardmarket bulk source crosswalk and source-labelled GBP cache.

Default --read-only prepares a bounded preview with no Supabase writes.
Explicit --apply requires a second operator permission flag and a verified
backup/restore checkpoint. Only writes the already-existing, RLS-protected
regional context+append-only history, never physical UK Market Value, Shopify,
owner/inventory or Store Price.

PYTHONPATH=backend python backend/scripts/pilot_cardmarket_live_crosswalk.py --read-only
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from uuid import UUID

import asyncpg
import httpx

from app.access_control import require_platform_admin
from app.cardmarket_bulk_crosswalk import MAX_LINKS, match_pokemon_bulk
from app.cardmarket_bulk_context import prepare_cardmarket_context
from app.cardmarket_bulk_persistence import persist_cardmarket_context
from app.cardmarket_bulk_rollout import apply_verified_remaining
from app.fx import EcbHistoricalFxProvider
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


async def run(*, apply: bool = False, max_references: int = 100,
              start_index: int = 0, full_remaining: bool = False,
              expected_products_sha: str | None = None,
              expected_guide_sha: str | None = None,
              expected_crosswalk_sha: str | None = None,
              expected_reference_count: int | None = None) -> dict:
    if not 1 <= max_references <= 500 or start_index < 0:
        raise PilotError("Invalid bounded import range")
    if apply and os.getenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED") != "YES":
        raise PilotError("Existing restore verification and explicit apply gate required")
    if full_remaining and (
        not apply or start_index < 100
        or os.getenv("DROP_RATE_CARDMARKET_FULL_BATCH_CONFIRMED") != "YES"
        or not all(isinstance(v,str) and len(v)==64 and
                   all(c in "0123456789abcdef" for c in v)
                   for v in (expected_products_sha,expected_guide_sha,expected_crosswalk_sha))
        or type(expected_reference_count) is not int
        or not 100 < expected_reference_count <= 10000
    ):
        raise PilotError("Verified pilot and exact full-source approval required")
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
    # A source-date historical ECB quote avoids using a rate published after
    # Cardmarket's 01:44 UTC guide observation.
    guide_at = datetime.fromisoformat(
        str(guide.get("createdAt") or "").replace("Z", "+00:00"))
    fx = await EcbHistoricalFxProvider().quote(
        base_currency="EUR", quote_currency="GBP",
        at=guide_at - timedelta(days=1))
    prepared = prepare_cardmarket_context(
        candidates=report["candidates"], fx=fx,
        guide_at=guide_at, now=datetime.now(timezone.utc),
        product_sha256=catalogue_receipt["sha256"],
        guide_sha256=guide_receipt["sha256"])
    # Never print source EUR guide amounts or unpublished private crosswalks.
    canonical = sorted({
        (c["language"], c["provider_id"], c["cardmarket_id"],
         c["finish"], c["source_field"], c["match_basis"])
        for c in report.pop("candidates")
    })
    report["prepared_regional_reference_count"] = prepared["regional_reference_count"]
    report["prepared_regional_variant_quote_count"] = prepared["regional_variant_quote_count"]
    report["preparation_rejections"] = prepared["rejections"]
    report["fx_source"] = fx.source
    report["fx_effective_at"] = fx.effective_at.isoformat()
    report["candidate_crosswalk_sha256"] = hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if full_remaining and (
        catalogue_receipt["sha256"] != expected_products_sha
        or guide_receipt["sha256"] != expected_guide_sha
        or report["candidate_crosswalk_sha256"] != expected_crosswalk_sha
        or prepared["regional_reference_count"] != expected_reference_count
    ):
        raise PilotError("Exact approved product, guide or canonical crosswalk changed")
    if apply:
        dsn = os.getenv("TCG_DATABASE_URL", "").strip()
        actor = UUID(os.environ["TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID"].strip())
        pool = await asyncpg.create_pool(
            dsn=dsn, min_size=1, max_size=1, command_timeout=30,
            server_settings={"statement_timeout": "25000",
                             "application_name": "cardmarket-region-bulk-bounded"})
        try:
            if full_remaining:
                # Read back the first 100 already applied canonical keys and
                # their exact source receipts inside an authenticated RLS snapshot.
                seed = prepared["prepared"][:100]
                async with user_connection(
                    pool, actor, "cardmarket-first-100-verified", readonly_snapshot=True
                ) as conn:
                    await require_platform_admin(conn)
                    if await conn.fetchval("show transaction_read_only") != "on":
                        raise PilotError("Pilot seed verification is not READ ONLY")
                    count = await conn.fetchval(
                        """
                        with seed(reference_key,identity_sha256) as (
                          select * from unnest($1::text[],$2::text[])
                        )
                        select count(*) from seed
                        join tcg.reference_regional_price_context c
                          using(reference_key,identity_sha256)
                        where c.expires_at > now()
                          and exists (
                            select 1 from jsonb_array_elements(c.quotes) q
                            where q->>'source'='CARDMARKET_PUBLIC_BULK'
                              and q->>'source_product_sha256'=$3
                              and q->>'source_guide_sha256'=$4
                          )
                        """,
                        [r["reference_key"] for r in seed],
                        [r["identity_sha256"] for r in seed],
                        expected_products_sha, expected_guide_sha,
                    )
                    if count != 100:
                        raise PilotError("The pilot 100 source-identity seed no longer matches")
                report["apply_receipt"] = await apply_verified_remaining(
                    pool, actor, prepared["prepared"],
                    start_index=start_index, batch_size=max_references,
                    request_id="cardmarket-verified-full-rollout",
                    log_progress=lambda row: print(
                        "CARDMARKET_ROLLOUT_PROGRESS " + json.dumps(row,sort_keys=True),
                        flush=True),
                )
                report["status"] = "FULL_REGIONAL_CONTEXT_ROLLOUT_COMPLETE"
            else:
                report["apply_receipt"] = await persist_cardmarket_context(
                    pool, actor, prepared["prepared"], request_id="cardmarket-approved-bulk",
                    max_references=max_references, start_index=start_index)
        finally:
            await pool.close()
    else:
        report["status"] = "REVIEW_ONLY_PREPARED_NOT_APPLIED"
        report["apply_receipt"] = None
    report["official_source_receipts"] = {
        "products": catalogue_receipt, "guide": guide_receipt
    }
    report["provider_requests"] = 2
    report["published_uk_market_values"] = 0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--max-references", type=int, default=100)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--full-remaining", action="store_true",
                        help="Resume only after the verified first-100 pilot")
    parser.add_argument("--expected-products-sha")
    parser.add_argument("--expected-guide-sha")
    parser.add_argument("--expected-crosswalk-sha")
    parser.add_argument("--expected-reference-count", type=int)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(
            apply=args.apply, max_references=args.max_references,
            start_index=args.start_index, full_remaining=args.full_remaining,
            expected_products_sha=args.expected_products_sha,
            expected_guide_sha=args.expected_guide_sha,
            expected_crosswalk_sha=args.expected_crosswalk_sha,
            expected_reference_count=args.expected_reference_count))
    except (PilotError, ValueError, asyncpg.PostgresError, httpx.HTTPError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED",
                          "error_type": type(exc).__name__,
                          "no_new_unverified_values": True,
                          "shopify_writes": 0},
                         sort_keys=True), flush=True)
        raise SystemExit(2) from None
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
