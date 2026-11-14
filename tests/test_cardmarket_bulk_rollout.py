"""Batch-only full Cardmarket rollout safeguards; no provider or DB access."""
import pytest
from unittest.mock import AsyncMock

from app import cardmarket_bulk_rollout as bulk
from app.cardmarket_public_pilot import PilotError


def prepared(n=1202):
    return [{"reference_key": f"r:{i:032x}"} for i in range(n)]


@pytest.mark.asyncio
async def test_resumes_after_verified_100_with_capped_batches(monkeypatch):
    calls=[]
    async def persist(pool,actor,rows,*,request_id,max_references,start_index):
        calls.append((start_index,max_references))
        return {"applied":max_references,"unchanged":0,"blocked":0,
                "physical_market_value_writes":0,"store_price_writes":0,
                "shopify_writes":0}
    monkeypatch.setattr(bulk,"persist_cardmarket_context_vector",persist)
    progress=[]
    result=await bulk.apply_verified_remaining(
        None,None,prepared(),start_index=100,batch_size=500,
        request_id="test",log_progress=progress.append)
    assert calls==[(100,500),(600,500),(1100,102)]
    assert result["planned"]==1102 and result["applied"]==1102
    assert result["blocked"]==result["shopify_writes"]==0
    assert len(progress)==result["batches"]==3


@pytest.mark.asyncio
async def test_idempotent_replay_can_reuse_existing_unchanged_values(monkeypatch):
    async def persist(*args,**kwargs):
        return {"applied":0,"unchanged":kwargs["max_references"],"blocked":0,
                "physical_market_value_writes":0,"store_price_writes":0,
                "shopify_writes":0}
    monkeypatch.setattr(bulk,"persist_cardmarket_context_vector",persist)
    result=await bulk.apply_verified_remaining(
        None,None,prepared(103),start_index=100,batch_size=500,request_id="test")
    assert result["applied"]==0 and result["unchanged"]==3


@pytest.mark.asyncio
async def test_any_blocked_batch_stops_before_next(monkeypatch):
    writer=AsyncMock(return_value={
        "applied":499,"unchanged":0,"blocked":1,
        "physical_market_value_writes":0,"store_price_writes":0,"shopify_writes":0})
    monkeypatch.setattr(bulk,"persist_cardmarket_context_vector",writer)
    with pytest.raises(PilotError,match="reconcile"):
        await bulk.apply_verified_remaining(
            None,None,prepared(),start_index=100,batch_size=500,request_id="test")
    assert writer.await_count==1


@pytest.mark.parametrize("start,size,n",[
    (99,100,200),(100,501,1000),(100,0,1000),(100,500,100),
    (100,500,10001),(100,True,1000),
])
@pytest.mark.asyncio
async def test_invalid_scope_fails_before_any_database_call(monkeypatch,start,size,n):
    writer=AsyncMock(side_effect=AssertionError("Database write forbidden"))
    monkeypatch.setattr(bulk,"persist_cardmarket_context_vector",writer)
    with pytest.raises(PilotError):
        await bulk.apply_verified_remaining(
            None,None,prepared(n),start_index=start,batch_size=size,request_id="test")
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_keys_fail_before_write(monkeypatch):
    rows=prepared(120)
    rows[101]["reference_key"]=rows[100]["reference_key"]
    writer=AsyncMock(side_effect=AssertionError("Database write forbidden"))
    monkeypatch.setattr(bulk,"persist_cardmarket_context_vector",writer)
    with pytest.raises(PilotError,match="Duplicate"):
        await bulk.apply_verified_remaining(
            None,None,rows,start_index=100,batch_size=20,request_id="test")
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_script_requires_separate_approval_before_network_or_db(monkeypatch):
    from scripts import pilot_cardmarket_live_crosswalk as script
    network=AsyncMock(side_effect=AssertionError("No source access before approval"))
    monkeypatch.setattr(script,"_fetch_links",network)
    monkeypatch.setenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED","YES")
    monkeypatch.delenv("DROP_RATE_CARDMARKET_FULL_BATCH_CONFIRMED",raising=False)
    with pytest.raises(PilotError,match="full-source approval"):
        await script.run(
            apply=True,full_remaining=True,start_index=100,max_references=500,
            expected_products_sha="a"*64,expected_guide_sha="b"*64,
            expected_crosswalk_sha="c"*64,expected_reference_count=8907)
    network.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_script_rejects_missing_sha_before_network(monkeypatch):
    from scripts import pilot_cardmarket_live_crosswalk as script
    network=AsyncMock(side_effect=AssertionError("No source access before digest"))
    monkeypatch.setattr(script,"_fetch_links",network)
    monkeypatch.setenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED","YES")
    monkeypatch.setenv("DROP_RATE_CARDMARKET_FULL_BATCH_CONFIRMED","YES")
    with pytest.raises(PilotError,match="full-source approval"):
        await script.run(
            apply=True,full_remaining=True,start_index=100,max_references=500,
            expected_products_sha="not-the-approved-sha",
            expected_guide_sha="b"*64,
            expected_crosswalk_sha="c"*64,expected_reference_count=8907)
    network.assert_not_awaited()
