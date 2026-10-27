from __future__ import annotations

import logging
import re
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator

from .automation_dispatcher import verify_signed_body
from .settings import get_settings


router = APIRouter(prefix="/api/v1/automation/control", tags=["automation-control"])
MAX_AUTOMATION_CONTROL_BODY_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class AutomationHeartbeat(BaseModel):
    heartbeat_key: Literal["n8n-runtime"] = "n8n-runtime"
    workflow_version: str = Field(default="v1", min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=255)
    occurred_at: AwareDatetime


class AutomationExecutionReceipt(BaseModel):
    workflow_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$")
    workflow_version: str = Field(default="unknown", min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=255)
    status: Literal["SUCCEEDED", "FAILED"]
    idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: AwareDatetime
    owner_id: UUID | None = None
    event_id: UUID | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def validate_failure(self) -> "AutomationExecutionReceipt":
        if self.status == "FAILED" and not (
            str(self.error_code or "").strip() or str(self.error_message or "").strip()
        ):
            raise ValueError("FAILED automation receipt requires error context")
        return self


def _control_database_error(
    operation: Literal["heartbeat", "receipt"], exc: asyncpg.PostgresError
) -> HTTPException:
    # Database messages/details can contain submitted data. Retain only a fixed
    # operation and SQLSTATE so failures are diagnosable without logging bodies.
    sqlstate = str(exc.sqlstate or "")
    if not re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        sqlstate = "UNKNOWN"
    logger.warning(
        "Automation control database failure operation=%s sqlstate=%s",
        operation,
        sqlstate,
    )
    if sqlstate == "22023":
        return HTTPException(status_code=422, detail=f"Invalid automation {operation}")
    return HTTPException(status_code=503, detail="Automation control storage is unavailable")


async def _verified_control_body(
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
            detail="Automation control authentication is not configured",
        )

    raw_body = await request.body()
    if not raw_body or len(raw_body) > MAX_AUTOMATION_CONTROL_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Invalid automation control body")
    if not verify_signed_body(
        secret=secret,
        body=raw_body,
        timestamp_header=timestamp_header,
        signature_header=signature_header,
    ):
        raise HTTPException(status_code=401, detail="Invalid automation control signature")
    return raw_body


@router.post("/heartbeat")
async def record_automation_heartbeat(
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
    raw_body = await _verified_control_body(
        request,
        timestamp_header=x_drop_rate_timestamp,
        signature_header=x_drop_rate_signature,
    )
    try:
        heartbeat = AutomationHeartbeat.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid automation heartbeat") from exc

    try:
        async with request.app.state.db_pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from tcg.record_automation_heartbeat($1,$2,$3,$4)
                """,
                heartbeat.heartbeat_key,
                heartbeat.workflow_version,
                heartbeat.execution_id,
                heartbeat.occurred_at,
            )
    except asyncpg.PostgresError as exc:
        raise _control_database_error("heartbeat", exc) from exc
    if row is None:
        raise HTTPException(status_code=503, detail="Automation heartbeat was not recorded")

    return {
        "accepted": True,
        "heartbeat_key": row["heartbeat_key"],
        "received_at": row["received_at"],
        "beat_count": int(row["beat_count"]),
        "duplicate": bool(row["duplicate"]),
    }


@router.post("/receipt")
async def record_automation_receipt(
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
    raw_body = await _verified_control_body(
        request,
        timestamp_header=x_drop_rate_timestamp,
        signature_header=x_drop_rate_signature,
    )

    try:
        receipt = AutomationExecutionReceipt.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid automation execution receipt") from exc

    # The private database capability resolves recipients and writes the receipt
    # and fixed failure alerts atomically. This signed system path must not set
    # tcg.user_id or read owner rows through an impersonated application user.
    try:
        async with request.app.state.db_pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select * from tcg_private.record_automation_execution_receipt(
                  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10
                )
                """,
                receipt.workflow_key,
                receipt.workflow_version,
                receipt.execution_id,
                receipt.status,
                receipt.idempotency_key,
                receipt.occurred_at,
                receipt.owner_id,
                receipt.event_id,
                receipt.error_code,
                receipt.error_message,
            )
    except asyncpg.PostgresError as exc:
        raise _control_database_error("receipt", exc) from exc
    if row is None:
        raise HTTPException(status_code=503, detail="Automation receipt was not recorded")

    return {
        "accepted": True,
        "workflow_key": receipt.workflow_key,
        "execution_id": receipt.execution_id,
        "status": receipt.status,
        "owner_receipts_inserted": int(row["owner_receipts_inserted"]),
        "duplicate_owner_receipts": int(row["duplicate_owner_receipts"]),
        "action_required_ids": [str(value) for value in row["action_required_ids"]],
    }
