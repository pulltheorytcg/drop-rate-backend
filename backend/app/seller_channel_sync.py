"""Seller-initiated publication using company stores and existing readiness gates."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .access_control import require_owner_portal
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_sales import EbayListRequest, publish_inventory_to_ebay
from .settings import get_settings
from .shopify_pipeline import publish_inventory_to_shopify

router = APIRouter(prefix="/api/v1/owner", tags=["seller-channels"])


class SyncRequest(BaseModel):
    version: int = Field(ge=1)


@router.post("/inventory/{inventory_id}/channels/{channel}/sync")
async def sync_inventory(
    inventory_id: UUID, channel: Literal["shopify", "ebay"], payload: SyncRequest,
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    settings = get_settings()
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        access = await require_owner_portal(connection)
        item = await connection.fetchrow(
            "select id,status,sale_intent,version from tcg.inventory_items where id=$1 and owner_id=$2",
            inventory_id, access["owner_id"],
        )
        if item is None:
            raise HTTPException(404, "Inventory item not found")
        if item["version"] != payload.version:
            raise HTTPException(409, "Inventory changed; refresh and try again")
        if item["status"] != "APPROVED" or item["sale_intent"] != "FOR_SALE":
            raise HTTPException(409, "Only approved inventory marked For sale can be synced")
        if channel == "shopify":
            if not settings.shopify_seller_sync_enabled or not settings.shopify_publish_enabled:
                raise HTTPException(409, "Seller sync to Drop Rate Shopify is not enabled yet")
            result = await publish_inventory_to_shopify(
                connection, inventory_id=inventory_id, owner_id=access["owner_id"],
                expected_version=payload.version, actor_user_id=user.user_id,
                automation_event_id=None, request_id=request.state.request_id, test_mode=False,
            )
            # Return only the seller-safe status; internal publication plans stay server-side.
            return {"inventory_id": str(inventory_id), "channel": "SHOPIFY", "status": result["status"]}

    if not settings.ebay_seller_sync_enabled or not settings.ebay_publish_enabled or not settings.ebay_shared_store_owner_id:
        raise HTTPException(409, "Seller sync to Drop Rate eBay is not enabled yet")
    result = await publish_inventory_to_ebay(inventory_id, EbayListRequest(version=payload.version), request, user)
    return {"inventory_id": str(inventory_id), "channel": "EBAY", "status": result["status"]}
