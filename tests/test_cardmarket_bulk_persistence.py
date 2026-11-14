"""Safe Cardmarket regional persistence: only context and append-only history."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4
import json

import pytest

from app import cardmarket_bulk_persistence as persist
from app.cardmarket_bulk_context import SOURCE
from app.cardmarket_public_pilot import PilotError


def entry():
    now=datetime.now(timezone.utc)
    return {"reference_key":"r:"+"a"*32,"identity_sha256":"b"*64,
            "quotes":[{"source":SOURCE,"product_id":"582029","variant_id":"v1",
                       "observed_at":(now-timedelta(hours=3)).isoformat()}],
            "guide_at":now-timedelta(hours=3),
            "expires_at":now+timedelta(days=2)}


def test_preserves_independent_regional_sources_and_replaces_own_source():
    original=[
        {"source":"TCGDEX_CARDMARKET","variant_id":"old"},
        {"source":SOURCE,"product_id":"582029","variant_id":"stale"}
    ]
    fresh=[{"source":SOURCE,"product_id":"582029","variant_id":"new"}]
    merged=json.loads(persist.merge_source_quotes(original,fresh))
    assert len(merged)==2
    assert merged[0]["source"]=="TCGDEX_CARDMARKET"
    assert merged[1]==fresh[0]


@pytest.mark.parametrize("existing",[None,"corrupted",{},[]])
def test_malformed_cache_never_silently_replaced(existing):
    if existing is None:
        existing={"source":"CORRUPT"}
    with pytest.raises(PilotError):
        persist.merge_source_quotes(existing,[{"source":SOURCE}])


@pytest.mark.asyncio
async def test_gated_persistence_writes_only_existing_regional_tables(monkeypatch):
    rows=[]
    conn=AsyncMock()
    conn.fetchval.return_value="off"
    conn.fetchrow.return_value=None
    async def fake_execute(sql,*args):
        rows.append((sql,args))
    conn.execute.side_effect=fake_execute
    @asynccontextmanager
    async def session(*args,**kwargs):
        yield conn
    monkeypatch.setattr(persist,"user_connection",session)
    monkeypatch.setattr(persist,"require_platform_admin",AsyncMock())
    result=await persist.persist_cardmarket_context(None,uuid4(),[entry()],request_id="test",max_references=1)
    assert result["applied"]==1 and result["blocked"]==0
    assert len(rows)==2
    assert "tcg.reference_regional_price_history" in rows[0][0]
    assert "on conflict do nothing" in rows[0][0]
    assert "tcg.reference_regional_price_context" in rows[1][0]
    assert "where tcg.reference_regional_price_context.identity_sha256" in rows[1][0]
    assert all(not any(x in sql for x in ("tcg.inventory_items","tcg.shopify","tcg.market_observations",
                                          "tcg.reference_market_prices","tcg.reference_catalogue_prices"))
               for sql,_ in rows)
    assert result["physical_market_value_writes"]==0
    assert result["store_price_writes"]==result["shopify_writes"]==0


@pytest.mark.asyncio
async def test_identity_conflict_skips_without_any_mutation(monkeypatch):
    conn=AsyncMock()
    conn.fetchval.return_value="off"
    conn.fetchrow.return_value={"identity_sha256":"c"*64,"lease_token":None,"quotes":[]}
    @asynccontextmanager
    async def session(*args,**kwargs):
        yield conn
    monkeypatch.setattr(persist,"user_connection",session)
    monkeypatch.setattr(persist,"require_platform_admin",AsyncMock())
    result=await persist.persist_cardmarket_context(None,uuid4(),[entry()],request_id="test",max_references=1)
    assert result["blocked"]==1
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_readonly_transaction_cannot_apply(monkeypatch):
    conn=AsyncMock()
    conn.fetchval.return_value="on"
    @asynccontextmanager
    async def session(*args,**kwargs):
        yield conn
    monkeypatch.setattr(persist,"user_connection",session)
    monkeypatch.setattr(persist,"require_platform_admin",AsyncMock())
    with pytest.raises(PilotError,match="cannot persist"):
        await persist.persist_cardmarket_context(None,uuid4(),[entry()],request_id="test",max_references=1)
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_source_stays_unapplied(monkeypatch):
    conn=AsyncMock()
    conn.fetchval.return_value="off"
    @asynccontextmanager
    async def session(*args,**kwargs):
        yield conn
    monkeypatch.setattr(persist,"user_connection",session)
    monkeypatch.setattr(persist,"require_platform_admin",AsyncMock())
    stale=entry()
    stale["expires_at"]=datetime.now(timezone.utc)-timedelta(days=1)
    result=await persist.persist_cardmarket_context(None,uuid4(),[stale],request_id="test",max_references=1)
    assert result["blocked"]==1
    conn.fetchrow.assert_not_awaited()
    conn.execute.assert_not_awaited()
