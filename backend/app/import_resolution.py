from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .inventory_intake import CARD_CONDITIONS, _find_exact_catalogue, _manual_identity_key
from .schemas import ManualCatalogueCreate, SealStatus


router = APIRouter(prefix="/api/v1/imports", tags=["inventory-import-review"])

ResolutionAction = Literal["MATCH_EXISTING", "CREATE_CATALOGUE", "SKIP"]
IDENTITY_REVIEW_ISSUES = {
    "missing_name",
    "missing_game",
    "missing_set",
    "missing_card_number",
    "ambiguous_catalogue_match",
    "catalogue_not_found",
}


class ImportCandidateResolveRequest(BaseModel):
    version: int = Field(ge=1)
    action: ResolutionAction
    catalogue_id: UUID | None = None
    new_catalogue: ManualCatalogueCreate | None = None
    quantity: int | None = Field(default=None, ge=1, le=1000)
    acquisition_cost_minor: int | None = Field(default=None, ge=0)
    condition: str | None = Field(default=None, max_length=80)
    seal_status: SealStatus | None = None
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ImportCandidateResolveRequest":
        if self.action == "MATCH_EXISTING":
            if self.catalogue_id is None or self.new_catalogue is not None:
                raise ValueError("MATCH_EXISTING requires catalogue_id only")
        elif self.action == "CREATE_CATALOGUE":
            if self.new_catalogue is None or self.catalogue_id is not None:
                raise ValueError("CREATE_CATALOGUE requires new_catalogue only")
        else:
            if self.catalogue_id is not None or self.new_catalogue is not None:
                raise ValueError("SKIP does not accept catalogue identity fields")

        supplied = self.model_fields_set
        company_set = "grading_company" in supplied
        grade_set = "grade" in supplied
        if company_set != grade_set:
            raise ValueError("grading_company and grade must be updated together")
        if company_set and ((self.grading_company is None) != (self.grade is None)):
            raise ValueError("grading_company and grade must both be set or both cleared")
        if self.condition is not None and self.condition not in CARD_CONDITIONS:
            raise ValueError("condition must use the Drop Rate / TCGplayer condition scale")
        return self


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        "select id from tcg.owners where active order by founder_slot nulls last limit 1"
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


def _normalise_catalogue_identity(normalized: dict, catalogue: asyncpg.Record) -> dict:
    result = dict(normalized)
    result.update(
        {
            "product_type": catalogue["product_type"],
            "game": catalogue["game"],
            "name": catalogue["name"],
            "set_name": catalogue["set_name"],
            "card_number": catalogue["card_number"],
            "variant": catalogue["variant"],
            "rarity": catalogue["rarity"],
        }
    )
    if catalogue["language"]:
        result["language"] = catalogue["language"]
    return result


def _apply_physical_corrections(normalized: dict, payload: ImportCandidateResolveRequest) -> dict:
    result = dict(normalized)
    for field in (
        "quantity",
        "acquisition_cost_minor",
        "condition",
        "seal_status",
        "grading_company",
        "grade",
        "certificate_number",
        "language",
    ):
        if field in payload.model_fields_set:
            result[field] = getattr(payload, field)
    return result


def _validate_resolved_physical_state(
    normalized: dict,
    *,
    original_issues: set[str],
    corrected_fields: set[str],
) -> None:
    if "invalid_quantity" in original_issues and "quantity" not in corrected_fields:
        raise HTTPException(
            status_code=422,
            detail="This row had an invalid quantity. Enter the intended quantity before resolving it.",
        )

    product_type = normalized.get("product_type")
    company = normalized.get("grading_company")
    grade = normalized.get("grade")
    certificate = normalized.get("certificate_number")

    if bool(company) != bool(grade):
        raise HTTPException(status_code=422, detail="Grading company and grade must both be set or both cleared")
    if certificate and not company:
        raise HTTPException(status_code=422, detail="Certificate number requires grading company and grade")

    if product_type == "CARD":
        if normalized.get("seal_status") is not None:
            raise HTTPException(status_code=422, detail="Card inventory cannot use seal_status")
        condition = normalized.get("condition")
        if condition is not None and condition not in CARD_CONDITIONS:
            raise HTTPException(status_code=422, detail="Card condition is not recognised")
    else:
        if normalized.get("condition") is not None:
            raise HTTPException(status_code=422, detail="Sealed/collection products cannot use card condition")
        if company or grade or certificate:
            raise HTTPException(status_code=422, detail="Grading fields are only supported for card inventory")


