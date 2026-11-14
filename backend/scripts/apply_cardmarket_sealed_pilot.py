"""Bounded, source-pinned, exact-name sealed Cardmarket price pilot.

Default --read-only. --apply additionally needs the existing production
maintenance actor, explicit feature confirmation, source digest agreement and
a 50-reference cap. Writes only append-only reference price history and the
existing sealed *reference* guide cache, not physical inventory or Shopify.

PYTHONPATH=backend python backend/scripts/apply_cardmarket_sealed_pilot.py --read-only
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import unicodedata
from uuid import UUID

import asyncpg
import httpx

from app.access_control import require_platform_admin
from app.cardmarket_public_pilot import PilotError, _rows
from app.db import user_connection
from app.fx import EcbHistoricalFxProvider
from app.sealed_market import quote_for, WRITE_SQL, HISTORY_SQL
from scripts.audit_cardmarket_bulk_feed import _HOST, _read_source

MAX_REFERENCES=50
PREVIEW_ROWS=100
SQL = """
select r.*
from tcg.reference_sealed_products r
join tcg.reference_sealed_market_prices p
using(provider,system_code,language,provider_id)
join tcg.reference_sets s using(provider,system_code,language,set_id)
where r.provider='CardTrader' and r.system_code='POKEMON_TCG'
and r.evidence->>'cardmarket_product_id' is not null
and p.market_value_minor>0 and p.expires_at<now()
and (s.release_date is null or s.release_date<=current_date)
order by r.provider_id asc limit 100
"""


def canonical(value):
    if not isinstance(value,str):
        return ""
    normalized=unicodedata.normalize("NFKC",value).casefold()
    return "".join(c for c in normalized if c.isalnum())


def exact_source_name(reference: dict, product: dict) -> bool:
    """One source ID PLUS the full product name: never a pack-size transfer."""
    a,b=canonical(reference.get("name")),canonical(product.get("name"))
    return bool(a and b and len(a)>=8 and a==b)


def identity_tuple(row: dict, product_id: str) -> list[str]:
    return [
        row["provider"],row["system_code"],row["language"],
        row["provider_id"],row["name"],row["set_id"],
        row["product_type"],product_id,
    ]


def history_receipt(identity: list[str], quote_data) -> tuple:
    if isinstance(quote_data,str):
        quote_data=json.loads(quote_data)
    if not isinstance(quote_data,list) or not quote_data:
        raise PilotError("Cannot record empty historical price evidence")
    payload=json.dumps(quote_data,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    if len(payload.encode())>65536:
        raise PilotError("Unexpected historical payload size")
    key="s:"+hashlib.md5(chr(31).join(identity[:4]).encode()).hexdigest()
    identity_hash=hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    return (key,identity_hash,hashlib.sha256(payload.encode()).hexdigest(),payload)


async def fetch_samples(pool,actor):
    async with user_connection(pool,actor,"sealed-market-readonly",readonly_snapshot=True) as c:
        await require_platform_admin(c)
        if await c.fetchval("show transaction_read_only")!="on":
            raise PilotError("Read-only snapshot not active")
        return [dict(r) for r in await c.fetch(SQL)]


async def current_cardmarket_sources(now):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0,connect=15.0,pool=15.0),
        follow_redirects=False,
        headers={"User-Agent":"DropRateSealedPinnedPilot/1.0","Accept":"application/json"}
    ) as client:
        products,pdigest=await _read_source(client,_HOST+"productList/products_nonsingles_6.json")
        guide,gdigest=await _read_source(client,_HOST+"priceGuide/price_guide_6.json")
    products,pt=_rows(products,"products",now=now)
    prices,gt=_rows(guide,"priceGuides",now=now)
    if (abs((pt-gt).total_seconds())>2*86400 or
        gt>now or now-gt>timedelta(days=2)):
        raise PilotError("Guide and catalogue timestamps incompatible")
    pmap={str(r["idProduct"]):r for r in products}
    gmap={str(r["idProduct"]):r for r in prices}
    if len(pmap)!=len(products) or len(gmap)!=len(prices):
        raise PilotError("Duplicate official source products")
    return pmap,gmap,gt,pdigest["sha256"],gdigest["sha256"]


async def run(*, apply=False, expected_product_sha=None,expected_guide_sha=None):
    if apply and os.getenv("DROP_RATE_SEALED_PINNED_PILOT_APPLY_CONFIRMED")!="YES":
        raise PilotError("Explicit sealed pilot apply gate not approved")
    if apply and (
        not all(isinstance(v,str) and len(v)==64 and
                all(ch in "0123456789abcdef" for ch in v)
                for v in (expected_product_sha,expected_guide_sha))
    ):
        raise PilotError("Source digest approval required")
    actor=UUID(os.environ["TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID"])
    dsn=os.environ["TCG_DATABASE_URL"]
    now=datetime.now(timezone.utc)
    # Read-only snapshot is explicit in the server settings and transaction.
    pool=await asyncpg.create_pool(
        dsn=dsn,min_size=1,max_size=1,command_timeout=45,
        server_settings={"default_transaction_read_only":"on",
                         "statement_timeout":"40000",
                         "application_name":"sealed-source-pinned-plan"},
    )
    try:
        refs=await fetch_samples(pool,actor)
    finally:
        await pool.close()
    if not 1<=len(refs)<=PREVIEW_ROWS:
        raise PilotError("Unexpected empty or excessive sampled canonical references")
    products,guide,at,source_sha,guide_sha=await current_cardmarket_sources(now)
    if apply and (source_sha!=expected_product_sha or guide_sha!=expected_guide_sha):
        raise PilotError("Source snapshots changed after reviewed read-only pilot")
    fx=await EcbHistoricalFxProvider().quote(
        base_currency="EUR",quote_currency="GBP",at=at-timedelta(days=1))
    class PinnedFx:
        async def quote(self,**kwargs):
            if (kwargs.get("base_currency"),kwargs.get("quote_currency"),kwargs.get("at"))!=("EUR","GBP",at):
                raise PilotError("Unexpected FX request")
            return fx
    eligible=[]
    invalid_names=invalid_guides=0
    seen=set()
    for row in refs:
        evidence=row.get("evidence")
        if isinstance(evidence,str):
            try:evidence=json.loads(evidence)
            except ValueError:
                invalid_names+=1
                continue
        if not isinstance(evidence,dict):
            invalid_names+=1
            continue
        product_id=str(evidence.get("cardmarket_product_id") or "")
        p=products.get(product_id)
        if not p or not exact_source_name(row,p):
            invalid_names+=1
            continue
        if product_id in seen:
            invalid_names+=1
            continue
        q=await quote_for(row,products,guide,at,PinnedFx(),game_name="Pokémon")
        if q is None:
            invalid_guides+=1
            continue
        eligible.append((row,product_id,q))
        seen.add(product_id)
    matched=eligible[:MAX_REFERENCES]
    result={
        "status":"SOURCE_PINNED_SEALED_PILOT_PREVIEW",
        "reference_sample":len(refs),
        "exact_name_and_id_eligible":len(eligible),
        "pilot_limit":MAX_REFERENCES,
        "name_or_id_rejections":invalid_names,
        "guide_or_category_rejections":invalid_guides,
        "with_asking_floor":sum(bool(q.get("offer_floor_context")) for _,_,q in eligible),
        "guide_at":at.isoformat(),
        "source_sha256":{"products":source_sha,"guide":guide_sha},
        "sample":[{"canonical_id":r["provider_id"],"source_id":pid,
                   "category":r["product_type"],
                   "low_offer_available":bool(q.get("offer_floor_context"))}
                  for r,pid,q in matched],
        "writes":0, "owner_writes":0, "shopify_writes":0,
    }
    if not apply:
        return result
    if len(matched)!=MAX_REFERENCES:
        raise PilotError("Fewer than 50 unambiguous source/packaging/name candidates")
    # A second, WRITE-authorized actor connection is only opened after all
    # independent source and identity tests pass. No physical-item SQL here.
    pool=await asyncpg.create_pool(
        dsn=dsn,min_size=1,max_size=1,command_timeout=45,
        server_settings={"statement_timeout":"40000",
                         "application_name":"sealed-source-pinned-50-apply"},
    )
    try:
        async with user_connection(pool,actor,"sealed-market-50-reviewed") as conn:
            await require_platform_admin(conn)
            if await conn.fetchval("show transaction_read_only")!="off":
                raise PilotError("Controlled source write transaction is read-only")
            for reference,product_id,quote in matched:
                live=await conn.fetchrow(
                    """select r.* from tcg.reference_sealed_products r
                       where r.provider=$1 and r.system_code=$2 and r.language=$3
                         and r.provider_id=$4 for update""",
                    *[reference[k] for k in ("provider","system_code","language","provider_id")])
                if live is None or any(live[k]!=reference[k] for k in
                    ("name","set_id","product_type","image_url","evidence")):
                    raise PilotError("Canonical sealed identity changed before apply")
                old=await conn.fetchrow(
                    """select * from tcg.reference_sealed_market_prices p
                       where p.provider=$1 and p.system_code=$2
                       and p.language=$3 and p.provider_id=$4 for update""",
                    *[reference[k] for k in ("provider","system_code","language","provider_id")])
                if old is None or old["checked_at"]>now:
                    raise PilotError("Existing sealed price record changed")
                ident=identity_tuple(reference,product_id)
                if old["quotes"]:
                    await conn.execute(HISTORY_SQL,*history_receipt(ident,old["quotes"]))
                new_quote_json=json.dumps([quote],sort_keys=True,separators=(",",":"),ensure_ascii=False)
                await conn.execute(HISTORY_SQL,*history_receipt(ident,[quote]))
                value=quote["price_gbp_minor"]
                await conn.execute(WRITE_SQL,
                    reference["provider"],reference["system_code"],
                    reference["language"],reference["provider_id"],new_quote_json,
                    value,value,at,now,now+timedelta(hours=24))
            # All fifty writes and their history commit atomically.
            fresh=await conn.fetchval(
                """select count(*) from tcg.reference_sealed_market_prices
                   where provider='CardTrader' and system_code='POKEMON_TCG'
                     and provider_id=any($1::text[])
                     and market_value_minor>0 and checked_at=$2
                     and expires_at>now()""",
                [x[0]["provider_id"] for x in matched],now)
            if fresh!=MAX_REFERENCES:
                raise PilotError("Readback mismatch; transaction rolled back")
        result["status"]="VERIFIED_FIFTY_SEALED_REFERENCE_GUIDES_APPLIED"
        result["writes"]=MAX_REFERENCES
        result["physical_item_writes"]=0
        return result
    finally:
        await pool.close()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read-only",action="store_true")
    mode.add_argument("--apply",action="store_true")
    ap.add_argument("--expected-product-sha")
    ap.add_argument("--expected-guide-sha")
    a=ap.parse_args()
    try:
        print("SEALED_PINNED_PILOT_RESULT "+json.dumps(asyncio.run(run(
            apply=a.apply,expected_product_sha=a.expected_product_sha,
            expected_guide_sha=a.expected_guide_sha)),sort_keys=True),flush=True)
    except Exception as exc:
        print("SEALED_PINNED_PILOT_RESULT "+json.dumps({
            "status":"FAILED_CLOSED","error_type":type(exc).__name__,
            "writes_confirmed":False,"owner_writes":0,"shopify_writes":0
        },sort_keys=True),flush=True)
        raise SystemExit(2) from None


if __name__=="__main__":
    main()
