"""Authenticated, disabled-by-default UK Auction Lens proof on authorised footage.

This is NOT a live Whatnot/eBay capture adapter. It performs a single local
image-decode and bounded cached visual-index lookup per stable scene. It cannot
publish inventory, refresh prices, bid, retain frames or contact providers.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .auction_lens_pilot import (
    ObservedCard, MAX_CANDIDATES, confirm_exact_printing,
)
from .db import user_connection
from .inventory_reference_values import (
    REFERENCE_VALUES_SQL, MAX_AGE, SALE_AGE, SOLD, resolve_reference_value,
)
from .ownership import current_owner
from .recognition_images import RecognitionImageError, decode_image_data_url
from .recognition_reference_index import discover_reference_candidate_hints
from .settings import get_settings


router = APIRouter(prefix="/api/v1/auction-lens", tags=["auction-lens"])
_LOOKUP_LIMIT = asyncio.Semaphore(3)
_LOOKUP_TIMEOUT_SECONDS = 2.5


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


class PilotObservedCard(BaseModel):
    game: Literal["Pokemon"]
    language: Literal["English"]
    name: str = Field(min_length=1, max_length=120)
    set_name: str = Field(min_length=1, max_length=120)
    card_number: str = Field(min_length=1, max_length=45)
    finish: Literal["Normal", "Holofoil", "Reverse Holofoil"]
    object_type: Literal["RAW_CARD"] = "RAW_CARD"


class PilotResolveRequest(BaseModel):
    generation: int = Field(ge=0, le=2_147_483_647)
    image_data_url: str = Field(min_length=100, max_length=1_300_000)
    observed: PilotObservedCard
    source: Literal["OWN_VIDEO", "EXPLICITLY_AUTHORISED_VIDEO"]
    # An AI/vision condition estimate must NEVER be treated as user confirmation.
    confirmed_raw_condition: Literal["Near Mint"] | None = None


async def _eligible_uk_value(connection, *, catalogue_id: UUID, now: datetime) -> dict | None:
    """Use the existing exact-copy UK sold resolver, never a guide or asking quote.

    This is reached ONLY with an independently verified display-rights switch,
    explicit condition and current approved exact-print visual match.
    """
    snapshots = [dict(item) for item in await connection.fetch(
        REFERENCE_VALUES_SQL, [catalogue_id], now
    )]
    price = resolve_reference_value(
        {
            "product_type": "CARD",
            "catalogue_id": catalogue_id,
            "language": "English",
            "catalogue_language": "English",
            "condition": "Near Mint",
            "grading_company": None,
            "grade": None,
            "seal_status": None,
        },
        snapshots,
        now=now,
    )
    if (price.get("status") != "AVAILABLE"
            or price.get("method") != SOLD
            or type(price.get("market_value_minor")) is not int
            or price["market_value_minor"] <= 0
            or not isinstance(price.get("checked_at"), datetime)):
        return None
    # Sold observation expiry may precede the last-refresh seven-day window.
    # The client must stop displaying the value at the FIRST expiring gate.
    source_snapshot = next(
        (row for row in snapshots if str(row.get("snapshot_id")) == str(price.get("snapshot_id"))),
        None,
    )
    if not source_snapshot:
        return None
    oldest = source_snapshot.get("oldest_sale_at")
    if not isinstance(oldest, datetime) or oldest.tzinfo is None:
        return None
    expires = min(price["checked_at"] + MAX_AGE, oldest + SALE_AGE)
    if expires <= now:
        return None
    return {
        "marketValueMinor": price["market_value_minor"],
        "currency": "GBP",
        "source": "Drop Rate · eligible UK sold Market Value",
        "basis": "English · Near Mint · raw",
        "evidenceAtMs": int(price["checked_at"].timestamp() * 1000),
        "expiresAtMs": int(expires.timestamp() * 1000),
        "valuationEligible": True,
    }


@router.post("/pilot/resolve")
async def resolve_authorised_auction_frame(
    payload: PilotResolveRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Resolve one stable cropped frame with strict abstention and no write path.

    Unavailable by default in every environment, including production.
    Temporary pilot access must be deliberately enabled for authorised video,
    independently of (also default-off) licensed sold-value display.
    """
    if not _enabled("TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED"):
        raise HTTPException(status_code=404, detail="Auction Lens pilot is not active")
    # Source selection is the operator's declaration, NOT a platform licence.
    # This endpoint must never be used on unapproved third-party live streams.
    try:
        image = decode_image_data_url(
            payload.image_data_url,
            max_bytes=min(900_000, get_settings().recognition_max_image_bytes),
        )
    except RecognitionImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    response = {"generation": payload.generation, "decision": "CHECK_VERSION"}
    try:
        await asyncio.wait_for(_LOOKUP_LIMIT.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(status_code=429, detail="Auction recognition is busy") from None
    try:
        async with asyncio.timeout(_LOOKUP_TIMEOUT_SECONDS):
            async with user_connection(
                request.app.state.db_pool,
                user.user_id,
                request.state.request_id,
                readonly_snapshot=True,
            ) as connection:
                await current_owner(connection)
                hints = await discover_reference_candidate_hints(
                    connection, image.hashes, system_code="POKEMON_TCG",
                    max_rows=2048, min_similarity=0.60,
                    max_candidates=MAX_CANDIDATES,
                )
                if not hints:
                    return response
                catalogue_ids = list({h["catalogue_id"] for h in hints})
                media_ids = list({h["media_asset_id"] for h in hints})
                rows = [dict(row) for row in await connection.fetch(
                    """
                    select p.id as catalogue_id,p.product_type,p.game,p.name,
                           p.set_name,p.card_number,p.variant,p.language,
                           ma.id as media_asset_id,ma.approval_status,
                           ma.source_status,ma.rights_status
                    from tcg.catalogue_products p
                    join tcg.media_assets ma on ma.catalogue_id=p.id
                    where p.id=any($1::uuid[]) and ma.id=any($2::uuid[])
                      and p.product_type='CARD'
                    """,
                    catalogue_ids, media_ids,
                )]
                exact = confirm_exact_printing(
                    hints, rows, ObservedCard(**payload.observed.model_dump())
                )
                if exact is None:
                    return response
                response = {
                    "generation": payload.generation,
                    "decision": "EXACT",
                    "identityKey": exact["identityKey"],
                    "title": exact["title"],
                }
                if (
                    payload.confirmed_raw_condition == "Near Mint"
                    and _enabled("TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED")
                ):
                    value = await _eligible_uk_value(
                        connection, catalogue_id=UUID(exact["catalogue_id"]),
                        now=datetime.now(timezone.utc)
                    )
                    if value:
                        response["value"] = value
                return response
    except TimeoutError:
        # Fail closed instead of holding the UI on a slow DB/index read.
        return {"generation": payload.generation, "decision": "CHECK_VERSION"}
    finally:
        _LOOKUP_LIMIT.release()
