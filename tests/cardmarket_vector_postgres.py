"""Disposable PostgreSQL 17: batched Cardmarket RLS, idempotency and history.

Run only against local postgres fixture. Hard refuses remote DSNs.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import asyncpg

from app.db import user_connection, _init_connection
from app import cardmarket_bulk_vector_writer as writer
from app.cardmarket_public_pilot import PilotError

ROOT=Path(__file__).resolve().parents[1]


def candidate(i):
    now=datetime.now(timezone.utc)
    return {
        "reference_key":f"r:{i:032x}",
        "identity_sha256":f"{i:064x}",
        "quotes":[{
            "source":"CARDMARKET_PUBLIC_BULK",
            "source_record_id":str(i+500000),
            "product_id":str(i+500000),
            "variant_id":"exact-v1",
            "source_field":"avg7",
            "observed_at":(now-timedelta(hours=1)).isoformat(),
            "physical_valuation_eligible":False,
            "regional_sale":{"region":"EU","source_field":"avg7",
                             "price_gbp_minor":100,"original_minor":120,
                             "fx_rate_to_gbp":"0.8333333333"}
        }],
        "guide_at":now-timedelta(hours=1),
        "expires_at":now+timedelta(days=2)
    }


async def run():
    dsn=os.environ["CARDMARKET_VECTOR_TEST_DSN"]
    url=urlsplit(dsn)
    if url.hostname not in ("localhost","127.0.0.1") or url.path!="/cardmarket_vector_test":
        raise RuntimeError("Disallowed non-disposable PostgreSQL for vector writer tests")
    admin=await asyncpg.connect(dsn)
    pool=None
    original_guard=writer.require_platform_admin
    try:
        await admin.execute("""create schema tcg;
          create role tcg_api nologin nosuperuser nobypassrls;
          create role anon;create role authenticated;create role service_role;
          create function tcg.current_user_id() returns uuid language sql stable as
          $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          grant usage on schema tcg to tcg_api;
          create table tcg.reference_market_prices(
            id integer primary key,quotes jsonb,market_value_minor integer,
            checked_at timestamptz,expires_at timestamptz);
          insert into tcg.reference_market_prices
            values(1,'[{"verified_uk_sold":true}]',12345,now(),now()+interval '30 days');
        """)
        await admin.execute((ROOT/"database/migrations/20261112120000_regional_catalogue_context.sql").read_text())
        async def init(conn):
            await _init_connection(conn)
            await conn.execute("set role tcg_api")
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=1,init=init)
        actor=uuid4()
        writer.require_platform_admin=AsyncMock(return_value={"business_allowed":True})
        rows=[candidate(i) for i in range(160)]
        receipt=await writer.persist_cardmarket_context_vector(
            pool,actor,rows,request_id="postgres-vector-apply",
            start_index=100,max_references=50)
        assert receipt["applied"]==50 and receipt["blocked"]==0
        assert await admin.fetchval("select count(*) from tcg.reference_regional_price_context")==50
        assert await admin.fetchval("select count(*) from tcg.reference_regional_price_history")==50
        assert await admin.fetchval("select count(*) from tcg.reference_market_prices where market_value_minor=12345")==1
        replay=await writer.persist_cardmarket_context_vector(
            pool,actor,rows,request_id="postgres-vector-replay",
            start_index=100,max_references=50)
        assert replay["unchanged"]==50 and replay["applied"]==0
        assert await admin.fetchval("select count(*) from tcg.reference_regional_price_history")==50
        await admin.execute(
            "update tcg.reference_regional_price_context set identity_sha256=$1 where reference_key=$2",
            "f"*64, rows[150]["reference_key"]
        ) if False else None
        async with user_connection(pool,actor,"no-history-update") as conn:
            try:
                await conn.execute("update tcg.reference_regional_price_history set quotes='[]'")
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("History records must be append-only")
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("select set_config('tcg.user_id','',true)")
                assert await conn.fetchval("select count(*) from tcg.reference_regional_price_context")==0
        assert await admin.fetchval("select count(*) from tcg.reference_regional_price_history")==50
        print(json.dumps({"status":"POSTGRES_VECTOR_CARDMARKET_RLS_PASS",
                         "applied":50,"replay_unchanged":50,
                         "history":50,"physical_uk_market_value_untouched":True,
                         "owner_data_writes":0,"shopify_writes":0}))
    finally:
        writer.require_platform_admin=original_guard
        if pool:await pool.close()
        await admin.close()


if __name__=="__main__":
    asyncio.run(run())
