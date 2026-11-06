"""Private, read-only R2 checkpoint of exact permitted-column UK sold observations.

This worker is intentionally NOT a Market Value calculator and never
publishes prices. Its input is legacy PostgreSQL `tcg.market_observations`,
limited to the explicit columns below: NO free-text `metadata`, provider
URLs/titles, API tokens, auth sessions, audit JSON, customer data, or AI
inferences. All records are labelled SOURCE_CLASSIFIED_SOLD_UNREVIEWED until
independent provenance/usage-rights review.

Run one-shot from Railway with its existing R2 and read-only snapshot access.
No source writes. No public R2 URL. No settlement/Shopify/D1 cutover.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID

from app.access_control import require_platform_admin
from app.db import create_pool
from app.object_storage import ObjectStorageError, configured_object_storage, sha256_file
from app.settings import get_settings

MIN_SOLD_ROWS=1083
MAX_SOLD_ROWS=100_000
MAX_UNCOMPRESSED=100_000_000
MAX_COMPRESSED=60_000_000
HEX64=re.compile(r"[0-9a-f]{64}\Z")
FIELDS=(
    "id","catalogue_id","source","source_record_key","observation_type",
    "observed_at","price_minor","shipping_minor","currency","price_gbp_minor",
    "shipping_gbp_minor","condition","grading_company","grade","language",
    "seal_status","source_country","sample_size","evidence_quality",
    "ingested_at",
)
QUERY="""SELECT row_to_json(x)::text AS payload FROM (
 SELECT id, catalogue_id, source, source_record_key, observation_type,
        observed_at, price_minor, shipping_minor, currency, price_gbp_minor,
        shipping_gbp_minor, condition, grading_company, grade, language,
        seal_status, source_country, sample_size, evidence_quality, ingested_at
 FROM tcg.market_observations WHERE observation_type='SOLD'
 ORDER BY id
) x"""
assert "metadata" not in QUERY and "metadata" not in FIELDS
assert len(FIELDS)==20


class SoldEvidenceGuard(ValueError):
    pass


def validate_record(raw: str) -> tuple[str,str]:
    if type(raw) is not str or not 0<len(raw)<25000:
        raise SoldEvidenceGuard("Invalid sold observation projection length")
    try:
        record=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError,TypeError) as exc:
        raise SoldEvidenceGuard("Invalid sold source JSON") from exc
    if not isinstance(record,dict) or tuple(record)!=FIELDS:
        raise SoldEvidenceGuard("Sold source projection columns changed")
    source_key=record["source_record_key"]
    if (record["observation_type"]!="SOLD" or record["source"]!="EBAY"
            or record["source_country"]!="GB" or record["currency"]!="GBP"
            or not isinstance(source_key,str) or not HEX64.fullmatch(source_key)
            or type(record["price_gbp_minor"]) is not int or record["price_gbp_minor"]<=0
            or type(record["price_minor"]) is not int or record["price_minor"]<=0
            or type(record["id"]) is not str or not record["id"]
            or type(record["catalogue_id"]) is not str or not record["catalogue_id"]
            or not isinstance(record["observed_at"],str) or not record["observed_at"]
            or not isinstance(record["ingested_at"],str) or not record["ingested_at"]):
        raise SoldEvidenceGuard("Source sale provenance or pricing eligibility mismatch")
    if (record["shipping_gbp_minor"] is not None
            and (type(record["shipping_gbp_minor"]) is not int
                 or record["shipping_gbp_minor"]<0)):
        raise SoldEvidenceGuard("Negative or malformed shipping")
    return record["id"],source_key


def canonical_lines(rows:list[str]) -> tuple[bytes,int,str]:
    if not isinstance(rows,list) or not MIN_SOLD_ROWS<=len(rows)<=MAX_SOLD_ROWS:
        raise SoldEvidenceGuard("SOLD source RLS visibility/count outside approved floor")
    seen_ids=set();seen_external=set();lines=[]
    for raw in rows:
        id_value,external=validate_record(raw)
        if id_value in seen_ids or external in seen_external:
            raise SoldEvidenceGuard("Duplicate source sold identity")
        seen_ids.add(id_value);seen_external.add(external)
        lines.append((id_value,raw))
    lines.sort(key=lambda p:p[0])
    payload=("\n".join(x[1] for x in lines)+"\n").encode("utf-8")
    if len(payload)>MAX_UNCOMPRESSED:
        raise SoldEvidenceGuard("Sold evidence exceeds source-byte bound")
    digest=hashlib.sha256(payload).hexdigest()
    return payload,len(lines),digest


async def capture_source(pool,actor:UUID) -> tuple[bytes,int,str]:
    async with pool.acquire(timeout=15) as conn:
        async with conn.transaction(isolation="repeatable_read",readonly=True):
            await conn.execute("select set_config('tcg.user_id',$1,true)",str(actor))
            await conn.execute("select set_config('tcg.request_id',$1,true)",
                               "private-r2-sold-observations-only")
            await require_platform_admin(conn)
            visible=await conn.fetchval(
                "SELECT count(*) FROM tcg.market_observations WHERE observation_type='SOLD'")
            if type(visible) is not int or not MIN_SOLD_ROWS<=visible<=MAX_SOLD_ROWS:
                raise SoldEvidenceGuard("SOLD source RLS visibility below independently checked floor")
            rows=await conn.fetch(QUERY)
            if len(rows)!=visible:
                raise SoldEvidenceGuard("Incomplete READ ONLY sold observation snapshot")
            return canonical_lines([r["payload"] for r in rows])


def pack_and_verify(payload:bytes, path:Path) -> str:
    with path.open("xb") as f:
        with gzip.GzipFile(filename="",fileobj=f,mode="wb",mtime=0,compresslevel=6) as gz:
            gz.write(payload)
    compressed_sha,size=sha256_file(path)
    if size==0 or size>MAX_COMPRESSED:
        raise SoldEvidenceGuard("Compressed sold archive outside approved bounds")
    with gzip.open(path,"rb") as gz:
        reconstructed=gz.read(MAX_UNCOMPRESSED+1)
    if reconstructed!=payload:
        raise SoldEvidenceGuard("Local sold-evidence gzip roundtrip failed")
    return compressed_sha


def verify_remote(storage,archive:Path,expected_sha:str) -> dict:
    compressed_sha,size=sha256_file(archive)
    if compressed_sha!=expected_sha:
        raise SoldEvidenceGuard("Local archive digest changed before upload")
    result=storage.put_verified_file(archive,category="exports",content_type="application/gzip")
    if not result.get("verified") or result.get("sha256")!=compressed_sha:
        raise SoldEvidenceGuard("Remote R2 upload failed checksum verification")
    with tempfile.TemporaryDirectory(prefix="drop-rate-private-sold-readback-") as d:
        local=Path(d)/"remote.ndjson.gz"
        storage.download_verified_file(result["key"],local,
            expected_sha256=compressed_sha,expected_size=size)
        with gzip.open(local,"rb") as gz:
            reconstructed=gz.read(MAX_UNCOMPRESSED+1)
    return {"payload":reconstructed,"r2_compressed_sha256":compressed_sha,"r2_size_bytes":size}


async def run(*,apply:bool) -> dict:
    if apply and os.getenv("TCG_PRIVATE_SOLD_EVIDENCE_R2_APPLY_ENABLED","false").lower()!="true":
        raise SoldEvidenceGuard("Private sold evidence R2 apply has no explicit one-shot authorisation")
    settings=get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise SoldEvidenceGuard("Admin maintenance actor is required")
    pool=await create_pool(settings)
    try:
        payload,count,source_sha=await capture_source(
            pool,UUID(settings.catalogue_maintenance_actor_user_id))
    finally:
        await pool.close()
    with tempfile.TemporaryDirectory(prefix="drop-rate-uk-sold-source-") as d:
        root=Path(d)
        archive=root/"uk-sold.ndjson.gz"
        compressed_sha=pack_and_verify(payload,archive)
        receipt={
            "status":"LOCAL_UK_SOLD_SOURCE_TYPED_ROUNDTRIP_VERIFIED",
            "source_relation":"tcg.market_observations",
            "observation_type":"SOURCE_CLASSIFIED_SOLD_UNREVIEWED",
            "source_rows":count,
            "source_payload_sha256":source_sha,
            "compressed_sha256":compressed_sha,
            "source_query_excludes_metadata":True,
            "sample_size_eligible_for_market_value":False,
            "source_usage_rights_recheck_required":True,
            "prices_published":0,
            "pricing_model_calculated":False,
            "d1_rows_written":0,
            "supabase_rows_written":0,
            "r2_uploaded":False,
            "supabase_retired":False,
        }
        if apply:
            storage=configured_object_storage()
            if storage is None:
                raise SoldEvidenceGuard("Private R2 not configured")
            remote=verify_remote(storage,archive,compressed_sha)
            recovered=remote.pop("payload")
            if hashlib.sha256(recovered).hexdigest()!=source_sha or recovered!=payload:
                raise SoldEvidenceGuard("Remote R2 sold-evidence row exact readback failed")
            # Full per-row schema and uniqueness re-validation after R2 download.
            back_lines=recovered.decode("utf8").splitlines()
            _,parsed,hash_after=canonical_lines(back_lines)
            if parsed!=count or hash_after!=source_sha:
                raise SoldEvidenceGuard("Remote sold-source row identity mismatch")
            receipt.update(remote)
            receipt.update({"status":"PRIVATE_R2_UK_SOLD_SOURCE_ROWS_VERIFIED",
                            "r2_uploaded":True})
            report_path=root/"uk-sold-evidence-receipt.json"
            report_path.write_text(
                json.dumps(receipt,separators=(",",":"),sort_keys=True)+"\n",
                encoding="utf8")
            report=storage.put_verified_file(
                report_path,category="exports",content_type="application/json")
            if not report.get("verified"):
                raise SoldEvidenceGuard("R2 source receipt did not verify")
            receipt["private_receipt_sha256"]=report["sha256"]
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",
        help="Private immutable R2 write and actual byte readback; requires one-off flag")
    args=parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(apply=args.apply)),sort_keys=True))
    except Exception as exc:
        # Never print original DB SQL, provider source rows or signed R2 URLs.
        raise SystemExit("Private UK sold checkpoint not verified: "+type(exc).__name__) from None
