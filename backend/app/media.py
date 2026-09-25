from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Mapping
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .shopify_completeness import media_policy


router = APIRouter(prefix="/api/v1/media", tags=["media"])


class MediaAssetCreate(BaseModel):
    scope: Literal["CATALOGUE", "INVENTORY"]
    catalogue_id: UUID | None = None
    inventory_id: UUID | None = None
    asset_role: Literal["FRONT", "BACK", "OTHER"]
    asset_url: str = Field(min_length=1, max_length=2000)
    source_kind: Literal[
        "FOUNDER_UPLOAD",
        "CONSIGNOR_UPLOAD",
        "LICENSED_PROVIDER",
        "MIGRATED",
    ]
    source_provider: str | None = Field(default=None, max_length=255)
    source_reference: str | None = Field(default=None, max_length=2000)
    rights_basis: Literal[
        "OWNED_PHOTOGRAPH",
        "LICENSED_PROVIDER",
        "EXPLICIT_PERMISSION",
        "PUBLIC_DOMAIN",
    ]
    rights_reference: str = Field(min_length=1, max_length=2000)
    rights_checked_at: datetime | None = None
    rights_expires_at: datetime | None = None
    checksum_sha256: str | None = Field(default=None, max_length=64)
    alt_text: str = Field(default="", max_length=500)
    is_primary: bool = False
    display_order: int = Field(default=0, ge=0)

    @field_validator(
        "asset_url",
        "source_provider",
        "source_reference",
        "rights_reference",
        "checksum_sha256",
        "alt_text",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("asset_url")
    @classmethod
    def _https_asset_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme.casefold() != "https" or not parsed.netloc:
            raise ValueError("asset_url must be a public HTTPS URL")
        return value

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        lowered = value.casefold()
        if len(lowered) != 64 or any(ch not in "0123456789abcdef" for ch in lowered):
            raise ValueError("checksum_sha256 must contain exactly 64 hexadecimal characters")
        return lowered

    @model_validator(mode="after")
    def _target_shape(self) -> "MediaAssetCreate":
        if self.scope == "CATALOGUE":
            if self.catalogue_id is None or self.inventory_id is not None:
                raise ValueError("CATALOGUE media requires catalogue_id only")
        else:
            if self.inventory_id is None:
                raise ValueError("INVENTORY media requires inventory_id")
            if self.catalogue_id is not None:
                raise ValueError(
                    "INVENTORY media catalogue_id is resolved from the physical item"
                )
        if (
            self.rights_basis == "LICENSED_PROVIDER"
            and not (self.source_provider or "").strip()
        ):
            raise ValueError("Licensed provider media requires source_provider")
        if (
            self.rights_expires_at is not None
            and self.rights_checked_at is not None
            and self.rights_expires_at <= self.rights_checked_at
        ):
            raise ValueError("rights_expires_at must be after rights_checked_at")
        return self


class MediaDecision(BaseModel):
    version: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]


async def _founder(connection: asyncpg.Connection) -> asyncpg.Record:
    owner = await _owner(connection)
    if owner["role"] != "FOUNDER":
        raise HTTPException(
            status_code=403,
            detail="Only a founder can manage approved marketplace media",
        )
    return owner


def _asset_public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "scope": row["scope"],
        "catalogue_id": row["catalogue_id"],
        "inventory_id": row["inventory_id"],
        "asset_role": row["asset_role"],
        "asset_url": row["asset_url"],
        "alt_text": row["alt_text"],
        "approval_status": row["approval_status"],
        "is_primary": row["is_primary"],
        "display_order": row["display_order"],
        "rights_basis": row["rights_basis"],
        "source_kind": row["source_kind"],
        "source_provider": row["source_provider"],
        "rights_checked_at": row["rights_checked_at"],
        "rights_expires_at": row["rights_expires_at"],
        "version": row["version"],
    }