def _remaining_issues(
    original_issues: list[str],
    *,
    payload: ImportCandidateResolveRequest,
    normalized: dict,
) -> list[str]:
    issues = set(original_issues) - IDENTITY_REVIEW_ISSUES
    corrected = payload.model_fields_set
    if "quantity" in corrected:
        issues.discard("invalid_quantity")
    if "acquisition_cost_minor" in corrected:
        issues.discard("invalid_purchase_cost")
        issues.discard("non_gbp_purchase_cost")
    if "condition" in corrected:
        issues.discard("unrecognised_card_condition")
    if "grading_company" in corrected and "grade" in corrected:
        issues.discard("incomplete_grading_pair")
    if "certificate_number" in corrected or normalized.get("grading_company"):
        issues.discard("certificate_without_grade")
    return sorted(issues)


async def _create_or_reuse_catalogue(
    connection: asyncpg.Connection,
    product: ManualCatalogueCreate,
) -> tuple[asyncpg.Record, bool]:
    catalogue = await _find_exact_catalogue(connection, product)
    if catalogue is not None:
        return catalogue, False

    catalogue = await connection.fetchrow(
        """
        insert into tcg.catalogue_products(
            identity_key, product_type, game, name, set_name,
            card_number, variant, rarity, language
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        on conflict (identity_key) do nothing
        returning *
        """,
        _manual_identity_key(product),
        product.product_type,
        product.game,
        product.name,
        product.set_name,
        product.card_number,
        product.variant,
        product.rarity,
        product.language,
    )
    if catalogue is not None:
        return catalogue, True

    catalogue = await _find_exact_catalogue(connection, product)
    if catalogue is None:
        raise HTTPException(
            status_code=409,
            detail="Catalogue identity was created concurrently. Search the catalogue and retry.",
        )
    return catalogue, False


