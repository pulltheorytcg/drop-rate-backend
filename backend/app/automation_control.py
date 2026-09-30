from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, model_validator

from .action_required import upsert_action_required
from .automation_dispatcher import verify_signed_body
from .settings import get_settings


router = APIRouter(prefix="/api/v1/automation/control", tags=["automation-control"])
MAX_AUTOMATION_CONTROL_BODY_BYTES = 64 * 1024


class AutomationHeartbeat(BaseModel):
    heartbeat_key: Literal["n8n-runtime"] = "n8n-runtime"
    workflow_version: str = Field(default="v1", min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime


class AutomationExecutionReceipt(BaseModel):
    workflow_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$")
    workflow_version: str = Field(default="unknown", min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=255)
    status: Literal["SUCCEEDED", "FAILED"]
    idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
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


def _workflow_entity_id(workflow_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"drop-rate:n8n-workflow:{workflow_key}")


async def _receipt_owner_ids(connection, owner_id: UUID | None) -> list[UUID]:
    if owner_id is not None:
        exists = await connection.fetchval(
            """
            select exists(
              select 1
              from tcg.owners
              where id=$1 and active
            )
            """,
            owner_id,
        )
        if not exists:
            raise HTTPException(status_code=422, detail="Automation receipt owner is not active")
        return [owner_id]

    rows = await connection.fetch(
        """
        select id
        from tcg.owners
        where active
          and owner_type='FOUNDER'
        order by created_at,id
        """
    )
    owner_ids = [row["id"] for row in rows]
    if not owner_ids:
        raise HTTPException(status_code=503, detail="No active founder owners available")
    return owner_ids


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

    result_payload = {
        "workflow_key": receipt.workflow_key,
        "workflow_version": receipt.workflow_version,
        "execution_id": receipt.execution_id,
        "status": receipt.status,
        "idempotency_key": receipt.idempotency_key,
        "event_id": str(receipt.event_id) if receipt.event_id else None,
        "error_code": receipt.error_code,
        "error_message": receipt.error_message,
        "occurred_at": receipt.occurred_at.isoformat(),
    }

    inserted = 0
    duplicates = 0
    action_required_ids: list[str] = []

    async with request.app.state.db_pool.acquire() as connection:
        owner_ids = await _receipt_owner_ids(connection, receipt.owner_id)
        async with connection.transaction():
            for owner_id in owner_ids:
                row = await connection.fetchrow(
                    """
                    insert into tcg.automation_runs(
                      owner_id,job_type,run_key,initiated_by,result
                    ) values(
                      $1,$2,$3,'N8N',$4::jsonb
                    )
                    on conflict(owner_id,job_type,run_key) do nothing
                    returning id
                    """,
                    owner_id,
                    f"N8N:{receipt.workflow_key}",
                    receipt.idempotency_key,
                    json.dumps(result_payload, sort_keys=True, separators=(",", ":")),
                )
                if row is None:
                    duplicates += 1
                else:
                    inserted += 1

                if receipt.status == "FAILED" and row is not None:
                    error_code = str(receipt.error_code or "N8N_WORKFLOW_FAILED").strip()
                    error_message = str(receipt.error_message or "Workflow execution failed").strip()
                    action = await upsert_action_required(
                        connection,
                        owner_id=owner_id,
                        category="AUTOMATION",
                        code="N8N_WORKFLOW_FAILED",
                        severity="HIGH",
                        entity_type="N8N_WORKFLOW",
                        entity_id=_workflow_entity_id(receipt.workflow_key),
                        dedupe_key=f"n8n-workflow-failed:{receipt.workflow_key}",
                        title=f"Automation workflow failed: {receipt.workflow_key}",
                        detail=f"{error_code}: {error_message}"[:2000],
                        recommended_action=(
                            "Review the n8n execution and backend/provider health. "
                            "Replay only after the underlying cause is understood."
                        ),
                        metadata={
                            **result_payload,
                            "source": "n8n-control-plane",
                        },
                    )
                    action_required_ids.append(str(action["id"]))

    return {
        "accepted": True,
        "workflow_key": receipt.workflow_key,
        "execution_id": receipt.execution_id,
        "status": receipt.status,
        "owner_receipts_inserted": inserted,
        "duplicate_owner_receipts": duplicates,
        "action_required_ids": action_required_ids,
    }
