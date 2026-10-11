from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .imports import _owner


router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

# These issues are fully resolved by a human explicitly choosing the canonical
# catalogue product. Physical-data issues remain Action Required until handled
# through a dedicated workflow or the row is deliberately skipped.
IDENTITY_REVIEW_ISSUES = {
    "missing_name",
    "missing_game",
    "missing_set",
    "missing_card_number",
    "ambiguous_catalogue_match",
    "catalogue_not_found",
    # A seller may clear this restriction only by selecting an existing
    # canonical match. It cannot create a new shared catalogue identity.
    "catalogue_admin_review_required",
}


class ImportCandidateResolutionRequest(BaseModel):
    version: int = Field(ge=1)
    catalogue_id: UUID


class ImportCandidateSkipRequest(BaseModel):
    version: int = Field(ge=1)


def _json_value(value: Any, *, expected_type: type, fallback: Any) -> Any:
    """Handle asyncpg JSON/JSONB values whether returned decoded or as text."""

    if value is None:
        return fallback
    decoded = value
    if isinstance(value, str):
        decoded = json.loads(value)
    if not isinstance(decoded, expected_type):
        raise ValueError("Stored import JSON has an unexpected shape")
    return decoded


def remaining_issues_after_catalogue_selection(issues: list[str]) -> list[str]:
    """Remove only identity issues a human catalogue choice actually resolves."""

    return sorted({issue for issue in issues if issue not in IDENTITY_REVIEW_ISSUES})


async def _locked_preview_batch(
    connection: asyncpg.Connection,
    *,
    batch_id: UUID,
    owner_id: UUID,
    expected_version: int,
) -> asyncpg.Record:
    batch = await connection.fetchrow(
        """
        select *
        from tcg.import_batches
        where id = $1 and owner_id = $2
        for update
        """,
        batch_id,
        owner_id,
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch["version"] != expected_version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Import batch changed",
                "current_version": batch["version"],
            },
        )
    if batch["status"] != "PREVIEW":
        raise HTTPException(
            status_code=409,
            detail="Only PREVIEW import batches can be reviewed",
        )
    return batch


