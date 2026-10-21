"""Owner-bound manual intake for comics, graded comics and manga."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID
import json

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .inventory_intake import create_inventory_intake
from .schemas import ManualInventoryCreate
from .db import user_connection
from .book_research import identity_digest, catalogue_candidates
from .comic_identity import ComicPrintingCreate
from .catalogue_artwork import reference_thumbnail

router = APIRouter(prefix="/api/v1/owner/books", tags=["owner-books"])


async def saved_cover_choices(db, inventory_id, owner_id):
    row = await db.fetchrow("""select b.*,coalesce(i.language,p.language) as language
        from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.comic_printing_details b on b.catalogue_id=p.id
        where i.id=$1 and i.owner_id=$2 and p.product_type='COMIC'
          and coalesce(i.language,p.language)=p.language""", inventory_id, owner_id)
    if row is None:
        raise HTTPException(404, "Comic or manga not found")
    attrs = row["attributes"]
    if isinstance(attrs, str): attrs = json.loads(attrs)
    fields = {key: row.get(key) for key in ComicPrintingCreate.model_fields}
    fields.update(publisher=attrs.get("publisher"), book_format=attrs.get("book_format"), language=row["language"])
    revoked = attrs.get("cover_rights_status") in {"REVOKED", "REJECTED"} or attrs.get("cover_source_status") in {"REVOKED", "INACTIVE"}
    return fields, [] if revoked else await catalogue_candidates(db, fields)


@router.get("/inventory/{inventory_id}/covers")
async def existing_book_covers(inventory_id: UUID, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
        fields, candidates = await saved_cover_choices(db, inventory_id, access["owner_id"])
        version = await db.fetchval("select version from tcg.inventory_items where id=$1 and owner_id=$2", inventory_id, access["owner_id"])
    return {"version": version, "identity_digest": identity_digest(fields), "candidates": [
        {key: value for key, value in {**c, "image_path": f"/api/v1/owner/books/inventory/{inventory_id}/covers/{c['id']}?version={version}"}.items()
         if key != "image_url"} for c in candidates]}


@router.get("/inventory/{inventory_id}/covers/{candidate_id}")
async def existing_book_cover_image(inventory_id: UUID, candidate_id: str, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)], version: int = Query(ge=1)):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
        _, candidates = await saved_cover_choices(db, inventory_id, access["owner_id"])
        current = await db.fetchval("select version from tcg.inventory_items where id=$1 and owner_id=$2", inventory_id, access["owner_id"])
    candidate = next((c for c in candidates if c["id"] == candidate_id), None)
    if current != version or candidate is None:
        raise HTTPException(404, "Cover choice changed. Refresh the item.")
    payload = await reference_thumbnail(candidate["image_url"])
    if payload is None:
        raise HTTPException(502, "Publisher cover temporarily unavailable")
    return Response(payload.data, media_type=payload.content_type, headers={"Cache-Control": "private, no-store"})


class SavedCoverChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    identity_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    confirmed: Literal[True]


@router.post("/inventory/{inventory_id}/cover")
async def choose_existing_book_cover(inventory_id: UUID, payload: SavedCoverChoice, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)]):
    from .owner_inventory import locked_item, require_editable
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
        item = await locked_item(db, inventory_id, access["owner_id"])
        fields, candidates = await saved_cover_choices(db, inventory_id, access["owner_id"])
        digest = identity_digest(fields)
        candidate = next((c for c in candidates if c["id"] == payload.candidate_id), None)
        if digest != payload.identity_digest or candidate is None:
            raise HTTPException(409, "Book details changed. Choose the cover again.")
        key = f"book-reference:{inventory_id}"
        prior = await db.fetchval("select provider_evidence from tcg.recognition_runs where owner_id=$1 and idempotency_key=$2", access["owner_id"], key)
        if isinstance(prior, str): prior = json.loads(prior)
        # A retry of an already committed choice is a no-op, including after a lost response.
        if prior and prior.get("identity_digest") == digest and prior.get("book_reference", {}).get("id") == payload.candidate_id:
            return {"message": "Cover saved.", "version": item["version"]}
        require_editable(item, payload.version)
        evidence = json.dumps({"book_reference": candidate, "identity_digest": digest,
                               "collector_confirmed": True, "reference_only": True, "choice_origin": "SAVED_INVENTORY"})
        # Keep every earlier receipt auditable; release only its active lookup key.
        await db.execute("""update tcg.recognition_runs set idempotency_key='book-reference-history:'||id::text
            where owner_id=$1 and idempotency_key=$2""", access["owner_id"], key)
        await db.execute("""insert into tcg.recognition_runs
            (owner_id,inventory_id,top_catalogue_id,idempotency_key,status,decision,provider_evidence,created_by_user_id,completed_at)
            values($1,$2,$3,$4,'NEEDS_REVIEW','NEEDS_REVIEW',$5::jsonb,$6,now())""",
            access["owner_id"], inventory_id, item["catalogue_id"], key, evidence, user.user_id)
        await db.execute("update tcg.inventory_items set version=version+1,updated_at=clock_timestamp() where id=$1 and owner_id=$2", inventory_id, access["owner_id"])
    return {"message": "Cover saved. Your copy’s details are unchanged.", "version": item["version"]+1}


class BookIntakeRequest(ManualInventoryCreate):
    research_run_id: UUID | None = None
    research_candidate_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")

    @model_validator(mode="after")
    def research_pair(self):
        if bool(self.research_run_id) != bool(self.research_candidate_id):
            raise ValueError("Book research run and cover choice must be supplied together")
        return self


@router.post("/intake", status_code=201)
async def add_book(
    payload: BookIntakeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
):
    product = payload.new_catalogue
    if product is None or product.product_type != "COMIC" or product.comic_printing is None:
        raise HTTPException(422, "Choose a comic or manga and complete its printing details")
    if not product.language:
        raise HTTPException(422, "Book language is required")
    if payload.language and payload.language.casefold() != product.language.casefold():
        raise HTTPException(422, "The copy and book printing must use the same language")
    if payload.grading_company:
        if not payload.certificate_number:
            raise HTTPException(422, "Enter the graded book's certificate number")
        payload.grading_company = payload.grading_company.upper()
    candidate = None
    fields = {**product.comic_printing.model_dump(), "language": product.language}
    if payload.research_run_id:
        async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
            evidence = await db.fetchval("""select provider_evidence from tcg.recognition_runs
                where id=$1 and owner_id=$2 and status='NEEDS_REVIEW'""", payload.research_run_id, access["owner_id"])
        if isinstance(evidence, str): evidence = json.loads(evidence)
        candidates = (evidence or {}).get("book_result", {}).get("research", {}).get("candidates", [])
        candidate = next((c for c in candidates if c["id"] == payload.research_candidate_id), None)
        if not candidate or identity_digest(fields) != identity_digest(candidate["fields"]):
            raise HTTPException(422, "Book details changed. Choose the matching cover again or save without a publisher cover.")
    try:
        intake = ManualInventoryCreate.model_validate(payload.model_dump(exclude={"research_run_id", "research_candidate_id"}))
        result = await create_inventory_intake(intake, request, user, idempotency_key)
        if candidate and candidate.get("image_url"):
            # Intake already has its durable idempotency receipt. If this write
            # fails, retrying the same save reuses that copy before adding art.
            inventory_id = UUID(str(result["inventory"]["id"]))
            catalogue_id = UUID(str(result["catalogue"]["id"]))
            evidence = json.dumps({"book_reference": candidate, "identity_digest": identity_digest(fields),
                                   "source_run_id": str(payload.research_run_id), "collector_confirmed": True})
            async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
                await db.execute("""insert into tcg.recognition_runs
                    (owner_id,inventory_id,top_catalogue_id,idempotency_key,status,decision,
                     provider_evidence,created_by_user_id,completed_at)
                    select $1,i.id,i.catalogue_id,$4,'NEEDS_REVIEW','NEEDS_REVIEW',$5::jsonb,$6,now()
                    from tcg.inventory_items i where i.id=$2 and i.owner_id=$1 and i.catalogue_id=$3
                    on conflict(owner_id,idempotency_key) do nothing""",
                    access["owner_id"],inventory_id,catalogue_id,f"book-reference:{inventory_id}",evidence,user.user_id)
        return result
    except asyncpg.UniqueViolationError as exc:
        # Do not disclose another collector's ownership or inventory ID.
        raise HTTPException(409, "This graded certificate is already recorded. Check your inventory or contact Drop Rate.") from exc
