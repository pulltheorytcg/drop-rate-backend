"""Vectorized Cardmarket RLS write tests: exact source snapshots only."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4
import json

import pytest

from app import cardmarket_bulk_vector_writer as vector
from app.cardmarket_bulk_context import SOURCE
from app.cardmarket_public_pilot import PilotError


def candidate(i,*,existing=False):
    now=datetime.now(timezone.utc)
    quotes=[{
        "source":SOURCE,"product_id":str(600000+i),"variant_id":"v1",
        "source_product_sha256":"a"*64,
        "source_guide_sha256":"b"*64,
        "observed_at":(now-timedelta(hours=4)).isoformat()
    }]
    return {
        "reference_key":f"r:{i:032x}",
        "identity_sha256":f"{i:064x}",
        "quotes":quotes,
        "guide_at":now-timedelta(hours=4),
        "expires_at":now+timedelta(days=2)
    }


class FakeConnection:
    def __init__(self,*,invalidate_readback=False):
        self.cache={}
        self.history=[]
        self.reads=[]
        self.writes=[]
        self.invalidate_readback=invalidate_readback
        self.mode="off"

    async def fetchval(self,sql,*args):
        assert sql=="show transaction_read_only"
        return self.mode

    async def fetch(self,sql,keys):
        self.reads.append(sql)
        if "for update" in sql:
            return [{**self.cache[key], "lease_token":None}
                    for key in keys if key in self.cache]
        result=[self.cache[key] for key in keys if key in self.cache]
        return result[:-1] if self.invalidate_readback else result

    async def executemany(self,sql,rows):
        self.writes.append((sql,rows))
        if "reference_regional_price_history" in sql:
            self.history.extend(rows)
        else:
            for key,identity,quote_json,checked,expires in rows:
                self.cache[key]={
                    "reference_key":key,"identity_sha256":identity,
                    "quotes":quote_json,"expires_at":expires,
                    "lease_token":None}


@pytest.fixture
def authorized(monkeypatch):
    fake=FakeConnection()
    @asynccontextmanager
    async def session(*args,**kwargs):
        yield fake
    monkeypatch.setattr(vector,"user_connection",session)
    monkeypatch.setattr(vector,"require_platform_admin",AsyncMock())
    return fake


@pytest.mark.asyncio
async def test_50_refs_in_two_transactions_but_four_executemany_calls(authorized):
    rows=[candidate(i) for i in range(160)]
    result=await vector.persist_cardmarket_context_vector(
        None,uuid4(),rows,request_id="approved",start_index=100,max_references=50)
    assert result["applied"]==50 and result["blocked"]==0
    assert result["physical_market_value_writes"]==result["shopify_writes"]==0
    assert len(authorized.cache)==50 and len(authorized.history)==50
    assert len(authorized.writes)==4 # Two vector operations per 25-reference transaction
    assert len(authorized.reads)==4
    assert all(len(items)==25 for _,items in authorized.writes)
    assert all("tcg.reference_regional_price_" in sql for sql,_ in authorized.writes)
    assert all("tcg.inventory_items" not in sql for sql,_ in authorized.writes)


@pytest.mark.asyncio
async def test_exact_current_source_replay_is_idempotent(authorized):
    rows=[candidate(i) for i in range(102)]
    row=rows[100]
    authorized.cache[row["reference_key"]]={
        "reference_key":row["reference_key"],
        "identity_sha256":row["identity_sha256"],
        "quotes":json.dumps(row["quotes"]),
        "lease_token":None,
        "expires_at":row["expires_at"]
    }
    result=await vector.persist_cardmarket_context_vector(
        None,None,rows,request_id="repeat",start_index=100,max_references=1)
    assert result["applied"]==0 and result["unchanged"]==1
    assert authorized.writes==[]


@pytest.mark.asyncio
async def test_preserve_independent_source_during_verified_bulk_merge(authorized):
    rows=[candidate(i) for i in range(102)]
    row=rows[100]
    authorized.cache[row["reference_key"]]={
        "reference_key":row["reference_key"],
        "identity_sha256":row["identity_sha256"],
        "quotes":json.dumps([{"source":"TCGDEX_TCGPLAYER","product_id":"other"}]),
        "lease_token":None,
        "expires_at":row["expires_at"]
    }
    result=await vector.persist_cardmarket_context_vector(
        None,None,rows,request_id="merge",start_index=100,max_references=1)
    saved=json.loads(authorized.cache[row["reference_key"]]["quotes"])
    assert result["applied"]==1
    assert [q["source"] for q in saved]==["TCGDEX_TCGPLAYER",SOURCE]


@pytest.mark.asyncio
async def test_conflicting_identity_or_lease_refused_before_mutation(authorized):
    rows=[candidate(i) for i in range(102)]
    row=rows[100]
    authorized.cache[row["reference_key"]]={
        "reference_key":row["reference_key"],"identity_sha256":"c"*64,
        "quotes":"[]","lease_token":None,"expires_at":row["expires_at"]
    }
    with pytest.raises(PilotError,match="conflict"):
        await vector.persist_cardmarket_context_vector(
            None,None,rows,request_id="conflict",start_index=100,max_references=1)
    assert authorized.writes==[]


@pytest.mark.asyncio
async def test_failure_to_readback_prevents_success_receipt(monkeypatch):
    fake=FakeConnection(invalidate_readback=True)
    @asynccontextmanager
    async def session(*args,**kwargs):yield fake
    monkeypatch.setattr(vector,"user_connection",session)
    monkeypatch.setattr(vector,"require_platform_admin",AsyncMock())
    with pytest.raises(PilotError,match="readback"):
        await vector.persist_cardmarket_context_vector(
            None,None,[candidate(i) for i in range(103)],
            request_id="failed",start_index=100,max_references=2)


@pytest.mark.asyncio
async def test_readonly_transaction_fails_before_mutation(authorized):
    authorized.mode="on"
    with pytest.raises(PilotError,match="read only"):
        await vector.persist_cardmarket_context_vector(
            None,None,[candidate(i) for i in range(102)],
            request_id="fail",start_index=100,max_references=1)
    assert authorized.writes==[]


@pytest.mark.parametrize("start,count",[(99,2),(100,501),(100,0),(100,True)])
@pytest.mark.asyncio
async def test_invalid_bounds_do_not_enter_authorized_context(authorized,start,count):
    with pytest.raises(PilotError,match="bounds"):
        await vector.persist_cardmarket_context_vector(
            None,None,[candidate(i) for i in range(150)],
            request_id="fail",start_index=start,max_references=count)
    assert authorized.reads==[] and authorized.writes==[]


@pytest.mark.asyncio
async def test_expired_source_refused_without_mutation(authorized):
    rows=[candidate(i) for i in range(102)]
    rows[100]["expires_at"]=datetime.now(timezone.utc)-timedelta(seconds=1)
    with pytest.raises(PilotError,match="Expired"):
        await vector.persist_cardmarket_context_vector(
            None,None,rows,request_id="fail",start_index=100,max_references=1)
    assert authorized.writes==[]


@pytest.mark.asyncio
async def test_duplicate_source_key_refused_before_read(authorized):
    rows=[candidate(i) for i in range(102)]
    rows[101]["reference_key"]=rows[100]["reference_key"]
    with pytest.raises(PilotError,match="Duplicate"):
        await vector.persist_cardmarket_context_vector(
            None,None,rows,request_id="fail",start_index=100,max_references=2)
    assert authorized.reads==[]
