from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from app import r2_media
from scripts import backfill_approved_r2_media as operator


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers,content",[
    (302,{"location":"https://www.dbs-cardgame.com/other.png"},b""),
    (200,{"content-type":"text/html"},b"<html>error</html>"),
    (200,{"content-type":"image/png","content-length":"4000001"},b"x"),
    (200,{"content-type":"image/png","content-length":"-1"},b"x"),
])
async def test_r2_fetch_rejects_redirects_and_invalid_headers(monkeypatch,status,headers,content):
    calls=[]
    async def respond(request):
        calls.append(str(request.url))
        return httpx.Response(status,headers=headers,content=content)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(r2_media,"_reference_http_client",lambda:client)
        assert await r2_media.reference_image_bytes("https://assets.tcgdex.net/card.png") is None
    assert calls==["https://assets.tcgdex.net/card.png"]


@pytest.mark.asyncio
async def test_r2_fetch_has_stream_cap_and_accepts_exact_source_bytes(monkeypatch):
    async def respond(request):
        return httpx.Response(200,headers={"content-type":"image/webp"},content=b"12345")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(r2_media,"_reference_http_client",lambda:client)
        assert await r2_media.reference_image_bytes("https://assets.tcgdex.net/card.webp",max_bytes=4) is None
        payload=await r2_media.reference_image_bytes("https://assets.tcgdex.net/card.webp",max_bytes=5)
        assert payload.data==b"12345"  # Decoder is enforced before any upload.
        assert await r2_media.reference_image_bytes("https://attacker.invalid/card.webp") is None


@pytest.mark.asyncio
async def test_operator_uses_short_admin_leases_and_moves_past_failed_candidates(monkeypatch):
    ids=[uuid4() for _ in range(8)]
    state={"lease":False,"checks":0,"reads":0,"attempted":[]}
    class Connection:
        async def fetch(self,query,*args):
            assert state["lease"]
            state["reads"]+=1
            return [{"id":i} for i in (ids if state["reads"]==1 else ids[:1])]
    @asynccontextmanager
    async def user_connection(pool,actor,request_id):
        assert not state["lease"]
        state["lease"]=True
        try: yield Connection()
        finally: state["lease"]=False
    async def require_admin(connection):
        assert state["lease"]
        state["checks"]+=1
    async def mirror(pool,*,limit,request_id,candidate_ids):
        assert not state["lease"]  # No network/S3 time inside a database lease.
        state["attempted"].extend(candidate_ids)
        async with pool.acquire():
            pass
        failed=int(ids[0] in candidate_ids)
        return dict(examined=limit,mirrored=limit-failed,failed=failed,skipped=0,remaining_possible=True)
    monkeypatch.setattr(operator,"user_connection",user_connection)
    monkeypatch.setattr(operator,"require_platform_admin",require_admin)
    monkeypatch.setattr(operator,"mirror_approved_media",mirror)
    result=await operator.run_with_pool(object(),uuid4(),apply=True)
    assert state["attempted"]==ids
    assert state["checks"]==4
    assert result["mirrored"]==7 and result["failed"]==1 and result["remaining_candidates"]==1
    assert result["unattempted_from_snapshot"]==0 and result["status"]=="PARTIAL"


@pytest.mark.asyncio
async def test_operator_dry_run_has_no_storage_mutations_and_admin_refusal_stops(monkeypatch):
    @asynccontextmanager
    async def user_connection(pool,actor,request_id):
        class Connection:
            async def fetch(self,*args): return [{"id":uuid4()}]
        yield Connection()
    async def allow(connection): pass
    async def forbidden(*args,**kwargs): raise AssertionError("network/storage must not run")
    monkeypatch.setattr(operator,"user_connection",user_connection)
    monkeypatch.setattr(operator,"require_platform_admin",allow)
    monkeypatch.setattr(operator,"mirror_approved_media",forbidden)
    report=await operator.run_with_pool(object(),uuid4())
    assert report["mode"]=="DRY_RUN" and report["mutations"]==0
    async def deny(connection): raise PermissionError("not administrator")
    monkeypatch.setattr(operator,"require_platform_admin",deny)
    with pytest.raises(PermissionError):
        await operator.run_with_pool(object(),uuid4(),apply=True)


@pytest.mark.asyncio
async def test_soft_deadline_finishes_active_batch_then_stops(monkeypatch):
    ids=[uuid4() for _ in range(10)]
    now=[0]
    reads=[0]
    async def pending(pool):
        reads[0]+=1
        return [{"id":i} for i in (ids if reads[0]==1 else ids[5:])]
    async def mirror(pool,*,limit,request_id,candidate_ids):
        now[0]=130
        return dict(examined=5,mirrored=5,failed=0,skipped=0,remaining_possible=True)
    monkeypatch.setattr(operator,"pending",pending)
    monkeypatch.setattr(operator,"mirror_approved_media",mirror)
    monkeypatch.setattr(operator.time,"monotonic",lambda:now[0])
    result=await operator.run_with_pool(object(),uuid4(),apply=True,max_seconds=120)
    assert result["batches"]==1 and result["mirrored"]==5
    assert result["unattempted_from_snapshot"]==5 and result["status"]=="PARTIAL"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs",[{"max_batches":101},{"max_seconds":181},{"batch_size":6},{"apply":1}])
async def test_operator_rejects_unbounded_calls_before_database(kwargs):
    with pytest.raises(ValueError,match="R2_BACKFILL_LIMITS_INVALID"):
        await operator.run_with_pool(None,uuid4(),**kwargs)
