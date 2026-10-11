"""Owner-only upload -> confident Draft copies -> review exceptions.

One open incremental Collectr snapshot per owner is deliberate: pending rows
are not a completed quantity baseline. The same file resumes safely; a newer
snapshot waits until the open snapshot is confirmed/skipped. No stock is
removed on a decrease. No new catalogue, listing, price or money is created.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import Field, field_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner
from . import imports
from .import_review import ImportCandidateResolutionRequest, ImportCandidateSkipRequest, IDENTITY_REVIEW_ISSUES
from .import_inventory import lock_import_owner, create_draft_copies, json_object
from .import_admission import exact_admission, manual_admission_valid, identity_fingerprint, meets_threshold
from .collectr_snapshot import collectr_snapshot_key
from .language import clean_language


class ConfirmImportCandidate(ImportCandidateResolutionRequest):
    language: str | None = Field(default=None, max_length=80)

    @field_validator("language")
    @classmethod
    def valid_language(cls, value):
        if value is None:
            return None
        result = clean_language(value)
        if result not in {"English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese"}:
            raise ValueError("Choose a supported card language")
        return result


async def _summary(connection, batch_id, owner_id):
    return dict(await connection.fetchrow("""select
        coalesce(sum(quantity) filter(where status='COMMITTED'),0)::int as added_units,
        coalesce(sum(quantity) filter(where status='READY'),0)::int as ready_units,
        count(*) filter(where status='REVIEW')::int as review_rows,
        coalesce(sum(quantity) filter(where status='REVIEW'),0)::int as review_units,
        count(*) filter(where status='SKIPPED')::int as skipped_rows
        from tcg.import_candidates where batch_id=$1 and owner_id=$2""", batch_id, owner_id))


async def _batch(connection, owner, batch_id, version=None):
    await lock_import_owner(connection, owner["id"])
    batch = await connection.fetchrow(
        "select * from tcg.import_batches where id=$1 and owner_id=$2 for update",batch_id,owner["id"])
    if batch is None:
        raise HTTPException(404,"Import batch not found")
    if batch["status"] not in {"PREVIEW","COMMITTED"}:
        raise HTTPException(409,"This import is no longer editable")
    if version is not None and batch["version"] != version:
        if batch.get("last_auto_apply_version") != version:
            raise HTTPException(409, {"message":"Import changed; refresh to see the current result","current_version":batch["version"]})
    return batch


async def _require_current_snapshot(connection, batch, owner):
    other = await connection.fetchval("""select id from tcg.import_batches
        where owner_id=$1 and id<>$2 and automatic_intake and status='PREVIEW'
        order by created_at limit 1""",owner["id"],batch["id"])
    if other:
        raise HTTPException(409, {"message":"Finish or skip the remaining review rows in your open import before starting another export","batch_id":str(other)})
    if batch["adapter"] != "COLLECTR":
        return
    marker = await connection.fetchval("""select normalized_record from tcg.import_candidates
        where batch_id=$1 and owner_id=$2 order by source_row limit 1""",batch["id"],owner["id"])
    expected = json_object(marker or {}).get("collectr_baseline_batch_id")
    actual = await connection.fetchval("""select id from tcg.import_batches
        where owner_id=$1 and id<>$2 and adapter='COLLECTR' and status='COMMITTED'
        order by committed_at desc nulls last,created_at desc,id desc limit 1""",owner["id"],batch["id"])
    if expected != (str(actual) if actual else None):
        raise HTTPException(409,"Collectr quantity baseline changed; refresh the latest snapshot before adding stock")


async def _result(connection, batch, owner, *, created=0, replayed=False, candidate_id=None):
    response = {"batch_id":str(batch["id"]),"version":batch["version"],
                "batch_status":batch["status"],"status":batch["status"],
                "automatic_intake":batch.get("automatic_intake",False),
                "created_count":created,"replayed":replayed,
                "summary":await _summary(connection,batch["id"],owner["id"])}
    if candidate_id:
        candidate = await connection.fetchrow("""select id,source_row,quantity,normalized_record,catalogue_id,status,issues
            from tcg.import_candidates where id=$1 and batch_id=$2 and owner_id=$3""",candidate_id,batch["id"],owner["id"])
        response["candidate"] = dict(candidate) if candidate else None
    return jsonable_encoder(response)


async def _apply(connection, batch, owner, *, progress=False, candidate_id=None):
    await _require_current_snapshot(connection,batch,owner)
    candidates = await connection.fetch("""select * from tcg.import_candidates
        where batch_id=$1 and owner_id=$2 and status='READY' order by source_row for update""",batch["id"],owner["id"])
    accepted=[]
    changed=progress or not batch["automatic_intake"]
    for row in candidates:
        normalized=json_object(row["normalized_record"])
        catalogue=await connection.fetchrow("select * from tcg.catalogue_products where id=$1",row["catalogue_id"])
        catalogue=dict(catalogue) if catalogue else None
        if manual_admission_valid(normalized,catalogue):
            evidence=normalized["import_identity_confirmation"]
        else:
            match,issues=await imports._catalogue_match(connection,normalized)
            evidence=exact_admission(normalized,catalogue,unique=not issues and match==row["catalogue_id"])
            if evidence and not meets_threshold(evidence["rule_confidence"]):
                evidence=None
        stored_issues=imports._json_value(row["issues"],expected_type=list,fallback=[])
        if not evidence or stored_issues:
            await connection.execute("""update tcg.import_candidates set status='REVIEW',issues=$1::jsonb
                where id=$2 and batch_id=$3 and owner_id=$4""",
                json.dumps(sorted(set(stored_issues)|{"manual_identity_confirmation_required"})),row["id"],batch["id"],owner["id"])
            changed=True
            continue
        normalized["import_identity_confirmation"]=evidence
        await connection.execute("update tcg.import_candidates set normalized_record=$1::jsonb where id=$2 and batch_id=$3 and owner_id=$4",
                                 json.dumps(normalized),row["id"],batch["id"],owner["id"])
        accepted.append({**dict(row),"normalized_record":normalized})
    created=await create_draft_copies(connection,candidates=accepted,owner_id=owner["id"],batch_id=batch["id"],adapter=batch["adapter"])
    summary=await _summary(connection,batch["id"],owner["id"])
    final_status="PREVIEW" if summary["review_rows"] or summary["ready_units"] else "COMMITTED"
    if not changed and not created and final_status==batch["status"]:
        return await _result(connection,batch,owner,replayed=True,candidate_id=candidate_id)
    updated=await connection.fetchrow("""update tcg.import_batches set automatic_intake=true,
        status=$1,committed_at=case when $1='COMMITTED' then now() else null end,
        last_auto_apply_version=version,version=version+1
        where id=$2 and owner_id=$3 and version=$4 returning *""",final_status,batch["id"],owner["id"],batch["version"])
    if updated is None:
        raise HTTPException(409,"Import changed; refresh before retrying")
    return await _result(connection,updated,owner,created=created,candidate_id=candidate_id)


async def add_recognised(batch_id: UUID,payload: imports.ImportCommitRequest,request: Request,
                         user: Annotated[AuthenticatedUser,Depends(require_user)]) -> dict:
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        owner=await current_owner(connection)
        batch=await _batch(connection,owner,batch_id,payload.version)
        if batch["status"]=="COMMITTED" or batch["version"]!=payload.version:
            return await _result(connection,batch,owner,replayed=True)
        return await _apply(connection,batch,owner)


async def upload_collection(payload: imports.ImportPreviewRequest,request: Request,
                            user: Annotated[AuthenticatedUser,Depends(require_user)]) -> dict:
    try:
        preview=await imports.preview_import(payload,request,user)
        batch_id=UUID(str(preview["batch_id"]))
        version=preview["version"]
    except (HTTPException,asyncpg.UniqueViolationError) as exc:
        # An exact-file retry resumes its existing result. Other errors retain
        # their real status; never claim a failed request made no changes.
        if isinstance(exc,HTTPException) and (exc.status_code!=409 or not isinstance(exc.detail,dict) or "batch_id" not in exc.detail):
            raise
        async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
            owner=await current_owner(connection)
            existing=await connection.fetchrow("select id,version from tcg.import_batches where owner_id=$1 and source_sha256=$2",
                owner["id"],hashlib.sha256(payload.content.encode()).hexdigest())
            if existing is None:
                raise exc
            batch_id,version=existing["id"],existing["version"]
    return await add_recognised(batch_id,imports.ImportCommitRequest(version=version),request,user)


async def confirm_candidate(batch_id: UUID,candidate_id: UUID,payload: ConfirmImportCandidate,request: Request,
                            user: Annotated[AuthenticatedUser,Depends(require_user)]) -> dict:
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        owner=await current_owner(connection)
        batch=await _batch(connection,owner,batch_id,payload.version)
        row=await connection.fetchrow("select * from tcg.import_candidates where id=$1 and batch_id=$2 and owner_id=$3 for update",candidate_id,batch_id,owner["id"])
        if row is None:
            raise HTTPException(404,"Import row not found")
        if row["status"]=="COMMITTED" and row["catalogue_id"]==payload.catalogue_id:
            return await _result(connection,batch,owner,replayed=True,candidate_id=candidate_id)
        if batch["status"]!="PREVIEW" or batch["version"]!=payload.version or row["status"]!="REVIEW":
            raise HTTPException(409,"This row changed or was already processed; refresh the import")
        await _require_current_snapshot(connection,batch,owner)
        catalogue=await connection.fetchrow("select * from tcg.catalogue_products where id=$1",payload.catalogue_id)
        if catalogue is None:
            raise HTTPException(404,"Catalogue match not found")
        catalogue=dict(catalogue)
        normalized=json_object(row["normalized_record"])
        if normalized.get("product_type") and normalized["product_type"]!=catalogue["product_type"]:
            raise HTTPException(422,"Selected match has a different product type")
        issues=set(imports._json_value(row["issues"],expected_type=list,fallback=[]))
        language=payload.language or clean_language(catalogue.get("language")) or clean_language(normalized.get("language"))
        if payload.language and catalogue.get("language") and payload.language!=clean_language(catalogue["language"]):
            raise HTTPException(422,"Chosen language conflicts with the selected catalogue printing")
        if "language_conflict" in issues and payload.language is None:
            raise HTTPException(422,"Confirm the card language explicitly to resolve conflicting source information")
        normalized.setdefault("_collectr_source_identity",list(collectr_snapshot_key(normalized)))
        for key in ("game","name","set_name","card_number","variant","rarity"):
            normalized[key]=catalogue.get(key)
        normalized["language"]=language
        issues-=IDENTITY_REVIEW_ISSUES|{"manual_identity_confirmation_required"}
        if language:
            issues.discard("missing_language")
        if payload.language:
            issues.discard("language_conflict")
        if catalogue["product_type"]=="CARD" and not language:
            issues.add("missing_language")
        normalized["import_identity_confirmation"]={"method":"MANUAL","catalogue_id":str(catalogue["id"]),
            "identity_fingerprint":identity_fingerprint(catalogue),"actor_user_id":str(user.user_id)}
        await connection.execute("""update tcg.import_candidates set catalogue_id=$1,normalized_record=$2::jsonb,
            status=$3,issues=$4::jsonb where id=$5 and batch_id=$6 and owner_id=$7""",catalogue["id"],json.dumps(normalized),
            "REVIEW" if issues else "READY",json.dumps(sorted(issues)),candidate_id,batch_id,owner["id"])
        if batch["automatic_intake"]:
            return await _apply(connection,batch,owner,progress=True,candidate_id=candidate_id)
        updated=await connection.fetchrow("update tcg.import_batches set version=version+1 where id=$1 and owner_id=$2 returning *",batch_id,owner["id"])
        return await _result(connection,updated,owner,candidate_id=candidate_id)


async def skip_candidate(batch_id: UUID,candidate_id: UUID,payload: ImportCandidateSkipRequest,request: Request,
                         user: Annotated[AuthenticatedUser,Depends(require_user)]) -> dict:
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        owner=await current_owner(connection)
        batch=await _batch(connection,owner,batch_id,payload.version)
        row=await connection.fetchrow("select * from tcg.import_candidates where id=$1 and batch_id=$2 and owner_id=$3 for update",candidate_id,batch_id,owner["id"])
        if row is None:
            raise HTTPException(404,"Import row not found")
        if row["status"]=="SKIPPED":
            return await _result(connection,batch,owner,replayed=True,candidate_id=candidate_id)
        if batch["status"]!="PREVIEW" or batch["version"]!=payload.version or row["status"] not in {"READY","REVIEW"}:
            raise HTTPException(409,"Only unimported rows can be skipped")
        await _require_current_snapshot(connection,batch,owner)
        await connection.execute("update tcg.import_candidates set status='SKIPPED' where id=$1 and batch_id=$2 and owner_id=$3",candidate_id,batch_id,owner["id"])
        if batch["automatic_intake"]:
            return await _apply(connection,batch,owner,progress=True,candidate_id=candidate_id)
        updated=await connection.fetchrow("update tcg.import_batches set version=version+1 where id=$1 and owner_id=$2 returning *",batch_id,owner["id"])
        return await _result(connection,updated,owner,candidate_id=candidate_id)
