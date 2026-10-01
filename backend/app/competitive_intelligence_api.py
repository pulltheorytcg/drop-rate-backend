from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import AuthenticatedUser, require_user
from .competitive_intelligence import (
    ALLOWED_COLLECTION_METHODS,
    ALLOWED_RIGHTS_STATUSES,
    CompetitiveEvidence,
    evaluate_competitive_opportunity,
    source_preflight,
)
from .db import user_connection


router = APIRouter(
    prefix="/api/v1/competitive-intelligence",
    tags=["competitive-intelligence"],
)


CompetitorTier = Literal["MARKET_LEADER", "DIRECT", "EMERGING"]
CompetitorStatus = Literal["APPROVED", "PAUSED", "REJECTED"]
SourceType = Literal[
    "WEBSITE", "SOCIAL", "NEWSLETTER", "REVIEWS", "MARKETPLACE", "SEARCH", "OTHER"
]
SourceStatus = Literal["PENDING", "ACTIVE", "PAUSED", "BLOCKED"]
ObservationType = Literal[
    "PRODUCT_LAUNCH", "PRICE", "PROMOTION", "STOCK", "MERCHANDISING",
    "CRO", "SEO", "CONTENT", "SOCIAL", "CHANNEL", "REVIEW",
    "CUSTOMER_PAIN", "OTHER",
]
OpportunityType = Literal[
    "CONTENT", "CRO", "SEO", "MERCHANDISING", "ACQUISITION", "CHANNEL"
]
EvidenceOrigin = Literal["COMPETITOR", "INTERNAL", "MARKET", "SOCIAL", "OFFICIAL"]


def _clean_https(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not cleaned.startswith("https://"):
        raise ValueError(f"{field_name} must use https://")
    return cleaned


class CompetitorCreate(BaseModel):
    competitor_key: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9-]+$",
    )
    name: str = Field(min_length=1, max_length=200)
    tier: CompetitorTier
    website_url: str | None = Field(default=None, max_length=2000)
    status: CompetitorStatus = "APPROVED"
    notes: str = Field(default="", max_length=2000)

    @field_validator("name", "notes")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, value: str | None) -> str | None:
        return _clean_https(value, field_name="website_url")


