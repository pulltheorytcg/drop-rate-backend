"""Restricted Seller Hub bridge to the EXISTING deterministic import workflow.

The founder/admin /api/v1/imports APIs are intentionally untouched. Reuse
their preview, review/skip, idempotent commit, and Collectr snapshot logic,
but expose *only* owner-scoped actions to accounts with OWNER portal access.
The global catalogue / enrichment / publication endpoints stay admin-only.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection

from .access_control import require_owner_portal_request
from .import_review import resolve_import_candidate, skip_import_candidate
from .imports import (
    commit_import_batch,
    get_import_batch,
    list_import_batches,
    preview_import,
)

router = APIRouter(
    prefix="/api/v1/owner/imports",
    tags=["owner-csv-imports"],
    dependencies=[Depends(require_owner_portal_request)],
)

# Deliberately allowlisted. Do NOT include import_enrichment or other
# /api/v1/imports routes, and do NOT remove platform-admin protection from
# the original founder dashboard import router.
@router.get("/catalogue-search")
async def search_existing_catalogue_for_import(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    q: str = Query(min_length=2, max_length=150),
    product_type: str | None = Query(default=None),
) -> dict:
    """Search public canonical identities only; never other sellers' stock.

    A seller can choose a currently existing catalogue item for a CSV REVIEW
    row, but cannot create canonical products or alter anyone's inventory.
    """
    product_type = (product_type or "").strip().upper()
    if product_type and product_type not in {"CARD", "SEALED", "COLLECTION"}:
        return {"items": []}
    term = q.strip()
    if len(term) < 2:
        return {"items": []}
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select p.id,p.game,p.name,p.set_name,p.card_number,
                   p.variant,p.language,p.product_type
            from tcg.catalogue_products p
            where ($2::text = '' or p.product_type = $2)
              and (
                p.name ilike '%' || $1 || '%'
                or coalesce(p.card_number,'') ilike '%' || $1 || '%'
                or p.set_name ilike '%' || $1 || '%'
                or p.game ilike '%' || $1 || '%'
              )
            order by
              case when lower(p.card_number)=lower($1) then 0
                   when lower(p.name)=lower($1) then 1 else 2 end,
              p.game,p.set_name,p.name,p.card_number,p.id
            limit 16
            """,
            term, product_type,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


router.add_api_route("/preview", preview_import, methods=["POST"], status_code=201)
router.add_api_route("", list_import_batches, methods=["GET"])
router.add_api_route("/{batch_id}", get_import_batch, methods=["GET"])
router.add_api_route("/{batch_id}/commit", commit_import_batch, methods=["POST"])
router.add_api_route(
    "/{batch_id}/candidates/{candidate_id}/resolve",
    resolve_import_candidate,
    methods=["POST"],
)
router.add_api_route(
    "/{batch_id}/candidates/{candidate_id}/skip",
    skip_import_candidate,
    methods=["POST"],
)
