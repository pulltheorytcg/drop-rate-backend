from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import SUPPORTED_MARKET_SOURCES
from .market_ingestion import _owner


router = APIRouter(prefix="/api/v1/market/mappings", tags=["market-data"])


class MarketMappingCreate(BaseModel):
    catalogue_id: UUID
    source: str
    source_product_id: str = Field(min_length=1, max_length=10000)
    source_variant_id: str | None = Field(default=None, max_length=1000)
    match_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        source = value.upper().strip()
        if source not in SUPPORTED_MARKET_SOURCES:
            raise ValueError("Unsupported market source")
        return source

    @field_validator("source_product_id")
    @classmethod
    def clean_product_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_product_id is required")
        return cleaned

    @field_validator("source_variant_id")
    @classmethod
    def clean_variant_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class MarketMappingUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    source_product_id: str | None = Field(default=None, min_length=1, max_length=10000)
    source_variant_id: str | None = Field(default=None, max_length=1000)
    match_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None

    @field_validator("source_product_id")
    @classmethod
    def clean_product_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_product_id cannot be blank")
        return cleaned

    @field_validator("source_variant_id")
    @classmethod
    def clean_variant_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class MarketMappingDecision(BaseModel):
    expected_version: int = Field(ge=1)
    match_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


async def _catalogue_exists(connection: asyncpg.Connection, catalogue_id: UUID) -> bool:
    return bool(
        await connection.fetchval(
            "select exists(select 1 from tcg.catalogue_products where id = $1)",
            catalogue_id,
        )
    )


