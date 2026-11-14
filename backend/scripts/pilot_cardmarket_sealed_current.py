"""Read-only live sealed-cardmarket cross-ID probe (no DB/Shopify/price writes).

Uses existing canonical sealed IDs, the existing sealed-market category matcher,
fresh first-party Cardmarket nonsingles/guide exports, and dated ECB FX.
A quoted guide or lowest offer is market context, not a physical UK sold price.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from uuid import UUID

import asyncpg
import httpx

from app.access_control import require_platform_admin
from app.cardmarket_public_pilot import PilotError, _rows
from app.db import user_connection
from app.fx import EcbHistoricalFxProvider
from app.sealed_market import quote_for
from scripts.audit_cardmarket_bulk_feed import _HOST, _read_source

SELECT = """
select r.*,p.market_value_minor as old_price
from tcg.reference_sealed_products r
join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_sealed_market_prices p using(provider,system_code,language,provider_id)
where r.provider='CardTrader' and r.system_code='POKEMON_TCG'
and r.evidence->>'cardmarket_product_id' is not null
and (s.release_date is null or s.release_date<=current_date)
order by (p.market_value_minor is not null) desc,r.provider_id asc
limit 50
"""


async def read_live_references() -> list[dict]:
    dsn=os.getenv("TCG_DATABASE_URL","").strip()
    actor=os.getenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID","").strip()
    if not dsn or not actor:
        raise PilotError("Existing RLS maintenance credentials missing")
    pool=await asyncpg.create_pool(
        dsn=dsn,min_size=1,max_size=1,command_timeout=40,
        server_settings={"default_transaction_read_only":"on",
                         "statement_timeout":"30000",
                         "application_name":"cardmarket-sealed-source-only"}
    )
    try:
        async with user_connection(
            pool,UUID(actor),"cardmarket-sealed-readonly",readonly_snapshot=True,
        ) as conn:
            await require_platform_admin(conn)
            if await conn.fetchval("show transaction_read_only")!="on":
                raise PilotError("Expected READ ONLY DB transaction")
            rows=[dict(x) for x in await conn.fetch(SELECT)]
            if not 1<=len(rows)<=50:
                raise PilotError("Unexpected bounded sealed reference sample")
            return rows
    finally:
        await pool.close()


async def run() -> dict:
    refs=await read_live_references()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0,connect=15.0,pool=15.0),
        follow_redirects=False,
        headers={"User-Agent":"DropRateSealedReadOnlyAudit/1.0",
                 "Accept":"application/json"},
    ) as client:
        products,prod_receipt=await _read_source(
            client,_HOST+"productList/products_nonsingles_6.json")
        guides,guide_receipt=await _read_source(
            client,_HOST+"priceGuide/price_guide_6.json")
    now=datetime.now(timezone.utc)
    product_rows,created_at=_rows(products,"products",now=now)
    guide_rows,guide_at=_rows(guides,"priceGuides",now=now)
    if abs(created_at-guide_at)>timedelta(days=2):
        raise PilotError("Price and product exports mismatched")
    pmap={str(row["idProduct"]):row for row in product_rows}
    gmap={str(row["idProduct"]):row for row in guide_rows}
    if len(pmap)!=len(product_rows) or len(gmap)!=len(guide_rows):
        raise PilotError("Ambiguous Cardmarket source IDs")
    # FX source is observed before the price guide, consistent with the
    # existing Cardmarket bulk import; no arbitrary current forex quotation.
    fx=await EcbHistoricalFxProvider().quote(
        base_currency="EUR",quote_currency="GBP",
        at=guide_at-timedelta(days=1))
    class PinnedFx:
        async def quote(self,**kwargs):
            if kwargs.get("base_currency")!="EUR" or kwargs.get("quote_currency")!="GBP" or kwargs.get("at")!=guide_at:
                raise PilotError("FX source snapshot changed")
            return fx
    failures=Counter()
    matched=with_floor=0
    examples=[]
    for row in refs:
        evidence=row["evidence"]
        if isinstance(evidence,str):
            try:evidence=json.loads(evidence)
            except ValueError:
                failures["BAD_STORED_EVIDENCE"]+=1
                continue
        if not isinstance(evidence,dict):
            failures["BAD_STORED_EVIDENCE"]+=1
            continue
        source_id=str(evidence.get("cardmarket_product_id") or "")
        product=pmap.get(source_id)
        if product is None:
            failures["NO_PRODUCT"]+=1
            continue
        price=gmap.get(source_id)
        if price is None:
            failures["NO_GUIDE"]+=1
            continue
        quote=await quote_for(row,pmap,gmap,guide_at,PinnedFx(),game_name="Pokémon")
        if quote is None:
            failures["CATEGORY_PACKAGING_OR_TREND_MISMATCH"]+=1
            continue
        matched+=1
        with_floor+=bool(quote.get("offer_floor_context"))
        if len(examples)<5:
            examples.append({
                "canonical_id":row["provider_id"],
                "source_product_id":source_id,
                "product_type":row["product_type"],
                "name":row["name"],
                "has_active_offer_floor":bool(quote.get("offer_floor_context")),
            })
    return {
        "status":"READ_ONLY_SEALED_EXACT_SOURCE_PROBE",
        "reference_sample":len(refs),
        "verified_cardmarket_trend_candidates":matched,
        "with_separate_lowest_offer_context":with_floor,
        "rejections":dict(failures),
        "sample":examples,
        "guide_created_at":guide_at.isoformat(),
        "source_sha256":{"nonsingles":prod_receipt["sha256"],
                         "guide":guide_receipt["sha256"]},
        "requests":{"cardmarket":2,"fx":1},
        "db_writes":0,"shopify_writes":0,
        "physical_market_value_writes":0,"market_value_updates":0,
    }


if __name__=="__main__":
    try:
        print("SEALED_CARDMARKET_SOURCE_RESULT "+
              json.dumps(asyncio.run(run()),sort_keys=True),flush=True)
    except Exception as exc:
        print("SEALED_CARDMARKET_SOURCE_RESULT "+
              json.dumps({"status":"FAILED_CLOSED",
                          "error_type":type(exc).__name__,
                          "db_writes":0,"shopify_writes":0},sort_keys=True),flush=True)
        raise SystemExit(2) from None