@router.get("/{batch_id}/review")
async def list_import_review_candidates(
    batch_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        batch = await connection.fetchrow(
            "select id, status, version from tcg.import_batches where id = $1 and owner_id = $2",
            batch_id,
            owner["id"],
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="Import batch not found")
        total = await connection.fetchval(
            """
            select count(*) from tcg.import_candidates
            where batch_id = $1 and owner_id = $2 and status = 'REVIEW'
            """,
            batch_id,
            owner["id"],
        )
        rows = await connection.fetch(
            """
            select id, source_row, quantity, raw_record, normalized_record,
                   catalogue_id, status, issues
            from tcg.import_candidates
            where batch_id = $1 and owner_id = $2 and status = 'REVIEW'
            order by source_row, id
            limit $3 offset $4
            """,
            batch_id,
            owner["id"],
            limit,
            offset,
        )
        return jsonable_encoder(
            {
                "batch": dict(batch),
                "total": int(total or 0),
                "limit": limit,
                "offset": offset,
                "items": [dict(row) for row in rows],
            }
        )


@router.post("/{batch_id}/candidates/{candidate_id}/resolve")
async def resolve_import_candidate(
    batch_id: UUID,
    candidate_id: UUID,
    payload: ImportCandidateResolveRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        async with connection.transaction():
            batch = await connection.fetchrow(
                """
                select * from tcg.import_batches
                where id = $1 and owner_id = $2
                for update
                """,
                batch_id,
                owner["id"],
            )
            if batch is None:
                raise HTTPException(status_code=404, detail="Import batch not found")
            if batch["status"] != "PREVIEW":
                raise HTTPException(status_code=409, detail="Only PREVIEW batches can be reviewed")
            if batch["version"] != payload.version:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "Import batch changed", "current_version": batch["version"]},
                )

            candidate = await connection.fetchrow(
                """
                select * from tcg.import_candidates
                where id = $1 and batch_id = $2 and owner_id = $3
                for update
                """,
                candidate_id,
                batch_id,
                owner["id"],
            )
            if candidate is None:
                raise HTTPException(status_code=404, detail="Import candidate not found")
            if candidate["status"] in {"COMMITTED", "SKIPPED"}:
                raise HTTPException(status_code=409, detail="This import row can no longer be edited")

            if payload.action == "SKIP":
                issues = sorted(set(candidate["issues"] or []) | {"founder_skipped"})
                updated_candidate = await connection.fetchrow(
                    """
                    update tcg.import_candidates
                    set status = 'SKIPPED', catalogue_id = null, issues = $2::jsonb
                    where id = $1
                    returning *
                    """,
                    candidate_id,
                    json.dumps(issues),
                )
                catalogue_created = False
            else:
                if payload.action == "MATCH_EXISTING":
                    catalogue = await connection.fetchrow(
                        "select * from tcg.catalogue_products where id = $1",
                        payload.catalogue_id,
                    )
                    if catalogue is None:
                        raise HTTPException(status_code=404, detail="Catalogue product not found")
                    catalogue_created = False
                else:
                    assert payload.new_catalogue is not None
                    catalogue, catalogue_created = await _create_or_reuse_catalogue(
                        connection, payload.new_catalogue
                    )

                normalized = _normalise_catalogue_identity(candidate["normalized_record"], catalogue)
                normalized = _apply_physical_corrections(normalized, payload)
                _validate_resolved_physical_state(
                    normalized,
                    original_issues=set(candidate["issues"] or []),
                    corrected_fields=set(payload.model_fields_set),
                )
                issues = _remaining_issues(
                    list(candidate["issues"] or []), payload=payload, normalized=normalized
                )
                quantity = int(normalized.get("quantity") or candidate["quantity"])
                normalized["quantity"] = quantity
                next_status = "READY" if not issues else "REVIEW"
                updated_candidate = await connection.fetchrow(
                    """
                    update tcg.import_candidates
                    set quantity = $2,
                        normalized_record = $3::jsonb,
                        catalogue_id = $4,
                        status = $5,
                        issues = $6::jsonb
                    where id = $1
                    returning *
                    """,
                    candidate_id,
                    quantity,
                    json.dumps(normalized),
                    catalogue["id"],
                    next_status,
                    json.dumps(issues),
                )

            updated_batch = await connection.fetchrow(
                """
                update tcg.import_batches
                set version = version + 1
                where id = $1 and owner_id = $2 and version = $3
                returning *
                """,
                batch_id,
                owner["id"],
                payload.version,
            )
            if updated_batch is None:
                raise HTTPException(status_code=409, detail="Import batch changed; refresh and retry")

            counts = await connection.fetchrow(
                """
                select
                    count(*) filter (where status = 'REVIEW')::int as review_rows,
                    coalesce(sum(quantity) filter (where status = 'READY'), 0)::int as ready_units,
                    count(*) filter (where status = 'SKIPPED')::int as skipped_rows
                from tcg.import_candidates
                where batch_id = $1 and owner_id = $2
                """,
                batch_id,
                owner["id"],
            )
            return jsonable_encoder(
                {
                    "batch": dict(updated_batch),
                    "candidate": dict(updated_candidate),
                    "review_rows": counts["review_rows"],
                    "ready_units": counts["ready_units"],
                    "skipped_rows": counts["skipped_rows"],
                    "catalogue_created": catalogue_created,
                }
            )
