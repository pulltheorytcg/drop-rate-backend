"""Owner-bound sports card and figure intake through the shared copy engine."""
from __future__ import annotations

import json
from typing import Annotated, Literal

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ConfigDict, Field, model_validator

from .access_control import require_owner_portal_request, require_platform_admin_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .inventory_intake import create_inventory_intake
from .schemas import ManualCatalogueCreate, ManualInventoryCreate


router = APIRouter(tags=["owner-collectibles"])


class CollectibleCatalogueCreate(ManualCatalogueCreate):
    model_config = ConfigDict(extra="forbid")


class CollectibleIntakeRequest(ManualInventoryCreate):
    model_config = ConfigDict(extra="forbid")

    category: Literal["SPORTS", "FIGURES"]
    new_catalogue: CollectibleCatalogueCreate | None = None
    # Listing price belongs to the later sale flow, not collection admission.
    store_price_minor: None = None
    copy_serial_number: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_category(self):
        product = self.new_catalogue
        if product is not None:
            if self.category == "SPORTS" and (product.product_type != "CARD" or product.sports_card is None):
                raise ValueError("Complete the sports card's exact printing details")
            if self.category == "FIGURES" and (product.product_type != "FIGURE" or product.figure_details is None):
                raise ValueError("Complete the figure's exact edition details")
            if self.language and product.language and self.language.casefold() != product.language.casefold():
                raise ValueError("The copy and reference must use the same language")
        if self.category == "FIGURES" and (self.grading_company or self.grade or self.certificate_number):
            raise ValueError("Figures do not use card or comic grading fields")
        if self.category == "SPORTS" and self.grading_company and not self.certificate_number:
            raise ValueError("Enter the graded sports card's certificate number")
        self.copy_serial_number = self.copy_serial_number.strip() if self.copy_serial_number else None
        if self.copy_serial_number and len(self.notes) + len(self.copy_serial_number) + 16 > 2000:
            raise ValueError("Shorten the copy notes to include the serial number")
        return self


async def _add_collectible(payload, request, user, access, idempotency_key):
    if payload.catalogue_id is not None:
        system, kind = ("SPORTS_CARDS", "CARD") if payload.category == "SPORTS" else ("FIGURES", "FIGURE")
        async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as db:
            row = await db.fetchrow("""
                select p.product_type,p.language,cp.system_code,cp.identity_status,cp.attributes,
                       exists(select 1 from tcg.inventory_items i
                              where i.catalogue_id=p.id and i.owner_id=$2) as own_copy
                from tcg.catalogue_products p
                join tcg.catalogue_product_profiles cp on cp.catalogue_id=p.id
                where p.id=$1 and p.product_type=$3 and cp.system_code=$4
                """, payload.catalogue_id, access["owner_id"], kind, system)
        if row is None:
            raise HTTPException(404, "Matching collectible reference not found")
        attributes = row["attributes"]
        if isinstance(attributes, str):
            attributes = json.loads(attributes)
        if not isinstance(attributes, dict):
            attributes = {}
        if (row["identity_status"] == "NEEDS_REVIEW" and attributes.get("identity_source") == "SELLER_ENTERED"
                and not row["own_copy"] and access["access_role"] != "PLATFORM_ADMIN"):
            raise HTTPException(404, "Matching collectible reference not found")
        if payload.language and row["language"] and payload.language.casefold() != row["language"].casefold():
            raise HTTPException(422, "The copy and reference must use the same language")

    values = payload.model_dump(exclude={"category", "copy_serial_number"})
    if payload.copy_serial_number:
        # The serial belongs to one physical copy, never the shared edition key.
        values["notes"] = "\n".join(filter(None, (f"Serial number: {payload.copy_serial_number}", payload.notes)))
    intake = ManualInventoryCreate.model_validate(values)
    try:
        return await create_inventory_intake(intake, request, user, idempotency_key)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, "This certificate is already recorded. Check your collection or contact Drop Rate.") from exc


@router.post("/api/v1/owner/collectibles/intake", status_code=201)
async def add_owner_collectible(
    payload: CollectibleIntakeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
):
    return await _add_collectible(payload, request, user, access, idempotency_key)


@router.post("/api/v1/inventory/collectibles/intake", status_code=201)
async def add_founder_collectible(
    payload: CollectibleIntakeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_platform_admin_request)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
):
    return await _add_collectible(payload, request, user, access, idempotency_key)
