"""Source-hash-locked 2026-11-14 Cardmarket catch-up continuation."""
import os

import pytest

from app import cardmarket_approved_remainder as approved
from app.cardmarket_public_pilot import PilotError


def _material(monkeypatch, size=6):
    rows = [{
        "provider": "TCGdex", "language": "English",
        "provider_id": f"set-{i}", "cardmarket_id": i+1000,
        "variant_id": f"v-{i}", "source_field": "avg7",
    } for i in range(size)]
    digest = approved.exact_source_digest(rows)
    monkeypatch.setattr(approved, "APPROVED_PRODUCT_SHA", "a"*64)
    monkeypatch.setattr(approved, "APPROVED_GUIDE_SHA", "b"*64)
    monkeypatch.setattr(approved, "APPROVED_CROSSWALK_SHA", digest)
    monkeypatch.setattr(approved, "APPROVED_REFERENCE_COUNT", size)
    monkeypatch.setattr(approved, "APPROVED_VARIANT_QUOTE_COUNT", size)
    monkeypatch.setattr(approved, "APPROVED_MATCH_COUNT", size)
    monkeypatch.setattr(approved, "APPROVED_START", 2)
    monkeypatch.setattr(approved, "APPROVED_END", size)
    monkeypatch.setattr(approved, "APPROVED_CHUNK", 2)
    monkeypatch.setenv("DROP_RATE_CARDMARKET_FULL_APPLY_CONFIRMED", "YES")
    monkeypatch.setenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED", "YES")
    prepared = {
        "regional_reference_count": size,
        "regional_variant_quote_count": size,
        "prepared": [{"reference_key":f"r:{i:032x}","quotes":[{"x":i}]} for i in range(size)]
    }
    return rows, prepared


def _guard(candidates, prepared, **kwargs):
    approved.check_approved_source(
        candidates=candidates, prepared=prepared,
        product_sha256=kwargs.get("product_sha256","a"*64),
        guide_sha256=kwargs.get("guide_sha256","b"*64),
        start_index=kwargs.get("start_index",2),
        end_index=kwargs.get("end_index",6)
    )


def test_approved_source_exact_digest_and_number(monkeypatch):
    rows, prepared = _material(monkeypatch)
    _guard(rows, prepared)
    assert len(approved.exact_source_digest(rows)) == 64


@pytest.mark.parametrize("field", ["product_sha256","guide_sha256","start_index","end_index"])
def test_changed_files_or_cursor_fail_closed(monkeypatch,field):
    rows, prepared = _material(monkeypatch)
    with pytest.raises(PilotError,match="changed"):
        _guard(rows, prepared, **{field:0})


def test_changed_canonical_link_blocks_all_chunks(monkeypatch):
    rows, prepared = _material(monkeypatch)
    rows[0]["provider_id"] = "different"
    with pytest.raises(PilotError,match="changed"):
        _guard(rows, prepared)


def test_missing_any_operator_gate_blocks_before_writes(monkeypatch):
    rows, prepared = _material(monkeypatch)
    monkeypatch.delenv("DROP_RATE_CARDMARKET_FULL_APPLY_CONFIRMED")
    with pytest.raises(PilotError,match="gate"):
        _guard(rows, prepared)
    monkeypatch.setenv("DROP_RATE_CARDMARKET_FULL_APPLY_CONFIRMED", "YES")
    monkeypatch.delenv("DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED")
    with pytest.raises(PilotError,match="gate"):
        _guard(rows, prepared)


def test_changed_prepared_reference_count_blocks(monkeypatch):
    rows, prepared = _material(monkeypatch)
    prepared["prepared"].pop()
    with pytest.raises(PilotError,match="changed"):
        _guard(rows, prepared)


@pytest.mark.asyncio
async def test_remainder_only_processes_verified_tail(monkeypatch):
    rows, prepared = _material(monkeypatch)
    calls = []
    async def fake_persist(pool, actor, data, *, request_id, max_references, start_index):
        calls.append((max_references, start_index, data is prepared["prepared"]))
        return {"blocked":0,"applied":max_references,"unchanged":0}
    monkeypatch.setattr(approved,"persist_cardmarket_context",fake_persist)
    progress=[]
    result=await approved.apply_approved_remainder(
        None,None,candidates=rows,prepared=prepared,
        product_sha256="a"*64,guide_sha256="b"*64,
        start_index=2,end_index=6,progress=progress.append)
    assert calls == [(2,2,True),(2,4,True)]
    assert result["references_processed"]==4 and result["applied"]==4
    assert result["physical_market_value_writes"]==0
    assert result["shopify_writes"]==0
    assert [x["next_index"] for x in progress]==[4,6]


@pytest.mark.asyncio
async def test_idempotent_existing_snapshots_no_duplicate_history(monkeypatch):
    rows, prepared = _material(monkeypatch)
    async def fake_persist(pool,actor,data,*,request_id,max_references,start_index):
        return {"blocked":0,"applied":0,"unchanged":max_references}
    monkeypatch.setattr(approved,"persist_cardmarket_context",fake_persist)
    result=await approved.apply_approved_remainder(
        None,None,candidates=rows,prepared=prepared,
        product_sha256="a"*64,guide_sha256="b"*64,start_index=2,end_index=6)
    assert result["unchanged"]==4 and result["applied"]==0


@pytest.mark.asyncio
async def test_stop_immediately_if_any_chunk_conflicted(monkeypatch):
    rows, prepared = _material(monkeypatch)
    calls=[]
    async def fake_persist(pool,actor,data,*,request_id,max_references,start_index):
        calls.append(start_index)
        return {"blocked":1,"applied":1,"unchanged":0}
    monkeypatch.setattr(approved,"persist_cardmarket_context",fake_persist)
    with pytest.raises(PilotError,match="Partial batch"):
        await approved.apply_approved_remainder(
            None,None,candidates=rows,prepared=prepared,
            product_sha256="a"*64,guide_sha256="b"*64,
            start_index=2,end_index=6)
    assert calls==[2]
