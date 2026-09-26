from __future__ import annotations

from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .shopify_completeness import build_shopify_product_plan, media_completeness
from .shopify_pipeline import _media_assets_for_item, _test_sync_missing


router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])


def _increment(counts: dict[str, int], values: list[str]) -> None:
    for value in values:
        counts[value] = counts.get(value, 0) + 1


def summarize_local_readiness(
    rows: list[Mapping[str, Any]],
    media_assets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarise unsynced inventory without making any Shopify network calls."""

    operational_ready = 0
    media_ready = 0
    operational_blockers: dict[str, int] = {}
    media_blockers: dict[str, int] = {}
    next_operational: list[dict[str, Any]] = []
    next_media: list[dict[str, Any]] = []

    for item in rows:
        missing = _test_sync_missing(item)
        if missing:
            _increment(operational_blockers, missing)
            if len(next_operational) < 10:
                next_operational.append(
                    {
                        "id": item["id"],
                        "inventory_code": item["inventory_code"],
                        "name": item["name"],
                        "card_number": item["card_number"],
                        "status": item["status"],
                        "missing": missing,
                    }
                )
            continue

        operational_ready += 1
        plan = build_shopify_product_plan(item)
        media = media_completeness(
            plan["mediaPolicy"],
            _media_assets_for_item(item, media_assets),
        )
        blockers = list(media["blockers"])
        if not blockers:
            media_ready += 1
            continue

        _increment(media_blockers, blockers)
        if len(next_media) < 10:
            next_media.append(
                {
                    "id": item["id"],
                    "inventory_code": item["inventory_code"],
                    "name": item["name"],
                    "card_number": item["card_number"],
                    "media_policy": plan["mediaPolicy"],
                    "missing": blockers,
                }
            )

    return {
        "considered": len(rows),
        "operational_ready": operational_ready,
        "operational_blocked": len(rows) - operational_ready,
        "operational_blockers": operational_blockers,
        "media_ready": media_ready,
        "media_blocked": operational_ready - media_ready,
        "media_blockers": media_blockers,
        "next_operational_items": next_operational,
        "next_media_items": next_media,
    }


@router.get("/readiness")
async def shopify_local_readiness(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Founder-scoped local Shopify funnel; never calls Shopify or publishes."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        if owner["role"] != "FOUNDER":
            raise HTTPException(
                status_code=403,
                detail="Only a founder can view Shopify readiness",
            )

        rows = await connection.fetch(
            """
            select
                i.id,i.catalogue_id,i.owner_id,i.inventory_code,i.version,i.status,
                i.identity_confirmed,i.acquisition_cost_minor,i.store_price_minor,
                i.storage_location_id,i.language,i.condition,i.seal_status,
                i.grading_company,i.grade,
                p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
                p.rarity,p.language as catalogue_language,
                sl.id as registered_location_id,
                sl.active as registered_location_active
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.storage_locations sl on sl.id=i.storage_location_id
            left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            left join tcg.listing_inventory_members lim
              on lim.inventory_id=i.id and lim.state <> 'REMOVED'
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and sil.id is null
              and lim.id is null
            order by i.updated_at,i.inventory_code
            """,
            owner["id"],
        )
        media_rows = await connection.fetch(
            """
            select catalogue_id,inventory_id,scope,side,
                   approval_status,rights_status,shopify_file_status
            from tcg.media_assets
            where owner_id=$1
              and approval_status='APPROVED'
              and rights_status='VERIFIED'
              and shopify_file_status='READY'
            order by created_at,id
            """,
            owner["id"],
        )

    result = summarize_local_readiness(
        [dict(row) for row in rows],
        [dict(row) for row in media_rows],
    )
    result["scope"] = "UNSYNCED_FOUNDER_INVENTORY"
    result["network_calls"] = 0
    result["publication_actions"] = 0
    return jsonable_encoder(result)
