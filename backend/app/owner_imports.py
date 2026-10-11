"""Restricted Seller Hub bridge to the EXISTING deterministic import workflow.

The founder/admin /api/v1/imports APIs are intentionally untouched. Reuse
their preview, review/skip, idempotent commit, and Collectr snapshot logic,
but expose *only* owner-scoped actions to accounts with OWNER portal access.
The global catalogue / enrichment / publication endpoints stay admin-only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

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
