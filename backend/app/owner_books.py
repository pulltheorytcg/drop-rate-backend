"""Owner-bound manual intake for comics, graded comics and manga."""
from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .inventory_intake import create_inventory_intake
from .schemas import ManualInventoryCreate

router = APIRouter(prefix="/api/v1/owner/books", tags=["owner-books"])


@router.post("/intake", status_code=201)
async def add_book(
    payload: ManualInventoryCreate,
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
    try:
        return await create_inventory_intake(payload, request, user, idempotency_key)
    except asyncpg.UniqueViolationError as exc:
        # Do not disclose another collector's ownership or inventory ID.
        raise HTTPException(409, "This graded certificate is already recorded. Check your inventory or contact Drop Rate.") from exc
