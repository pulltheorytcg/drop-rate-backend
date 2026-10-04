from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, model_validator

from .automation_dispatcher import verify_signed_body
from .settings import get_settings
from .shopify_pipeline import publish_inventory_to_shopify, reconcile_shopify_product_prices


router = APIRouter(prefix="/api/v1/automation/commands", tags=["automation-commands"])
MAX_AUTOMATION_COMMAND_BODY_BYTES = 64 * 1024


class AutomationAggregate(BaseModel):
    type: Literal["INVENTORY_ITEM"]
    id: UUID


class InventoryApprovedPayload(BaseModel):
    inventory_id: UUID
    inventory_code: str = Field(min_length=1, max_length=120)
    catalogue_id: UUID
    status: Literal["APPROVED"]
    version: int = Field(ge=1)


class ShopifyProductUpdatesCommand(BaseModel):
    schema_version: Literal[1] = 1
    execution_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    limit: int = Field(default=50, ge=1, le=100)


class InventoryApprovedEvent(BaseModel):
    event_id: UUID
    event_type: Literal["inventory.approved"]
    schema_version: Literal[1]
    aggregate: AutomationAggregate
    idempotency_key: str = Field(min_length=1, max_length=255)
    owner_id: UUID
    attempt: int = Field(ge=0)
    occurred_at: datetime
    payload: InventoryApprovedPayload

    @model_validator(mode="after")
    def validate_identity(self) -> "InventoryApprovedEvent":
        if self.aggregate.id != self.payload.inventory_id:
            raise ValueError("Aggregate ID must match payload inventory ID")
        expected_key = (
            f"inventory.approved:{self.payload.inventory_id}:v{self.payload.version}"
        )
        if self.idempotency_key != expected_key:
            raise ValueError("Inventory approval idempotency key is invalid")
        return self


async def _verified_command_body(
    request: Request,
    *,
    timestamp_header: str | None,
    signature_header: str | None,
) -> bytes:
    settings = get_settings()
    secret = str(settings.automation_command_secret or "").strip()
    if len(secret) < 32:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Automation command authentication is not configured",
                "retryable": True,
            },
        )

    raw_body = await request.body()
    if not raw_body or len(raw_body) > MAX_AUTOMATION_COMMAND_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Invalid automation command body")
    if not verify_signed_body(
        secret=secret,
        body=raw_body,
        timestamp_header=timestamp_header,
        signature_header=signature_header,
    ):
        raise HTTPException(status_code=401, detail="Invalid automation command signature")
    return raw_body


@router.post("/shopify/product-updates")
async def reconcile_shopify_product_updates(
    request: Request,
    x_drop_rate_timestamp: str | None = Header(
        default=None,
        alias="X-Drop-Rate-Timestamp",
    ),
    x_drop_rate_signature: str | None = Header(
        default=None,
        alias="X-Drop-Rate-Signature",
    ),
) -> dict:
    settings = get_settings()
    if not settings.shopify_publish_enabled:
        raise HTTPException(
            status_code=409,
            detail="Automated Shopify updates are locked off",
        )

    raw_body = await _verified_command_body(
        request,
        timestamp_header=x_drop_rate_timestamp,
        signature_header=x_drop_rate_signature,
    )
    try:
        command = ShopifyProductUpdatesCommand.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid Shopify product-updates automation command",
        ) from exc

    result = await reconcile_shopify_product_prices(
        request.app.state.db_pool,
        limit=command.limit,
        request_id=request.state.request_id,
    )
    if int(result.get("failed_count") or 0) > 0:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "One or more Shopify product price updates failed read-back",
                "retryable": True,
                "result": result,
            },
        )
    if int(result.get("retry_required_count") or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Drop Rate state changed during Shopify price reconciliation",
                "retryable": True,
                "result": result,
            },
        )
    return result


@router.post("/shopify/inventory-approved")
async def publish_inventory_approved_to_shopify(
    request: Request,
    x_drop_rate_timestamp: str | None = Header(
        default=None,
        alias="X-Drop-Rate-Timestamp",
    ),
    x_drop_rate_signature: str | None = Header(
        default=None,
        alias="X-Drop-Rate-Signature",
    ),
) -> dict:
    settings = get_settings()
    if not settings.shopify_publish_enabled:
        raise HTTPException(
            status_code=409,
            detail="Automated Shopify publishing is locked off",
        )

    raw_body = await _verified_command_body(
        request,
        timestamp_header=x_drop_rate_timestamp,
        signature_header=x_drop_rate_signature,
    )
    try:
        event = InventoryApprovedEvent.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid inventory.approved automation envelope",
        ) from exc

    async with request.app.state.db_pool.acquire() as connection:
        return await publish_inventory_to_shopify(
            connection,
            inventory_id=event.payload.inventory_id,
            owner_id=event.owner_id,
            expected_version=event.payload.version,
            actor_user_id=None,
            automation_event_id=event.event_id,
            request_id=request.state.request_id,
            test_mode=False,
        )


# The marketing router reuses the raw-body HMAC verifier above. Its feature gate
# defaults off and its v1 publishing worker is hard-blocked independently.
from .marketing_specialist_api import router as marketing_specialist_router

router.include_router(marketing_specialist_router)

# An independent, exactly approved manual image pilot. It neither enables the
# preparation agents nor grants arbitrary publishing authority.
from .social_pilot import router as approved_social_pilot_router

router.include_router(approved_social_pilot_router)
