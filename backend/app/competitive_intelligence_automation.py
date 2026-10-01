from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .automation_dispatcher import verify_signed_body
from .settings import get_settings


router = APIRouter(
    prefix="/api/v1/automation/competitive-intelligence",
    tags=["competitive-intelligence-automation"],
)

MAX_COMPETITIVE_SHADOW_BODY_BYTES = 128 * 1024

ObservationType = Literal[
    "PRODUCT_LAUNCH",
    "PRICE",
    "PROMOTION",
    "STOCK",
    "MERCHANDISING",
    "CRO",
    "SEO",
    "CONTENT",
    "SOCIAL",
    "CHANNEL",
    "REVIEW",
    "CUSTOMER_PAIN",
    "OTHER",
]


def _normalize_metric(value: float) -> float:
    return round(float(value), 5)


class ShadowObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    dedupe_key: str = Field(min_length=1, max_length=255)
    observation_type: ObservationType
    subject: str = Field(min_length=1, max_length=500)
    facts: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    observed_at: datetime
    source_published_at: datetime | None = None

    @field_validator("dedupe_key", "subject")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be blank")
        return cleaned

    @field_validator("confidence", "relevance")
    @classmethod
    def normalize_metrics(cls, value: float) -> float:
        return _normalize_metric(value)

    @field_validator("observed_at", "source_published_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Automation timestamps must include a timezone")
        return value


class ShadowObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_key: Literal["competitive-intelligence"]
    workflow_version: str = Field(min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=255)
    observations: list[ShadowObservation] = Field(min_length=1, max_length=50)

    @field_validator("workflow_version", "execution_id")
    @classmethod
    def clean_metadata(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def unique_dedupe_keys(self) -> "ShadowObservationBatch":
        keys = [item.dedupe_key for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("Batch contains duplicate observation dedupe keys")
        return self


async def _verified_shadow_body(
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
            detail="Automation authentication is not configured",
        )

    raw_body = await request.body()
    if not raw_body or len(raw_body) > MAX_COMPETITIVE_SHADOW_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Invalid competitive shadow body")

    if not verify_signed_body(
        secret=secret,
        body=raw_body,
        timestamp_header=timestamp_header,
        signature_header=signature_header,
    ):
        raise HTTPException(status_code=401, detail="Invalid automation signature")
    return raw_body


@router.post("/observations/shadow")
async def ingest_shadow_observations(
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
    raw_body = await _verified_shadow_body(
        request,
        timestamp_header=x_drop_rate_timestamp,
        signature_header=x_drop_rate_signature,
    )
    try:
        payload = ShadowObservationBatch.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid competitive shadow observation batch",
        ) from exc

    results: list[dict] = []
    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            for item in payload.observations:
                row = await connection.fetchrow(
                    """
                    select *
                    from tcg.ingest_competitive_observation_system(
                        $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,$13,$14
                    )
                    """,
                    request.state.request_id,
                    payload.workflow_key,
                    payload.workflow_version,
                    payload.execution_id,
                    item.source_id,
                    item.dedupe_key,
                    item.observation_type,
                    item.subject,
                    json.dumps(item.facts, sort_keys=True, separators=(",", ":")),
                    json.dumps(item.evidence, sort_keys=True, separators=(",", ":")),
                    item.confidence,
                    item.relevance,
                    item.observed_at,
                    item.source_published_at,
                )
                if row is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Competitive shadow observation was not recorded",
                    )
                results.append(
                    {
                        "observation_id": str(row["observation_id"]),
                        "duplicate": bool(row["duplicate"]),
                        "dedupe_key": item.dedupe_key,
                    }
                )

    inserted = sum(1 for item in results if not item["duplicate"])
    duplicates = len(results) - inserted
    return {
        "accepted": True,
        "mode": "SHADOW",
        "workflow_key": payload.workflow_key,
        "workflow_version": payload.workflow_version,
        "execution_id": payload.execution_id,
        "inserted_count": inserted,
        "duplicate_count": duplicates,
        "observations": results,
        "external_action_taken": False,
    }