async def _mapping_row(connection: asyncpg.Connection, mapping_id: UUID) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select m.*,
               c.game,
               c.name as card_name,
               c.set_name,
               c.card_number,
               c.variant,
               c.rarity,
               c.language as catalogue_language
        from tcg.market_source_mappings m
        join tcg.catalogue_products c on c.id = m.catalogue_id
        where m.id = $1
        """,
        mapping_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Market mapping not found")
    return row


def _decision_metadata(
    existing: dict[str, Any] | None,
    *,
    action: Literal["VERIFIED", "REJECTED"],
    user_id: str,
    reason: str | None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata["review"] = {
        "status": action,
        "reviewed_by_user_id": user_id,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    return metadata


@router.get("")
async def list_market_mappings(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    source: str | None = Query(default=None),
    match_status: Literal["REVIEW", "VERIFIED", "REJECTED"] | None = Query(default=None),
    catalogue_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=250),
) -> dict:
    source_filter = source.upper().strip() if source else None
    if source_filter is not None and source_filter not in SUPPORTED_MARKET_SOURCES:
        raise HTTPException(status_code=404, detail="Unsupported market data source")

    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        rows = await connection.fetch(
            """
            select m.*,
                   c.game,
                   c.name as card_name,
                   c.set_name,
                   c.card_number,
                   c.variant,
                   c.rarity,
                   c.language as catalogue_language
            from tcg.market_source_mappings m
            join tcg.catalogue_products c on c.id = m.catalogue_id
            where ($1::text is null or m.source = $1)
              and ($2::text is null or m.match_status = $2)
              and ($3::uuid is null or m.catalogue_id = $3)
            order by m.updated_at desc, m.id
            limit $4
            """,
            source_filter,
            match_status,
            catalogue_id,
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("", status_code=201)
async def create_market_mapping(
    payload: MarketMappingCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        if not await _catalogue_exists(connection, payload.catalogue_id):
            raise HTTPException(status_code=404, detail="Catalogue product not found")

        metadata = dict(payload.metadata)
        metadata["created_by_user_id"] = str(user.user_id)

        try:
            row = await connection.fetchrow(
                """
                insert into tcg.market_source_mappings(
                    catalogue_id,
                    source,
                    source_product_id,
                    source_variant_id,
                    match_status,
                    match_confidence,
                    metadata
                ) values ($1,$2,$3,$4,'REVIEW',$5,$6::jsonb)
                returning id
                """,
                payload.catalogue_id,
                payload.source,
                payload.source_product_id,
                payload.source_variant_id,
                payload.match_confidence,
                json.dumps(metadata),
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409,
                detail="A mapping for this provider identity already exists",
            ) from exc

        return jsonable_encoder(dict(await _mapping_row(connection, row["id"])))


@router.patch("/{mapping_id}")
async def update_market_mapping(
    mapping_id: UUID,
    payload: MarketMappingUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        current = await _mapping_row(connection, mapping_id)
        if current["match_status"] != "REVIEW":
            raise HTTPException(
                status_code=409,
                detail="Only REVIEW mappings can be edited; create a new review mapping instead",
            )
        if current["version"] != payload.expected_version:
            raise HTTPException(status_code=409, detail="Mapping version conflict")

        source_product_id = payload.source_product_id or current["source_product_id"]
        source_variant_id = (
            payload.source_variant_id
            if "source_variant_id" in payload.model_fields_set
            else current["source_variant_id"]
        )
        match_confidence = (
            payload.match_confidence
            if payload.match_confidence is not None
            else float(current["match_confidence"])
        )
        metadata = dict(current["metadata"] or {})
        if payload.metadata is not None:
            metadata.update(payload.metadata)
        metadata["last_edited_by_user_id"] = str(user.user_id)

        try:
            row = await connection.fetchrow(
                """
                update tcg.market_source_mappings
                set source_product_id = $2,
                    source_variant_id = $3,
                    match_confidence = $4,
                    metadata = $5::jsonb,
                    version = version + 1,
                    updated_at = now()
                where id = $1
                  and match_status = 'REVIEW'
                  and version = $6
                returning id
                """,
                mapping_id,
                source_product_id,
                source_variant_id,
                match_confidence,
                json.dumps(metadata),
                payload.expected_version,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409,
                detail="A mapping for this provider identity already exists",
            ) from exc

        if row is None:
            raise HTTPException(status_code=409, detail="Mapping changed during update")
        return jsonable_encoder(dict(await _mapping_row(connection, mapping_id)))


async def _decide_mapping(
    connection: asyncpg.Connection,
    *,
    mapping_id: UUID,
    payload: MarketMappingDecision,
    user_id: str,
    status: Literal["VERIFIED", "REJECTED"],
) -> dict:
    current = await _mapping_row(connection, mapping_id)
    if current["match_status"] != "REVIEW":
        raise HTTPException(status_code=409, detail="Only REVIEW mappings can be decided")
    if current["version"] != payload.expected_version:
        raise HTTPException(status_code=409, detail="Mapping version conflict")

    if (
        status == "VERIFIED"
        and current["source"] in {"CARDMARKET", "TCGPLAYER"}
        and str(current["game"]).strip().casefold() == "pokemon"
    ):
        provider_variant = str(current["source_variant_id"] or "").strip().casefold()
        catalogue_variant = str(current["variant"] or "").strip().casefold()
        aliases = {
            "holo": "holofoil",
            "reverse holo": "reverse holofoil",
            "reverse": "reverse holofoil",
        }
        provider_variant = aliases.get(provider_variant, provider_variant)
        catalogue_variant = aliases.get(catalogue_variant, catalogue_variant)
        if catalogue_variant and not provider_variant:
            raise HTTPException(
                status_code=409,
                detail=f"{current['source']} Pokemon mapping requires a provider variant before verification",
            )
        if catalogue_variant and provider_variant != catalogue_variant:
            raise HTTPException(
                status_code=409,
                detail=f"{current['source']} provider variant does not match the catalogue variant",
            )

    metadata = _decision_metadata(
        dict(current["metadata"] or {}),
        action=status,
        user_id=user_id,
        reason=payload.reason,
    )
    # VERIFIED is a binary human trust decision: if identity is still uncertain,
    # leave the mapping in REVIEW rather than passing uncertain evidence downstream.
    confidence = 1.0 if status == "VERIFIED" else 0.0
    try:
        row = await connection.fetchrow(
            """
        update tcg.market_source_mappings
        set match_status = $2,
            match_confidence = $3,
            metadata = $4::jsonb,
            version = version + 1,
            updated_at = now()
        where id = $1
          and match_status = 'REVIEW'
          and version = $5
        returning id
        """,
        mapping_id,
        status,
        confidence,
        json.dumps(metadata),
            payload.expected_version,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=409,
            detail="A VERIFIED mapping already exists for this catalogue product and source",
        ) from exc
    if row is None:
        raise HTTPException(status_code=409, detail="Mapping changed during review")
    return dict(await _mapping_row(connection, mapping_id))


@router.post("/{mapping_id}/verify")
async def verify_market_mapping(
    mapping_id: UUID,
    payload: MarketMappingDecision,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        row = await _decide_mapping(
            connection,
            mapping_id=mapping_id,
            payload=payload,
            user_id=str(user.user_id),
            status="VERIFIED",
        )
        return jsonable_encoder(row)


@router.post("/{mapping_id}/reject")
async def reject_market_mapping(
    mapping_id: UUID,
    payload: MarketMappingDecision,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        row = await _decide_mapping(
            connection,
            mapping_id=mapping_id,
            payload=payload,
            user_id=str(user.user_id),
            status="REJECTED",
        )
        return jsonable_encoder(row)
