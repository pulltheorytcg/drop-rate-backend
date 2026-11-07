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
from .import_catalogue_search import CATALOGUE_SEARCH_SQL, search_tokens

from .access_control import require_owner_portal_request
from .owner_auto_imports import upload_collection, add_recognised, confirm_candidate, skip_candidate
from .imports import (
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
    """Search canonical identities across fields; never other sellers' stock.

    The review UI prefills e.g. 'OP14-041 The Azure Sea\'s Seven'. Requiring
    that entire phrase inside ONE column returned zero results. Instead all
    literal tokens must occur across the identity fields. A result is only a
    suggestion: the existing explicit review, owner and commit gates remain.
    """
    product_type = (product_type or "").strip().upper()
    if product_type and product_type not in {"CARD", "SEALED", "COLLECTION"}:
        return {"items": []}
    term = q.strip()
    tokens = search_tokens(term)
    if len(term) < 2 or not tokens:
        return {"items": []}
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        rows = await connection.fetch(CATALOGUE_SEARCH_SQL, term, product_type, tokens)
    return jsonable_encoder({"items": [dict(row) for row in rows]})


router.add_api_route("/upload", upload_collection, methods=["POST"], status_code=201)
router.add_api_route("/preview", preview_import, methods=["POST"], status_code=201)
router.add_api_route("", list_import_batches, methods=["GET"])
router.add_api_route("/{batch_id}", get_import_batch, methods=["GET"])
router.add_api_route("/{batch_id}/commit", add_recognised, methods=["POST"])
router.add_api_route(
    "/{batch_id}/candidates/{candidate_id}/resolve",
    confirm_candidate,
    methods=["POST"],
)
router.add_api_route(
    "/{batch_id}/candidates/{candidate_id}/skip",
    skip_candidate,
    methods=["POST"],
)
