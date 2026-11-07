"""Owner-scoped, read-only decisions from Drop Rate's shared media engine.

This endpoint never fetches remote bytes, approves media, changes Shopify,
creates an eBay offer or claims Whatnot publishing is connected.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .media_resolver import resolve_media
from .ownership import current_owner
from .settings import get_settings


router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/resolve/{inventory_id}")
async def owner_media_decisions(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Preview consistent selections for the active owner and every channel."""
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await current_owner(connection)
        item = await connection.fetchrow(
            """
            select i.*, p.product_type,p.game,p.name,p.set_name,p.card_number,
                   p.variant,p.rarity,p.language as catalogue_language
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where i.id=$1 and i.owner_id=$2
            """,
            inventory_id, owner["id"],
        )
        if item is None:
            raise HTTPException(404, "Inventory item not found")
        # Never include another owner's physical photos even if RLS changes.
        # Canonical assets are shared exact-print media only, with the resolver
        # independently checking rights, variant, language and approval.
        media = await connection.fetch(
            """
            select * from tcg.media_assets
            where (scope='INVENTORY_ITEM' and inventory_id=$1 and owner_id=$2)
               or (scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
                   and catalogue_id=$3)
            order by approved_at desc nulls last,created_at desc,id desc
            limit 250
            """,
            inventory_id, owner["id"], item["catalogue_id"],
        )
        item_dict = dict(item)
        assets = [dict(row) for row in media]
        threshold = get_settings().media_physical_photo_threshold_minor
        channels = {
            channel: resolve_media(
                item_dict, assets,
                channel=channel,
                purpose="DISPLAY" if channel == "DROP_RATE" else "LISTING",
                threshold_minor=threshold,
            )
            for channel in ("DROP_RATE", "SHOPIFY", "EBAY", "WHATNOT")
        }
        return jsonable_encoder({
            "inventory_id": inventory_id,
            "inventory_code": item_dict["inventory_code"],
            "channels": channels,
            "mutated": False,
        })
