"""Owner-bound manual intake for comics, graded comics and manga."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID
import json

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import Field, model_validator

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .inventory_intake import create_inventory_intake
from .schemas import ManualInventoryCreate
from .db import user_connection
from .book_research import identity_digest

router = APIRouter(prefix="/api/v1/owner/books", tags=["owner-books"])


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