def media_readiness_for_item(
    item: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    policy = media_policy(item)
    inventory_id = str(item["id"])
    catalogue_id = str(item["catalogue_id"])

    valid = [
        asset
        for asset in assets
        if str(asset["catalogue_id"]) == catalogue_id
        and (
            (
                asset["scope"] == "INVENTORY"
                and str(asset["inventory_id"]) == inventory_id
            )
            or asset["scope"] == "CATALOGUE"
        )
    ]

    inventory_assets = [
        asset for asset in valid if asset["scope"] == "INVENTORY"
    ]
    catalogue_assets = [
        asset for asset in valid if asset["scope"] == "CATALOGUE"
    ]

    selected: list[Mapping[str, Any]] = []
    missing_roles: list[str] = []
    if policy == "PHYSICAL_ITEM_REQUIRED":
        required_roles = ["FRONT", "BACK"]
        for role in required_roles:
            matches = [
                asset
                for asset in inventory_assets
                if asset["asset_role"] == role
            ]
            if not matches:
                missing_roles.append(role)
                continue
            selected.append(matches[0])
    else:
        required_roles = ["FRONT"]
        inventory_front = [
            asset
            for asset in inventory_assets
            if asset["asset_role"] == "FRONT"
        ]
        catalogue_front = [
            asset
            for asset in catalogue_assets
            if asset["asset_role"] == "FRONT"
        ]
        if inventory_front:
            selected.append(inventory_front[0])
        elif catalogue_front:
            selected.append(catalogue_front[0])
        else:
            missing_roles.append("FRONT")

    blockers = [
        (
            f"approved physical {role.lower()} media"
            if policy == "PHYSICAL_ITEM_REQUIRED"
            else f"approved {role.lower()} media"
        )
        for role in missing_roles
    ]
    return {
        "complete": not blockers,
        "policy": policy,
        "requiredRoles": required_roles,
        "missingRoles": missing_roles,
        "blockers": blockers,
        "approvedMediaCount": len(selected),
        "selectedAssets": [_asset_public(asset) for asset in selected],
    }


async def _approved_assets_for_targets(
    connection: asyncpg.Connection,
    *,
    inventory_ids: list[UUID],
    catalogue_ids: list[UUID],
) -> list[asyncpg.Record]:
    if not inventory_ids and not catalogue_ids:
        return []
    return await connection.fetch(
        """
        select *
        from tcg.media_assets
        where approval_status='APPROVED'
          and media_type='IMAGE'
          and (rights_expires_at is null or rights_expires_at > clock_timestamp())
          and (
            (scope='INVENTORY' and inventory_id=any($1::uuid[]))
            or
            (scope='CATALOGUE' and catalogue_id=any($2::uuid[]))
          )
        order by
          case when scope='INVENTORY' then 0 else 1 end,
          is_primary desc,
          display_order,
          approved_at desc,
          id
        """,
        inventory_ids,
        catalogue_ids,
    )


async def resolve_media_readiness(
    connection: asyncpg.Connection,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    assets = await _approved_assets_for_targets(
        connection,
        inventory_ids=[item["id"]],
        catalogue_ids=[item["catalogue_id"]],
    )
    return media_readiness_for_item(item, list(assets))


async def resolve_media_readiness_batch(
    connection: asyncpg.Connection,
    items: list[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    inventory_ids = list(dict.fromkeys(item["id"] for item in items))
    catalogue_ids = list(dict.fromkeys(item["catalogue_id"] for item in items))
    assets = await _approved_assets_for_targets(
        connection,
        inventory_ids=inventory_ids,
        catalogue_ids=catalogue_ids,
    )
    rows = list(assets)
    return {
        str(item["id"]): media_readiness_for_item(item, rows)
        for item in items
    }


@router.get("/readiness/{inventory_id}")
async def media_readiness(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        item = await connection.fetchrow(
            """
            select
              i.id,i.catalogue_id,i.owner_id,i.grading_company,i.grade,
              i.condition,p.product_type,p.game,p.name,p.set_name,p.card_number
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where i.id=$1 and i.owner_id=$2
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        readiness = await resolve_media_readiness(connection, item)
        return jsonable_encoder(
            {
                "inventory_id": inventory_id,
                "inventory_code": await connection.fetchval(
                    "select inventory_code from tcg.inventory_items where id=$1",
                    inventory_id,
                ),
                **readiness,
            }
        )


@router.post("/assets", status_code=201)
async def create_media_asset(
    payload: MediaAssetCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _founder(connection)
        if payload.scope == "INVENTORY":
            target = await connection.fetchrow(
                """
                select id,catalogue_id,owner_id
                from tcg.inventory_items
                where id=$1 and owner_id=$2
                """,
                payload.inventory_id,
                owner["id"],
            )
            if target is None:
                raise HTTPException(
                    status_code=404,
                    detail="Physical inventory media target not found",
                )
            catalogue_id = target["catalogue_id"]
            inventory_id = target["id"]
            owner_id = target["owner_id"]
        else:
            exists = await connection.fetchval(
                "select exists(select 1 from tcg.catalogue_products where id=$1)",
                payload.catalogue_id,
            )
            if not exists:
                raise HTTPException(
                    status_code=404,
                    detail="Catalogue media target not found",
                )
            catalogue_id = payload.catalogue_id
            inventory_id = None
            owner_id = None

        row = await connection.fetchrow(
            """
            insert into tcg.media_assets(
              scope,catalogue_id,inventory_id,owner_id,asset_role,asset_url,
              source_kind,source_provider,source_reference,rights_basis,
              rights_reference,rights_checked_at,rights_expires_at,
              checksum_sha256,alt_text,is_primary,display_order,
              created_by_user_id
            ) values(
              $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
              coalesce($12,clock_timestamp()),$13,$14,$15,$16,$17,$18
            )
            returning *
            """,
            payload.scope,
            catalogue_id,
            inventory_id,
            owner_id,
            payload.asset_role,
            payload.asset_url,
            payload.source_kind,
            payload.source_provider,
            payload.source_reference,
            payload.rights_basis,
            payload.rights_reference,
            payload.rights_checked_at,
            payload.rights_expires_at,
            payload.checksum_sha256,
            payload.alt_text,
            payload.is_primary,
            payload.display_order,
            user.user_id,
        )
        return jsonable_encoder({"asset": _asset_public(row)})


@router.post("/assets/{asset_id}/decision")
async def decide_media_asset(
    asset_id: UUID,
    payload: MediaDecision,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _founder(connection)
        row = await connection.fetchrow(
            "select * from tcg.media_assets where id=$1 for update",
            asset_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Media asset not found")
        if row["version"] != payload.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Media asset changed",
                    "current_version": row["version"],
                },
            )

        updated = await connection.fetchrow(
            """
            update tcg.media_assets
            set approval_status=$2,
                approved_at=case when $2='APPROVED' then clock_timestamp() else null end,
                approved_by_user_id=case when $2='APPROVED' then $3 else null end,
                updated_at=clock_timestamp(),
                version=version+1
            where id=$1 and version=$4
            returning *
            """,
            asset_id,
            payload.decision,
            user.user_id,
            payload.version,
        )
        if updated is None:
            raise HTTPException(
                status_code=409,
                detail="Media asset changed during approval",
            )
        return jsonable_encoder({"asset": _asset_public(updated)})
