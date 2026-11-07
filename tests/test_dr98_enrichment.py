"""DR98: private, checksum-verified R2 artwork and UK sold-evidence queue."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app import automation_commands as api
from app import catalogue_enrichment as queue
from app import r2_first_catalogue as codec
from app.r2_first_sources import source_descriptor


ACTOR = "11111111-1111-4111-8111-111111111111"
SOURCES = (
    "ygoprodeck", "lorcast", "mtgjson", "cardcollectorcapital",
    "cardcollectorcapital_heritage", "reviewed_figures",
)


class MemoryStorage:
    def __init__(self, bundle):
        self.objects = {}
        self.writes = []
        for raw in (bundle._manifest_bytes, *bundle.parts):
            self.objects[hashlib.sha256(raw).hexdigest()] = raw
        self.corrupt_readback = False
    def read_verified_reference_snapshot(self, digest):
        value = self.objects[digest]
        if self.corrupt_readback and digest in self.writes:
            return b'CORRUPT'
        return value
    def put_verified_reference_snapshot(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        self.objects.setdefault(digest,raw)
        self.writes.append(digest)
        return {"sha256":digest,"verified":True}


def make_source(rows=None):
    descriptor=source_descriptor("ygoprodeck")
    if rows is None:
        rows=[{
            "provider":"ygoprodeck","system_code":"YUGIOH",
            "language":"English","provider_id":str(i),
            "product_type":"CARD","name":f"Verified reference {i}",
            "set_id":"ABC-2026" if i else "",
            "set_name":"Fixture Set",
            "card_number":f"ABC-{i:05}" if i else "",
            "rarity":"Rare","finish":"Holo",
            "release_date":"2026-11-01",
            "source_url":descriptor.source_url,
        } for i in range(3)]
    bundle=codec.prepare_catalogue(
        rows,provider=descriptor.provider,system_code=descriptor.system_code,
        language=descriptor.catalogue_language,
        source_url=descriptor.source_url,source_revision="fixture-revision-2",
        permission_ref=descriptor.permission_ref,
    )
    manifest=bundle.manifest
    pub={
        **{key:manifest[key] for key in ("provider","system_code","language",
            "source_url","source_revision","permission_ref","record_count","raw_bytes")},
        "generation":2,"active":True,"manifest_sha256":bundle.manifest_digest,
    }
    return pub,MemoryStorage(bundle)


@pytest.fixture
def source_env(monkeypatch):
    pub,store=make_source()
    calls=[]
    async def authorised(pool,actor,descriptor):
        calls.append((str(actor),descriptor.provider))
        return pub
    monkeypatch.setattr(queue,"_authorised_publication",authorised)
    return pub,store,calls


@pytest.mark.asyncio
async def test_worklist_carries_verified_exact_printing_without_images_or_prices(source_env):
    pub,store,calls=source_env
    result=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)
    assert result["status"]=="PRIVATE_ENRICHMENT_WORKLIST_VERIFIED"
    assert result["generation"]==2
    assert result["candidate_count"]==3
    assert result["identity_review_count"]==1
    assert result["requires_exact_rights_and_printing"]==3
    assert result["requires_verified_sold_evidence"]==3
    assert result["artwork_published"] is False
    assert result["market_values_written"]==0
    assert result["shopify_updated"] is False
    assert result["ownership_or_price_changed"] is False
    assert len(store.writes)==2
    assert store.writes[1]==result["batch_worklist_manifest_sha256"]
    batch_index=json.loads(store.objects[store.writes[1]])
    assert batch_index["schema"]=="drop-rate-enrichment-batch-v1"
    assert batch_index["source_manifest_sha256"]==pub["manifest_sha256"]
    assert batch_index["part_worklists"][0]["worklist_sha256"]==store.writes[0]
    assert batch_index["artwork_publication_authorised"] is False
    assert batch_index["market_value_authorised"] is False
    digest=store.writes[0]
    assert digest==result["worklist_sha256"][0]
    body=json.loads(store.objects[digest])
    assert body["schema"]==queue.SCHEMA
    assert body["source_manifest_sha256"]==pub["manifest_sha256"]
    assert len(body["records"])==3
    assert body["no_artwork_rights_inferred"] is True
    assert body["no_market_value_inferred"] is True
    for card in body["records"]:
        assert card["reference_key"].startswith("x:")
        assert card["artwork_state"]=="NEEDS_EXACT_PRINT_AND_COMMERCIAL_RIGHTS_PROOF"
        assert card["market_state"]=="NEEDS_EXACT_UK_SOLD_EVIDENCE"
        assert not any("image_url" in k or "store_price" in k or "market_value_minor" in k
                       for k in card)
    assert calls==[(ACTOR,"ygoprodeck"),(ACTOR,"ygoprodeck"),(ACTOR,"ygoprodeck")]


@pytest.mark.asyncio
async def test_duplicate_pass_is_content_addressed_and_idempotent(source_env):
    pub,store,_=source_env
    first=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=1)
    second=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=1)
    assert first["worklist_sha256"]==second["worklist_sha256"]
    assert len(set(store.writes))==2


@pytest.mark.asyncio
async def test_no_active_generation_performs_no_r2_io(monkeypatch):
    monkeypatch.setattr(queue,"_authorised_publication",AsyncMock(return_value=None))
    result=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=object(),slot=0)
    assert result["status"]=="NO_ACTIVE_CATALOGUE_GENERATION"
    assert result["worklist_sha256"]==[]


@pytest.mark.asyncio
async def test_changed_source_during_upload_fails_closed(source_env,monkeypatch):
    pub,store,_=source_env
    before=deepcopy(pub)
    after={**before,"generation":3,"manifest_sha256":"a"*64}
    lookup=AsyncMock(side_effect=[before,after])
    monkeypatch.setattr(queue,"_authorised_publication",lookup)
    result=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)
    assert result["status"]=="STALE_GENERATION_PRIVATE_ONLY"
    assert result["worklist_sha256"]==[]


@pytest.mark.asyncio
async def test_generation_change_while_storing_batch_manifest_prevents_publishing_receipt(source_env,monkeypatch):
    pub,store,_=source_env
    before=deepcopy(pub)
    later={**before,"generation":3,"manifest_sha256":"a"*64}
    monkeypatch.setattr(queue,"_authorised_publication",
                        AsyncMock(side_effect=[before,before,later]))
    result=await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)
    assert result["status"]=="STALE_GENERATION_PRIVATE_ONLY"
    assert result["worklist_sha256"]==[]
    # Private immutable orphan bytes are harmless; no live pointer changed.
    assert len(store.writes)==2


@pytest.mark.asyncio
async def test_wrong_source_manifest_cannot_stage(source_env,monkeypatch):
    pub,store,_=source_env
    monkeypatch.setattr(queue,"_authorised_publication",AsyncMock(return_value={
        **pub,"provider":"unexpected",
    }))
    with pytest.raises(codec.R2FirstCatalogueError):
        await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)
    assert store.writes==[]


@pytest.mark.asyncio
async def test_corrupt_source_part_fails_before_any_new_r2_worklist(source_env):
    pub,store,_=source_env
    for digest,value in list(store.objects.items()):
        if digest!=pub["manifest_sha256"]:
            store.objects[digest]=b'[{}]'
    with pytest.raises(codec.R2FirstCatalogueError):
        await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)
    assert store.writes==[]


@pytest.mark.asyncio
async def test_bad_r2_readback_rejects_worklist(source_env):
    _,store,_=source_env
    store.corrupt_readback=True
    with pytest.raises(queue.EnrichmentError,match="byte readback"):
        await queue.run_batch(object(),ACTOR,"ygoprodeck",storage=store,slot=0)


@pytest.mark.asyncio
async def test_unsupported_source_cannot_read_publication_or_storage(monkeypatch):
    monkeypatch.setattr(queue,"_authorised_publication",
                        AsyncMock(side_effect=AssertionError("unapproved")))
    with pytest.raises(queue.EnrichmentError):
        await queue.run_batch(object(),ACTOR,"riftcodex",storage=object(),slot=0)


def test_canonical_reference_versus_physical_slab_identity_review():
    standard={
        "key":"x:"+"b"*64,"provider_id":"a","product_type":"CARD",
        "set_id":"ABC","card_number":"123","language":"English",
        "finish":"Foil","rarity":"Rare","release_date":None,
    }
    with_print=queue.candidate(standard)
    assert with_print["identity_state"]=="PRINTING_REVIEW_REQUIRED"
    assert with_print["slab_photo_state"]=="NOT_APPLICABLE_TO_CANONICAL_REFERENCE"
    assert queue.candidate({**standard,"card_number":""})["identity_state"]=="IDENTITY_REVIEW_REQUIRED"
    assert queue.candidate({**standard,"product_type":"FIGURE"})["identity_state"]=="IDENTITY_REVIEW_REQUIRED"


def test_signed_command_requires_exact_metadata_source_and_no_arbitrary_urls():
    baseline={
        "schema_version":1,"action":"PREPARE_R2_ENRICHMENT_WORKLIST",
        "source":"ygoprodeck","execution_id":"dr98-001",
        "occurred_at":"2026-11-07T00:55:00+00:00",
    }
    api.EnrichmentWorklistCommand.model_validate(baseline)
    for change in ({"source":"riftcodex"},{"source":"scryfall"},
                   {"source":"not-approved"},{"provider_url":"https://evil.invalid"},
                   {"action":"PUBLISH_UNLICENSED_IMAGES"},{"schema_version":99}):
        with pytest.raises(ValidationError):
            api.EnrichmentWorklistCommand.model_validate({**baseline,**change})


@pytest.mark.asyncio
async def test_api_reuses_shared_signature_checker_and_owns_no_media_or_price_writes(monkeypatch):
    body={
        "schema_version":1,"action":"PREPARE_R2_ENRICHMENT_WORKLIST",
        "source":"ygoprodeck","execution_id":"dr98-001",
        "occurred_at":"2026-11-07T00:55:00+00:00",
    }
    async def verified(*args,**kwargs):
        assert kwargs["timestamp_header"]=="123"
        assert kwargs["signature_header"]=="sha256=fixture"
        return json.dumps(body).encode()
    monkeypatch.setattr(api,"_verified_command_body",verified)
    monkeypatch.setattr(api,"get_settings",
                        lambda:SimpleNamespace(catalogue_maintenance_actor_user_id=ACTOR))
    worker=AsyncMock(return_value={
        "status":"PRIVATE_ENRICHMENT_WORKLIST_VERIFIED","source":"ygoprodeck",
        "generation":2,"source_manifest_sha256":"a"*64,
        "processed_parts":1,"candidate_count":3,"worklist_sha256":["b"*64],
        "batch_worklist_manifest_sha256":"c"*64,
    })
    monkeypatch.setattr(api,"prepare_enrichment_batch",worker)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())))
    result=await api.prepare_catalogue_enrichment_worklist(
        request,x_drop_rate_timestamp="123",x_drop_rate_signature="sha256=fixture")
    assert result["status"]=="PRIVATE_ENRICHMENT_WORKLIST_VERIFIED"
    assert result["scope"]=="EXACT_IDENTITY_REVIEW_AND_SOLD_EVIDENCE_TASKS_ONLY"
    assert result["batch_worklist_manifest_sha256"]=="c"*64
    assert result["artwork_published"] is False
    assert result["market_values_written"]==0
    assert result["shopify_updated"] is False
    assert result["ownership_or_price_changed"] is False
    worker.assert_awaited_once()


def test_all_six_workflows_use_source_specific_signed_endpoint_and_strict_receipts():
    root=Path(__file__).resolve().parents[1]/"automation/n8n/workflows"
    paths=list(root.glob("dr-98-*-enrichment.json"))
    assert len(paths)==6
    found=set()
    for path in paths:
        flow=json.loads(path.read_text())
        assert flow["active"] is False
        assert flow["settings"]["errorWorkflow"]=="DR90GlobalErrorV1"
        source=flow["meta"]["dropRate"]["source"]
        assert source in SOURCES and source not in found
        found.add(source)
        nodes=flow["nodes"]
        assert len(nodes)==4
        assert nodes[0]["type"]=="n8n-nodes-base.scheduleTrigger"
        assert nodes[0]["parameters"]["rule"]["interval"][0]["minutesInterval"]==15
        code=[n["parameters"]["jsCode"] for n in nodes if n["type"]=="n8n-nodes-base.code"]
        assert len(code)==2
        assert f"source:'{source}'" in code[0]
        assert "PREPARE_R2_ENRICHMENT_WORKLIST" in code[0]
        assert "createHmac('sha256'" in code[0]
        assert "/commands/catalogue/prepare-enrichment-worklist" in code[0]
        assert f"r.source!=='{source}'" in code[1]
        assert "r.artwork_published!==false" in code[1]
        assert "r.market_values_written!==0" in code[1]
        assert "r.batch_worklist_manifest_sha256" in code[1]
        assert "r.ownership_or_price_changed!==false" in code[1]
    assert found==set(SOURCES)
