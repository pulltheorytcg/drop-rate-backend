from __future__ import annotations

from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .media_resolver import (
    DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
    resolve_storefront_media,
)
from .ownership import current_owner as _owner
from .settings import get_settings
from .shopify_completeness import build_shopify_product_plan
from .shopify_pipeline import _media_assets_for_item, _test_sync_missing


router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])


def _increment(counts: dict[str, int], values: list[str]) -> None:
    for value in values:
        counts[value] = counts.get(value, 0) + 1


def summarize_local_readiness(
    rows: list[Mapping[str, Any]],
    media_assets: list[Mapping[str, Any]],
    *,
    physical_photo_threshold_minor: int = DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
) -> dict[str, Any]:
    """Summarise unsynced inventory without Shopify network calls."""

    operational_ready = 0
    media_ready = 0
    canonical_resolved = 0
    first_party_resolved = 0
    physical_capture_required = 0
    canonical_media_required = 0
    operational_blockers: dict[str, int] = {}
    media_blockers: dict[str, int] = {}
    next_operational: list[dict[str, Any]] = []
    next_media: list[dict[str, Any]] = []
    resolved_media_items: list[dict[str, Any]] = []

    for item in rows:
        missing = _test_sync_missing(
            item,
            physical_photo_threshold_minor=physical_photo_threshold_minor,
        )
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
        plan = build_shopify_product_plan(
            item,
            physical_photo_threshold_minor=physical_photo_threshold_minor,
        )
        media = resolve_storefront_media(
            item,
            _media_assets_for_item(item, media_assets),
            threshold_minor=physical_photo_threshold_minor,
        )
        blockers = list(media["blockers"])
        if not blockers:
            media_ready += 1
            if media["resolutionSource"] == "CANONICAL_STOREFRONT":
                canonical_resolved += 1
            elif media["resolutionSource"] == "FIRST_PARTY_CAPTURE":
                first_party_resolved += 1
            if len(resolved_media_items) < 10:
                resolved_media_items.append(
                    {
                        "id": item["id"],
                        "inventory_code": item["inventory_code"],
                        "name": item["name"],
                        "card_number": item["card_number"],
                        "resolution_source": media["resolutionSource"],
                        "rights_tier": media["rightsTier"],
                        "selection_reason": media["selectionReason"],
                        "physical_photos_required": media["physicalPhotosRequired"],
                        "selected_media": media["selectedMedia"],
                    }
                )
            continue

        if media["physicalPhotosRequired"]:
            physical_capture_required += 1
        else:
            canonical_media_required += 1
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
                    "resolution_source": media["resolutionSource"],
                    "rights_tier": media["rightsTier"],
                    "selection_reason": media["selectionReason"],
                    "physical_photos_required": media["physicalPhotosRequired"],
                    "physical_requirement_reasons": media["reasons"],
                    "action_required_reason": media["actionRequiredReason"],
                    "selected_media": media["selectedMedia"],
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
        "canonical_resolved": canonical_resolved,
        "first_party_resolved": first_party_resolved,
        "physical_capture_required": physical_capture_required,
        "canonical_media_required": canonical_media_required,
        "next_operational_items": next_operational,
        "next_media_items": next_media,
        "resolved_media_items": resolved_media_items,
        "policy": {
            "existing_image_first": True,
            "physical_photo_threshold_minor": physical_photo_threshold_minor,
        },
    }


@router.get("/readiness")
async def shopify_local_readiness(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Founder-scoped local Shopify funnel; never publishes."""

    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        if owner["owner_type"] != "FOUNDER":
            raise HTTPException(
                status_code=403,
                detail="Shopify readiness is available only for founder-owned inventory",
            )

        rows = await connection.fetch(
            """
            select
                i.id,i.catalogue_id,i.owner_id,i.inventory_code,i.version,i.status,
                i.identity_confirmed,i.acquisition_cost_minor,i.store_price_minor,
                i.market_value_minor,i.recommended_retail_minor,
                i.storage_location_id,i.language,i.condition,i.seal_status,
                i.grading_company,i.grade,i.condition_review_status,
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
              and i.sale_intent='FOR_SALE'
              and sil.id is null
              and lim.id is null
            order by i.updated_at,i.inventory_code
            """,
            owner["id"],
        )
        draft_rows = await connection.fetch(
            """
            select
                i.id,i.catalogue_id,i.owner_id,i.inventory_code,i.version,i.status,
                i.identity_confirmed,i.acquisition_cost_minor,i.store_price_minor,
                i.market_value_minor,i.recommended_retail_minor,
                i.storage_location_id,i.language,i.condition,i.seal_status,
                i.grading_company,i.grade,i.condition_review_status,
                p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
                p.rarity,p.language as catalogue_language,
                sl.id as registered_location_id,
                sl.active as registered_location_active
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.storage_locations sl on sl.id=i.storage_location_id
            join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            left join tcg.listing_inventory_members lim
              on lim.inventory_id=i.id and lim.state <> 'REMOVED'
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and i.sale_intent='FOR_SALE'
              and sil.sync_state='DRAFT'
              and lim.id is null
            order by i.updated_at,i.inventory_code
            """,
            owner["id"],
        )
        media_rows = await connection.fetch(
            """
            select *
            from tcg.media_assets
            where owner_id=$1 or scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
            order by created_at,id
            """,
            owner["id"],
        )

    result = summarize_local_readiness(
        [dict(row) for row in rows],
        [dict(row) for row in media_rows],
        physical_photo_threshold_minor=settings.media_physical_photo_threshold_minor,
    )
    linked_drafts = summarize_local_readiness(
        [dict(row) for row in draft_rows],
        [dict(row) for row in media_rows],
        physical_photo_threshold_minor=settings.media_physical_photo_threshold_minor,
    )
    linked_drafts["scope"] = "LINKED_SHOPIFY_DRAFTS"
    linked_drafts["network_calls"] = 0
    linked_drafts["publication_actions"] = 0

    result["scope"] = "UNSYNCED_FOUNDER_INVENTORY"
    result["network_calls"] = 0
    result["publication_actions"] = 0
    result["linked_drafts"] = linked_drafts
    return jsonable_encoder(result)
