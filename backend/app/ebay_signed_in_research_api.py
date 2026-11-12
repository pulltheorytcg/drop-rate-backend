"""Owner-scoped, authenticated eBay UK paid-sales research preview.

Never fetches eBay, accepts no cookies, persists no unverified source claims
and never calls the older price-and-Store-Price apply path.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_signed_in_research import build_sold_search_url, preview_product_research
from .ebay_sold_pricing import _target_snapshot
from .ownership import current_owner as _owner

router = APIRouter(prefix="/api/v1/pricing/ebay-research", tags=["pricing"])

_INVENTORY_CODE = re.compile(r"INV-[A-Z0-9-]{6,56}\Z")
_ALLOWED_SALE_FIELDS = frozenset({
    "source", "sale_price_basis", "item_id", "title", "sold_at",
    "price_gbp", "shipping_gbp", "currency", "item_country",
    "condition_raw", "set_name", "card_number", "variant", "language",
})
_MAX_REVIEW_JSON_BYTES = 64_000


class ResearchPreviewBody(BaseModel):
    """Data is transient in the request, never persisted or sent to Shopify."""
    sales: list[dict[str, Any]] = Field(max_length=100)


def _validate_code(value: str) -> str:
    if not _INVENTORY_CODE.fullmatch(value):
        raise HTTPException(status_code=422, detail="Valid Inventory ID required")
    return value


def _validate_review_rows(rows: list[dict[str, Any]]) -> None:
    # Exclude seller usernames, buyer details, cookies, arbitrary HTML or
    # unbounded JSON before it ever reaches a log or preview.
    if len(json.dumps(rows, ensure_ascii=True)) > _MAX_REVIEW_JSON_BYTES:
        raise HTTPException(status_code=413, detail="Review evidence exceeds the 64 KB limit")
    for row in rows:
        if (not isinstance(row, dict)
                or not set(row).issubset(_ALLOWED_SALE_FIELDS)
                or any(isinstance(value, (dict, list, bool))
                       or (isinstance(value, str) and len(value) > 300)
                       for value in row.values())):
            raise HTTPException(status_code=422, detail="Only minimal sale evidence fields are accepted")


async def _owned_target(pool, user_id: UUID, request_id: str, inventory_code: str) -> dict[str, Any]:
    async with user_connection(pool, user_id, request_id, readonly_snapshot=True) as connection:
        owner = await _owner(connection)
        # Physical inventory remains owner-scoped even for founder operators.
        inventory_id = await connection.fetchval(
            "select id from tcg.inventory_items where owner_id=$1 and inventory_code=$2",
            owner["id"], _validate_code(inventory_code),
        )
        if inventory_id is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        item = await _target_snapshot(connection, owner["id"], inventory_id)
    return item


def _public_target(target: dict[str, Any]) -> dict[str, str | None]:
    return {
        "game": target["game"],
        "name": target["name"],
        "set_name": target["set_name"],
        "card_number": target["card_number"],
        "variant": target["variant"],
        "language": target["language"],
        "condition": target["condition"],
        "grading_company": target["grading_company"],
        "grade": target["grade"],
    }


@router.get("/inventory/{inventory_code}/search")
async def prepare_ebay_research(
    inventory_code: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    item = await _owned_target(
        request.app.state.db_pool, user.user_id, request.state.request_id, inventory_code
    )
    canonical = _public_target(item)
    return jsonable_encoder({
        "inventory_code": inventory_code,
        "target": canonical,
        "sold_search_url": build_sold_search_url(canonical),
        "research_method": "SIGNED_IN_EBAY_PRODUCT_RESEARCH_HUMAN_REVIEW",
        "automated_evidence_available": False,
        "can_change_market_value": False,
        "can_change_store_price": False,
        "can_change_shopify": False,
    })


@router.post("/inventory/{inventory_code}/preview")
async def preview_ebay_research(
    inventory_code: str,
    body: ResearchPreviewBody,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    _validate_review_rows(body.sales)
    item = await _owned_target(
        request.app.state.db_pool, user.user_id, request.state.request_id, inventory_code
    )
    result = preview_product_research(_public_target(item), body.sales)
    return jsonable_encoder({
        "inventory_code": inventory_code,
        **result,
        "evidence_is_verified_for_market_value": False,
        "existing_pricing_engine_not_invoked_for_publication": True,
    })
