"""Read-only proof of REAL R2 media bytes, never mere database mirror metadata.

One-shot Railway job, with the existing owner-scoped maintenance actor. It reads
all 401+ real owner-media mirror entries and an even provider-stratified subset
of 66k+ reference mirrors. Every selected object must download with exact R2
content-addressed key, byte size, WEBP header, and SHA256. This never fetches
third-party source URLs, creates replacement images, alters PostgreSQL or D1,
relabels graded/slab images or grants media publication rights.

Only a passing *scope-specific* receipt is uploaded to private R2. Never log
owner IDs, private object keys, URLs, or signed links.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID

from app.access_control import require_platform_admin
from app.db import create_pool
from app.object_storage import ObjectStorageError, configured_object_storage
from app.settings import get_settings

REF_PROVIDER_NAMES = frozenset({
    "TCGdex", "Punk Records", "Bandai Official",
    "Naruto Card Game Archive",
})
PHYSICAL_MIN=401
REFERENCE_MIN=66218
PROBES_PER_PROVIDER=20
MAX_FILE=10_000_000
MAX_TOTAL_SELECTED_BYTES=105_000_000
MAX_FULL_REFERENCE_BYTES=7_000_000_000
READ_BATCH=480
CONCURRENCY=8
HASH_RE=re.compile(r"[0-9a-f]{64}\Z")


class MediaByteAuditError(ValueError):
    pass


def assert_mirror(record: dict, prefix: str) -> tuple[str,str,int]:
    key=record.get("object_key")
    digest=record.get("content_sha256")
    size=record.get("size_bytes")
    if (not isinstance(digest,str) or not HASH_RE.fullmatch(digest)
            or not isinstance(key,str)
            or key!=f"{prefix}/private-media/{digest}.webp"
            or type(size) is not int or not 0<size<=MAX_FILE):
        raise MediaByteAuditError("Reference/physical image has invalid R2 identity")
    asset_hash=record.get("asset_sha256")
    if asset_hash is not None and asset_hash!=digest:
        raise MediaByteAuditError("Physical media row differs from canonical media asset")
    return key,digest,size


def stratified_sample(refs: list[dict]) -> tuple[list[dict],dict[str,int]]:
    by=defaultdict(list)
    for entry in refs:
        provider=entry.get("provider")
        if provider not in REF_PROVIDER_NAMES:
            raise MediaByteAuditError("New reference image provider needs approval")
        by[provider].append(entry)
    if set(by)!=REF_PROVIDER_NAMES:
        raise MediaByteAuditError("Required reference providers missing from source")
    picked=[];counts={}
    for provider in sorted(by):
        group=sorted(by[provider],key=lambda r:(
            r["system_code"],r["language"],r["provider_id"],r["content_sha256"]))
        if len(group)<PROBES_PER_PROVIDER:
            raise MediaByteAuditError("Insufficient reference images for stratified proof")
        counts[provider]=len(group)
        for i in range(PROBES_PER_PROVIDER):
            index=((2*i+1)*len(group))//(2*PROBES_PER_PROVIDER)
            picked.append(group[index])
    return picked,counts


def verify_metadata(physical:list[dict], references:list[dict],prefix:str,*,all_references:bool=False):
    if len(physical)<PHYSICAL_MIN or len(references)<REFERENCE_MIN:
        raise MediaByteAuditError("Full source table is hidden behind RLS or reduced")
    seen_ids=set()
    for row in physical:
        uid=str(row.get("media_asset_id"))
        if not uid or uid in seen_ids:
            raise MediaByteAuditError("Missing or duplicated physical media record")
        seen_ids.add(uid)
        assert_mirror(row,prefix)
    identities=set()
    for row in references:
        ident=(row.get("provider"),row.get("system_code"),
               row.get("language"),row.get("provider_id"))
        if ident in identities:
            raise MediaByteAuditError("Duplicate canonical reference image key")
        identities.add(ident)
        assert_mirror(row,prefix)
    sample,provider_counts=stratified_sample(references)
    selected=physical+(references if all_references else sample)
    budget=MAX_FULL_REFERENCE_BYTES if all_references else MAX_TOTAL_SELECTED_BYTES
    if sum(int(r["size_bytes"]) for r in selected)>budget:
        raise MediaByteAuditError("R2 proof would exceed the approved read budget")
    # Hash full source mirror metadata identity without disclosing any source keys.
    digest=hashlib.sha256()
    for record in sorted(physical,key=lambda r:str(r["media_asset_id"])):
        digest.update(json.dumps({
            "id":str(record["media_asset_id"]),"sha256":record["content_sha256"],
            "size":record["size_bytes"]},sort_keys=True).encode())
        digest.update(b"\n")
    for record in sorted(references,key=lambda r:(
        r["provider"],r["system_code"],r["language"],r["provider_id"])):
        digest.update(json.dumps({
            "provider":record["provider"],"system":record["system_code"],
            "language":record["language"],"id":record["provider_id"],
            "sha256":record["content_sha256"],"size":record["size_bytes"]
        },sort_keys=True).encode())
        digest.update(b"\n")
    return sample,provider_counts,digest.hexdigest()


async def capture_mirror_index(pool, actor:UUID):
    async with pool.acquire(timeout=15) as conn:
        async with conn.transaction(isolation="repeatable_read",readonly=True):
            await conn.execute("SELECT set_config('tcg.user_id',$1,true)",str(actor))
            await conn.execute("SELECT set_config('tcg.request_id',$1,true)",
                               "private-r2-image-byte-audit")
            await require_platform_admin(conn)
            pc=await conn.fetchval("SELECT count(*) FROM tcg.media_object_mirrors")
            rc=await conn.fetchval(
                "SELECT count(*) FROM tcg.reference_image_mirrors WHERE status='VERIFIED'")
            if type(pc) is not int or pc<PHYSICAL_MIN or type(rc) is not int or rc<REFERENCE_MIN:
                raise MediaByteAuditError("Postgres maintenance actor cannot see full image index")
            p=await conn.fetch("""SELECT m.media_asset_id,m.object_key,m.content_sha256,
                    m.size_bytes,a.content_sha256 AS asset_sha256
                FROM tcg.media_object_mirrors m
                JOIN tcg.media_assets a ON a.id=m.media_asset_id
                ORDER BY m.id""")
            r=await conn.fetch("""SELECT provider,system_code,language,provider_id,
                    object_key,content_sha256,size_bytes
                FROM tcg.reference_image_mirrors
                WHERE status='VERIFIED'
                ORDER BY provider,system_code,language,provider_id""")
            if len(p)!=pc or len(r)!=rc:
                raise MediaByteAuditError("Reference/physical index RLS or dangling asset detected")
            return [dict(x) for x in p],[dict(x) for x in r]


async def verify_actual_bytes(storage, selected:list[dict]):
    # The storage client is initialised before spawning threads. Only the
    # bounded R2 read client is used, not the third-party external origin.
    storage._bounded_reference_client()
    sem=asyncio.Semaphore(CONCURRENCY)

    # Offload the sync S3 SDK without blocking the async event loop.
    async def bounded_probe(row):
        async with sem:
            def check():
                storage.read_verified_media(
                    row["object_key"],
                    expected_sha256=row["content_sha256"],
                    expected_size=row["size_bytes"])
                return True
            return await asyncio.to_thread(check)
    async def safely_probe(row):
        try:
            await bounded_probe(row)
            return True
        except Exception:
            return False
    passed=failed=0
    for start in range(0,len(selected),READ_BATCH):
        batch=selected[start:start+READ_BATCH]
        ok=await asyncio.gather(*(safely_probe(row) for row in batch))
        passed+=sum(ok)
        failed+=len(ok)-sum(ok)
        if len(selected)>5000 and (start+READ_BATCH)%4800==0:
            # Aggregate progress only. Never print owner/product IDs, R2 keys,
            # source URLs, signed links, or provider identifiers.
            print(json.dumps({"status":"R2_BYTES_CHECK_IN_PROGRESS",
                "objects_checked":passed+failed,"required":len(selected),
                "bytes_failed":failed}),flush=True)
    return passed,failed


async def run(*,all_references:bool=False) -> dict:
    if all_references and os.getenv("TCG_FULL_R2_REFERENCE_BYTE_AUDIT_ENABLED","false").lower()!="true":
        raise MediaByteAuditError("Full 5.7 GB reference R2 read requires explicit one-shot opt-in")
    settings=get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise MediaByteAuditError("Existing maintenance actor required")
    storage=configured_object_storage()
    if storage is None:
        raise MediaByteAuditError("Private R2 credentials not configured")
    pool=await create_pool(settings)
    try:
        physical,refs=await capture_mirror_index(
            pool,UUID(settings.catalogue_maintenance_actor_user_id))
    finally:
        await pool.close()
    sample,provider_counts,index_sha=verify_metadata(
        physical,refs,storage.config.prefix,all_references=all_references)
    selection=physical+(refs if all_references else sample)
    verified,failed=await verify_actual_bytes(storage,selection)
    outcome={
        "status":(
            ("PRIVATE_R2_ALL_QUALIFIED_REFERENCE_BYTES_VERIFIED"
             if all_references else "PRIVATE_R2_PHYSICAL_ALL_AND_REFERENCE_SAMPLE_BYTES_VERIFIED")
            if failed==0 else "PRIVATE_R2_MEDIA_BYTE_AUDIT_FAILED"),
        "source_inventory_mirror_rows":len(physical),
        "physical_media_bytes_checked":sum(x["size_bytes"] for x in physical),
        "source_reference_verified_metadata_rows":len(refs),
        "reference_provider_counts":provider_counts,
        "reference_image_sample_count":len(sample),
        "reference_bytes_requested":sum(x["size_bytes"] for x in (refs if all_references else sample)),
        "actual_object_reads":verified+failed,
        "byte_verified":verified,
        "byte_failed":failed,
        "source_metadata_sha256":index_sha,
        "read_scope":("ALL_PHYSICAL_AND_ALL_VERIFIED_REFERENCE_MEDIA"
                      if all_references else "ALL_PHYSICAL_MEDIA_AND_20_PER_REFERENCE_PROVIDER"),
        "full_reference_byte_coverage":all_references and failed==0,
        "supabase_writes":0,
        "d1_writes":0,
        "market_values_changed":0,
        "publication_rights_granted":False,
        "shopify_or_login_cutover":False,
    }
    if failed==0:
        # Private, content-addressed and remotely re-read; no source rows or
        # owner/media identifiers in this receipt.
        with tempfile.TemporaryDirectory(prefix="drop-rate-media-audit-") as d:
            receipt=Path(d)/"verified-r2-media-bytes.json"
            receipt.write_text(json.dumps(outcome,sort_keys=True,separators=(",",":"))+"\n")
            obj=storage.put_verified_file(
                receipt,category="exports",content_type="application/json")
            if not obj.get("verified"):
                raise MediaByteAuditError("Private R2 receipt readback unverified")
            outcome["private_receipt_sha256"]=obj["sha256"]
            outcome["private_receipt_size_bytes"]=obj["size_bytes"]
    return outcome


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-references",action="store_true",
        help="Read and SHA256-verify every verified reference R2 object; explicit opt-in required")
    args=parser.parse_args()
    try:
        result=asyncio.run(run(all_references=args.all_references))
        print(json.dumps(result,sort_keys=True,separators=(",",":")))
        if result["byte_failed"]>0:
            raise SystemExit(2)
    except Exception as exc:
        raise SystemExit("Private R2 media-byte audit failed: "+type(exc).__name__) from None