class SourceCreate(BaseModel):
    source_key: str = Field(
        min_length=2,
        max_length=255,
        pattern=r"^[a-z0-9][a-z0-9._:/-]+$",
    )
    source_type: SourceType
    collection_method: str
    source_url: str | None = Field(default=None, max_length=2000)
    rights_status: str = "REFERENCE_ONLY"
    terms_reviewed: bool = False
    terms_review_notes: str = Field(default="", max_length=2000)
    status: SourceStatus = "PENDING"
    poll_interval_minutes: int | None = Field(default=None, ge=60, le=10080)
    rate_limit_notes: str = Field(default="", max_length=2000)

    @field_validator("collection_method")
    @classmethod
    def validate_collection_method(cls, value: str) -> str:
        method = value.strip().upper()
        if method not in ALLOWED_COLLECTION_METHODS:
            raise ValueError("Unsupported collection method")
        return method

    @field_validator("rights_status")
    @classmethod
    def validate_rights_status(cls, value: str) -> str:
        rights = value.strip().upper()
        if rights not in ALLOWED_RIGHTS_STATUSES:
            raise ValueError("Unsupported rights status")
        return rights

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _clean_https(value, field_name="source_url")

    @field_validator("terms_review_notes", "rate_limit_notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_activation(self) -> "SourceCreate":
        if self.status == "ACTIVE":
            result = source_preflight(
                collection_method=self.collection_method,
                rights_status=self.rights_status,
                terms_reviewed=self.terms_reviewed,
                bypasses_access_control=False,
            )
            if not result.allowed:
                raise ValueError(
                    "ACTIVE source failed preflight: " + ",".join(result.failures)
                )
        return self


class SourceStateUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal["ACTIVE", "PAUSED", "BLOCKED"]


class SourceReviewUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["APPROVE", "BLOCK"]
    notes: str = Field(default="", max_length=2000)
    activate: bool = False

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()


class CompetitorStateUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: CompetitorStatus


class ObservationCreate(BaseModel):
    source_id: UUID
    dedupe_key: str = Field(min_length=1, max_length=255)
    observation_type: ObservationType
    subject: str = Field(min_length=1, max_length=500)
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
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


class OpportunityEvidenceInput(BaseModel):
    origin: EvidenceOrigin
    source_key: str | None = Field(default=None, max_length=255)
    competitor_observation_id: UUID | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    rights_status: str = "REFERENCE_ONLY"
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rights_status")
    @classmethod
    def validate_rights_status(cls, value: str) -> str:
        rights = value.strip().upper()
        if rights not in ALLOWED_RIGHTS_STATUSES:
            raise ValueError("Unsupported rights status")
        return rights

    @field_validator("source_key")
    @classmethod
    def clean_source_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_origin_contract(self) -> "OpportunityEvidenceInput":
        if self.origin == "COMPETITOR":
            if self.competitor_observation_id is None:
                raise ValueError("COMPETITOR evidence requires competitor_observation_id")
            if self.source_key is not None:
                raise ValueError("COMPETITOR source_key is derived from stored observation")
        else:
            if not self.source_key:
                raise ValueError("Non-competitor evidence requires source_key")
            if self.competitor_observation_id is not None:
                raise ValueError("Non-competitor evidence cannot reference competitor observation")
            if self.confidence is None or self.relevance is None:
                raise ValueError("Non-competitor evidence requires confidence and relevance")
        return self


class OpportunityEvaluateRequest(BaseModel):
    opportunity_key: str = Field(min_length=2, max_length=255)
    opportunity_type: OpportunityType
    subject: str = Field(min_length=1, max_length=500)
    hypothesis: str = Field(min_length=1, max_length=3000)
    evidence: list[OpportunityEvidenceInput] = Field(min_length=1, max_length=50)
    qualification_threshold: float = Field(default=0.72, ge=0.0, le=1.0)

    @field_validator("opportunity_key", "subject", "hypothesis")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be blank")
        return cleaned


async def _fetch_competitor(connection: asyncpg.Connection, competitor_id: UUID):
    row = await connection.fetchrow(
        "select * from tcg.competitors where id=$1",
        competitor_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return row


async def _fetch_source(connection: asyncpg.Connection, source_id: UUID):
    row = await connection.fetchrow(
        """
        select s.*,c.competitor_key,c.name as competitor_name,c.status as competitor_status
        from tcg.competitor_sources s
        join tcg.competitors c on c.id=s.competitor_id
        where s.id=$1
        """,
        source_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Competitive source not found")
    return row


@router.get("/competitors")
async def list_competitors(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    status: CompetitorStatus | None = Query(default=None),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select c.*,
                   count(s.id)::integer as source_count,
                   count(s.id) filter (where s.status='ACTIVE')::integer as active_source_count
            from tcg.competitors c
            left join tcg.competitor_sources s on s.competitor_id=c.id
            where ($1::text is null or c.status=$1)
            group by c.id
            order by c.tier,c.name,c.id
            """,
            status,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/competitors", status_code=201)
async def create_competitor(
    payload: CompetitorCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        try:
            row = await connection.fetchrow(
                """
                insert into tcg.competitors(
                    competitor_key,name,tier,website_url,status,notes,created_by_user_id
                ) values($1,$2,$3,$4,$5,$6,$7)
                returning *
                """,
                payload.competitor_key,
                payload.name,
                payload.tier,
                payload.website_url,
                payload.status,
                payload.notes,
                user.user_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409,
                detail="Competitor key already exists",
            ) from exc
        return jsonable_encoder(dict(row))


@router.patch("/competitors/{competitor_id}/status")
async def update_competitor_status(
    competitor_id: UUID,
    payload: CompetitorStateUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        current = await _fetch_competitor(connection, competitor_id)
        if current["version"] != payload.expected_version:
            raise HTTPException(status_code=409, detail="Competitor version conflict")

        row = await connection.fetchrow(
            """
            update tcg.competitors
            set status=$2,
                version=version+1,
                updated_at=clock_timestamp()
            where id=$1 and version=$3
            returning *
            """,
            competitor_id,
            payload.status,
            payload.expected_version,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Competitor changed during update")
        return jsonable_encoder(dict(row))


@router.post("/competitors/{competitor_id}/sources", status_code=201)
async def create_competitor_source(
    competitor_id: UUID,
    payload: SourceCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        competitor = await _fetch_competitor(connection, competitor_id)
        if competitor["status"] != "APPROVED":
            raise HTTPException(
                status_code=409,
                detail="Sources can only be added to an approved competitor",
            )

        if payload.collection_method == "MANUAL_REVIEW":
            terms_status = "NOT_REQUIRED"
            terms_reviewed_at = None
            terms_reviewed_by = None
        elif payload.terms_reviewed:
            terms_status = "REVIEWED"
            terms_reviewed_at = datetime.now(timezone.utc)
            terms_reviewed_by = user.user_id
        else:
            terms_status = "PENDING"
            terms_reviewed_at = None
            terms_reviewed_by = None

        try:
            row = await connection.fetchrow(
                """
                insert into tcg.competitor_sources(
                    competitor_id,source_key,source_type,collection_method,
                    source_url,rights_status,terms_review_status,
                    terms_reviewed_at,terms_reviewed_by_user_id,
                    terms_review_notes,status,poll_interval_minutes,
                    rate_limit_notes,created_by_user_id
                ) values(
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
                )
                returning *
                """,
                competitor_id,
                payload.source_key,
                payload.source_type,
                payload.collection_method,
                payload.source_url,
                payload.rights_status,
                terms_status,
                terms_reviewed_at,
                terms_reviewed_by,
                payload.terms_review_notes,
                payload.status,
                payload.poll_interval_minutes,
                payload.rate_limit_notes,
                user.user_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409,
                detail="Competitive source key already exists",
            ) from exc
        return jsonable_encoder(dict(row))


@router.get("/sources")
async def list_competitor_sources(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    competitor_id: UUID | None = Query(default=None),
    status: SourceStatus | None = Query(default=None),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select s.*,c.competitor_key,c.name as competitor_name,c.tier
            from tcg.competitor_sources s
            join tcg.competitors c on c.id=s.competitor_id
            where ($1::uuid is null or s.competitor_id=$1)
              and ($2::text is null or s.status=$2)
            order by c.name,s.source_type,s.source_key
            """,
            competitor_id,
            status,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/sources/{source_id}/review")
async def review_competitor_source(
    source_id: UUID,
    payload: SourceReviewUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        current = await _fetch_source(connection, source_id)
        if current["version"] != payload.expected_version:
            raise HTTPException(status_code=409, detail="Competitive source version conflict")

        if payload.decision == "BLOCK":
            terms_status = "BLOCKED"
            source_status = "BLOCKED"
        else:
            result = source_preflight(
                collection_method=current["collection_method"],
                rights_status=current["rights_status"],
                terms_reviewed=True,
                bypasses_access_control=False,
            )
            if not result.allowed:
                raise HTTPException(
                    status_code=409,
                    detail="Competitive source failed review preflight",
                )
            terms_status = (
                "NOT_REQUIRED"
                if current["collection_method"] == "MANUAL_REVIEW"
                else "REVIEWED"
            )
            source_status = "ACTIVE" if payload.activate else "PAUSED"

        row = await connection.fetchrow(
            """
            update tcg.competitor_sources
            set terms_review_status=$2,
                terms_reviewed_at=clock_timestamp(),
                terms_reviewed_by_user_id=$3,
                terms_review_notes=$4,
                status=$5,
                version=version+1,
                updated_at=clock_timestamp()
            where id=$1 and version=$6
            returning *
            """,
            source_id,
            terms_status,
            user.user_id,
            payload.notes,
            source_status,
            payload.expected_version,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Competitive source changed during review")
        return jsonable_encoder(dict(row))


@router.patch("/sources/{source_id}/status")
async def update_source_status(
    source_id: UUID,
    payload: SourceStateUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        current = await _fetch_source(connection, source_id)
        if current["version"] != payload.expected_version:
            raise HTTPException(status_code=409, detail="Competitive source version conflict")

        if payload.status == "ACTIVE":
            if current["competitor_status"] != "APPROVED":
                raise HTTPException(
                    status_code=409,
                    detail="Competitor must be approved before source activation",
                )
            result = source_preflight(
                collection_method=current["collection_method"],
                rights_status=current["rights_status"],
                terms_reviewed=current["terms_review_status"] in {"REVIEWED","NOT_REQUIRED"},
                bypasses_access_control=False,
            )
            if not result.allowed:
                raise HTTPException(
                    status_code=409,
                    detail="Competitive source failed activation preflight",
                )

        row = await connection.fetchrow(
            """
            update tcg.competitor_sources
            set status=$2,
                version=version+1,
                updated_at=clock_timestamp()
            where id=$1 and version=$3
            returning *
            """,
            source_id,
            payload.status,
            payload.expected_version,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Competitive source changed during update")
        return jsonable_encoder(dict(row))


@router.post("/observations", status_code=201)
async def record_competitive_observation(
    payload: ObservationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        source = await _fetch_source(connection, payload.source_id)
        if source["status"] != "ACTIVE":
            raise HTTPException(status_code=409, detail="Competitive source is not active")
        if source["competitor_status"] != "APPROVED":
            raise HTTPException(status_code=409, detail="Competitor is not approved")

        existing = await connection.fetchrow(
            "select * from tcg.competitive_observations where dedupe_key=$1",
            payload.dedupe_key,
        )
        if existing is not None:
            same_contract = (
                existing["source_id"] == payload.source_id
                and existing["observation_type"] == payload.observation_type
                and existing["subject"] == payload.subject
                and existing["observed_at"] == payload.observed_at
                and existing["source_published_at"] == payload.source_published_at
                and existing["facts"] == payload.facts
                and existing["evidence"] == payload.evidence
                and float(existing["confidence"]) == payload.confidence
                and float(existing["relevance"]) == payload.relevance
            )
            if not same_contract:
                raise HTTPException(
                    status_code=409,
                    detail="Observation dedupe key already exists with different content",
                )
            return jsonable_encoder({"duplicate": True, "observation": dict(existing)})

        row = await connection.fetchrow(
            """
            insert into tcg.competitive_observations(
                competitor_id,source_id,dedupe_key,observation_type,subject,
                source_url,facts,evidence,confidence,relevance,rights_status,
                observed_at,source_published_at,actor_type,created_by_user_id
            ) values(
                $1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,'HUMAN',$14
            )
            returning *
            """,
            source["competitor_id"],
            payload.source_id,
            payload.dedupe_key,
            payload.observation_type,
            payload.subject,
            source["source_url"],
            json.dumps(payload.facts, sort_keys=True, separators=(",", ":")),
            json.dumps(payload.evidence, sort_keys=True, separators=(",", ":")),
            payload.confidence,
            payload.relevance,
            source["rights_status"],
            payload.observed_at,
            payload.source_published_at,
            user.user_id,
        )
        return jsonable_encoder({"duplicate": False, "observation": dict(row)})


@router.get("/observations")
async def list_competitive_observations(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    competitor_id: UUID | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    observation_type: ObservationType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select o.*,c.competitor_key,c.name as competitor_name,s.source_key,s.source_type
            from tcg.competitive_observations o
            join tcg.competitors c on c.id=o.competitor_id
            join tcg.competitor_sources s on s.id=o.source_id
            where ($1::uuid is null or o.competitor_id=$1)
              and ($2::uuid is null or o.source_id=$2)
              and ($3::text is null or o.observation_type=$3)
            order by o.observed_at desc,o.id
            limit $4
            """,
            competitor_id,
            source_id,
            observation_type,
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/opportunities/evaluate", status_code=201)
async def evaluate_and_store_opportunity(
    payload: OpportunityEvaluateRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        existing = await connection.fetchrow(
            "select * from tcg.competitive_opportunities where opportunity_key=$1",
            payload.opportunity_key,
        )

        competitor_ids = [
            item.competitor_observation_id
            for item in payload.evidence
            if item.origin == "COMPETITOR"
        ]
        observation_rows = {}
        if competitor_ids:
            rows = await connection.fetch(
                """
                select
                    o.id,o.observation_type,o.confidence,o.relevance,o.rights_status,
                    s.source_key,s.status as source_status,
                    c.competitor_key,c.status as competitor_status
                from tcg.competitive_observations o
                join tcg.competitor_sources s on s.id=o.source_id
                join tcg.competitors c on c.id=o.competitor_id
                where o.id=any($1::uuid[])
                """,
                competitor_ids,
            )
            observation_rows = {row["id"]: row for row in rows}
            if len(observation_rows) != len(set(competitor_ids)):
                raise HTTPException(
                    status_code=404,
                    detail="One or more competitor observations were not found",
                )
            if any(
                row["source_status"] == "BLOCKED"
                or row["competitor_status"] == "REJECTED"
                for row in observation_rows.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Blocked or rejected competitive evidence cannot qualify a new opportunity",
                )

        signals: list[CompetitiveEvidence] = []
        evidence_records: list[dict[str, Any]] = []
        for item in payload.evidence:
            if item.origin == "COMPETITOR":
                stored = observation_rows[item.competitor_observation_id]
                signal = CompetitiveEvidence(
                    origin="COMPETITOR",
                    source_key=stored["source_key"],
                    confidence=float(stored["confidence"]),
                    relevance=float(stored["relevance"]),
                    rights_status=stored["rights_status"],
                    competitor_key=stored["competitor_key"],
                    observation_type=stored["observation_type"],
                )
                evidence_record = {
                    "origin": "COMPETITOR",
                    "source_key": stored["source_key"],
                    "competitor_observation_id": item.competitor_observation_id,
                    "confidence": float(stored["confidence"]),
                    "relevance": float(stored["relevance"]),
                    "rights_status": stored["rights_status"],
                    "evidence": item.evidence,
                }
            else:
                signal = CompetitiveEvidence(
                    origin=item.origin,
                    source_key=item.source_key,
                    confidence=float(item.confidence),
                    relevance=float(item.relevance),
                    rights_status=item.rights_status,
                )
                evidence_record = {
                    "origin": item.origin,
                    "source_key": item.source_key,
                    "competitor_observation_id": None,
                    "confidence": float(item.confidence),
                    "relevance": float(item.relevance),
                    "rights_status": item.rights_status,
                    "evidence": item.evidence,
                }
            signals.append(signal)
            evidence_records.append(evidence_record)

        decision = evaluate_competitive_opportunity(
            signals,
            qualification_threshold=payload.qualification_threshold,
        )

        # Persist the same independent-source semantics used by the evaluator.
        # Multiple observations from one source remain useful context, but cannot
        # manufacture additional corroboration or violate the evidence unique key.
        best_evidence_by_source: dict[str, dict[str, Any]] = {}
        for item in evidence_records:
            source_key = str(item["source_key"])
            strength = (float(item["confidence"]) * 0.6) + (float(item["relevance"]) * 0.4)
            previous = best_evidence_by_source.get(source_key)
            if previous is None:
                best_evidence_by_source[source_key] = item
                continue
            previous_strength = (
                float(previous["confidence"]) * 0.6
                + float(previous["relevance"]) * 0.4
            )
            if strength > previous_strength:
                best_evidence_by_source[source_key] = item
        evidence_records = list(best_evidence_by_source.values())

        if existing is not None:
            evidence_rows = await connection.fetch(
                """
                select * from tcg.competitive_opportunity_evidence
                where opportunity_id=$1
                order by source_key,origin,id
                """,
                existing["id"],
            )
            same_core_contract = (
                existing["opportunity_type"] == payload.opportunity_type
                and existing["subject"] == payload.subject
                and existing["hypothesis"] == payload.hypothesis
                and float(existing["qualification_threshold"]) == payload.qualification_threshold
                and existing["state"] == decision.state
                and float(existing["score"]) == decision.score
            )
            existing_evidence_contract = sorted(
                (
                    row["origin"],
                    row["source_key"],
                    str(row["competitor_observation_id"] or ""),
                    float(row["confidence"]),
                    float(row["relevance"]),
                    row["rights_status"],
                    row["evidence"],
                )
                for row in evidence_rows
            )
            incoming_evidence_contract = sorted(
                (
                    item["origin"],
                    item["source_key"],
                    str(item["competitor_observation_id"] or ""),
                    float(item["confidence"]),
                    float(item["relevance"]),
                    item["rights_status"],
                    item["evidence"],
                )
                for item in evidence_records
            )
            if (
                not same_core_contract
                or existing_evidence_contract != incoming_evidence_contract
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Opportunity key already exists with a different evaluation contract",
                )
            return jsonable_encoder(
                {
                    "duplicate": True,
                    "opportunity": dict(existing),
                    "evidence": [dict(row) for row in evidence_rows],
                }
            )

        async with connection.transaction():
            row = await connection.fetchrow(
                """
                insert into tcg.competitive_opportunities(
                    opportunity_key,opportunity_type,subject,hypothesis,state,
                    score,qualification_threshold,reasons,
                    independent_sources,independent_origins,
                    competitor_sources,non_competitor_sources,created_by_user_id
                ) values(
                    $1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13
                )
                returning *
                """,
                payload.opportunity_key,
                payload.opportunity_type,
                payload.subject,
                payload.hypothesis,
                decision.state,
                decision.score,
                payload.qualification_threshold,
                json.dumps(list(decision.reasons)),
                decision.independent_sources,
                decision.independent_origins,
                decision.competitor_sources,
                decision.non_competitor_sources,
                user.user_id,
            )

            for item in evidence_records:
                await connection.execute(
                    """
                    insert into tcg.competitive_opportunity_evidence(
                        opportunity_id,origin,source_key,competitor_observation_id,
                        confidence,relevance,rights_status,evidence
                    ) values($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                    """,
                    row["id"],
                    item["origin"],
                    item["source_key"],
                    item["competitor_observation_id"],
                    item["confidence"],
                    item["relevance"],
                    item["rights_status"],
                    json.dumps(item["evidence"], sort_keys=True, separators=(",", ":")),
                )

        evidence_rows = await connection.fetch(
            """
            select * from tcg.competitive_opportunity_evidence
            where opportunity_id=$1
            order by created_at,id
            """,
            row["id"],
        )
        return jsonable_encoder(
            {
                "duplicate": False,
                "opportunity": dict(row),
                "evidence": [dict(item) for item in evidence_rows],
            }
        )


@router.get("/opportunities")
async def list_competitive_opportunities(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    state: Literal["WATCH", "QUALIFIED", "DISMISSED", "HANDED_OFF", "EXPIRED"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select o.*,
                   count(e.id)::integer as evidence_count
            from tcg.competitive_opportunities o
            left join tcg.competitive_opportunity_evidence e on e.opportunity_id=o.id
            where ($1::text is null or o.state=$1)
            group by o.id
            order by o.score desc,o.created_at desc,o.id
            limit $2
            """,
            state,
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})