async def _locked_candidate(
    connection: asyncpg.Connection,
    *,
    batch_id: UUID,
    candidate_id: UUID,
    owner_id: UUID,
) -> asyncpg.Record:
    candidate = await connection.fetchrow(
        """
        select *
        from tcg.import_candidates
        where id = $1 and batch_id = $2 and owner_id = $3
        for update
        """,
        candidate_id,
        batch_id,
        owner_id,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Import candidate not found")
    if candidate["status"] == "COMMITTED":
        raise HTTPException(status_code=409, detail="Committed import rows are immutable")
    return candidate


async def _batch_summary(
    connection: asyncpg.Connection,
    *,
    batch_id: UUID,
    owner_id: UUID,
) -> dict[str, int]:
    row = await connection.fetchrow(
        """
        select
            coalesce(sum(quantity) filter (where status = 'READY'), 0)::int as ready_units,
            count(*) filter (where status = 'REVIEW')::int as review_rows,
            count(*) filter (where status = 'SKIPPED')::int as skipped_rows
        from tcg.import_candidates
        where batch_id = $1 and owner_id = $2
        """,
        batch_id,
        owner_id,
    )
    return dict(row)


async def _bump_batch_version(
    connection: asyncpg.Connection,
    *,
    batch_id: UUID,
    owner_id: UUID,
    expected_version: int,
) -> int:
    version = await connection.fetchval(
        """
        update tcg.import_batches
        set version = version + 1
        where id = $1 and owner_id = $2 and version = $3 and status = 'PREVIEW'
        returning version
        """,
        batch_id,
        owner_id,
        expected_version,
    )
    if version is None:
        current = await connection.fetchval(
            "select version from tcg.import_batches where id = $1 and owner_id = $2",
            batch_id,
            owner_id,
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Import batch not found")
        raise HTTPException(
            status_code=409,
            detail={"message": "Import batch changed", "current_version": current},
        )
    return int(version)


def _candidate_response(row: asyncpg.Record) -> dict[str, Any]:
    payload = dict(row)
    payload["normalized_record"] = _json_value(
        payload.get("normalized_record"), expected_type=dict, fallback={}
    )
    payload["issues"] = _json_value(payload.get("issues"), expected_type=list, fallback=[])
    return payload


@router.post("/{batch_id}/candidates/{candidate_id}/resolve")
async def resolve_import_candidate(
    batch_id: UUID,
    candidate_id: UUID,
    payload: ImportCandidateResolutionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Resolve a REVIEW row by explicitly selecting a canonical catalogue item."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        await _locked_preview_batch(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
            expected_version=payload.version,
        )
        candidate = await _locked_candidate(
            connection,
            batch_id=batch_id,
            candidate_id=candidate_id,
            owner_id=owner["id"],
        )
        if candidate["status"] != "REVIEW":
            raise HTTPException(
                status_code=409,
                detail="Only Action Required import rows can be resolved",
            )

        catalogue = await connection.fetchrow(
            """
            select id, product_type, game, name, set_name, card_number,
                   variant, rarity, language
            from tcg.catalogue_products
            where id = $1
            """,
            payload.catalogue_id,
        )
        if catalogue is None:
            raise HTTPException(status_code=404, detail="Catalogue product not found")

        normalized = _json_value(
            candidate["normalized_record"], expected_type=dict, fallback={}
        )
        expected_product_type = normalized.get("product_type")
        if expected_product_type and catalogue["product_type"] != expected_product_type:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Selected catalogue product has a different product type",
                    "expected": expected_product_type,
                    "selected": catalogue["product_type"],
                },
            )

        original_issues = _json_value(candidate["issues"], expected_type=list, fallback=[])
        remaining_issues = remaining_issues_after_catalogue_selection(original_issues)
        new_status = "READY" if not remaining_issues else "REVIEW"

        updated_candidate = await connection.fetchrow(
            """
            update tcg.import_candidates
            set catalogue_id = $1,
                status = $2,
                issues = $3::jsonb
            where id = $4 and batch_id = $5 and owner_id = $6
            returning id, source_row, quantity, normalized_record,
                      catalogue_id, status, issues
            """,
            catalogue["id"],
            new_status,
            json.dumps(remaining_issues),
            candidate_id,
            batch_id,
            owner["id"],
        )
        new_version = await _bump_batch_version(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
            expected_version=payload.version,
        )
        summary = await _batch_summary(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
        )

        return jsonable_encoder(
            {
                "batch_id": batch_id,
                "version": new_version,
                "candidate": _candidate_response(updated_candidate),
                "catalogue": dict(catalogue),
                "summary": summary,
            }
        )


@router.post("/{batch_id}/candidates/{candidate_id}/skip")
async def skip_import_candidate(
    batch_id: UUID,
    candidate_id: UUID,
    payload: ImportCandidateSkipRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Deliberately exclude one source row from the eventual inventory commit."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        await _locked_preview_batch(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
            expected_version=payload.version,
        )
        candidate = await _locked_candidate(
            connection,
            batch_id=batch_id,
            candidate_id=candidate_id,
            owner_id=owner["id"],
        )
        if candidate["status"] not in {"REVIEW", "READY"}:
            raise HTTPException(
                status_code=409,
                detail="Only uncommitted import rows can be skipped",
            )

        updated_candidate = await connection.fetchrow(
            """
            update tcg.import_candidates
            set status = 'SKIPPED'
            where id = $1 and batch_id = $2 and owner_id = $3
            returning id, source_row, quantity, normalized_record,
                      catalogue_id, status, issues
            """,
            candidate_id,
            batch_id,
            owner["id"],
        )
        new_version = await _bump_batch_version(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
            expected_version=payload.version,
        )
        summary = await _batch_summary(
            connection,
            batch_id=batch_id,
            owner_id=owner["id"],
        )

        return jsonable_encoder(
            {
                "batch_id": batch_id,
                "version": new_version,
                "candidate": _candidate_response(updated_candidate),
                "summary": summary,
            }
        )
