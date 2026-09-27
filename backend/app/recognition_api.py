from __future__ import annotations

import json
from typing import Annotated, Any, Mapping
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .recognition_engine import (
    SYSTEM_BY_GAME,
    attach_visual_evidence,
    discover_provider_evidence,
    load_catalogue_candidates,
    resolve_candidates,
)
from .recognition_images import RecognitionImageError, decode_image_data_url
from .recognition_vision import (
    OpenAIRecognitionVisionClient,
    RecognitionObservation,
    RecognitionVisionError,
)
from .settings import get_settings


router = APIRouter(prefix="/api/v1/recognition", tags=["recognition"])


class RecognitionAnalyzeRequest(BaseModel):
    image_data_url: str = Field(min_length=100, max_length=28_000_000)
    inventory_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_key(self) -> "RecognitionAnalyzeRequest":
        if self.idempotency_key is not None:
            self.idempotency_key = self.idempotency_key.strip()
            if len(self.idempotency_key) < 8:
                raise ValueError("idempotency_key is too short")
        return self


class RecognitionEvaluateRequest(BaseModel):
    observation: RecognitionObservation
    inventory_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_key(self) -> "RecognitionEvaluateRequest":
        if self.idempotency_key is not None:
            self.idempotency_key = self.idempotency_key.strip()
        return self


async def _inventory_context(connection, owner_id: UUID, inventory_id: UUID | None):
    if inventory_id is None:
        return None
    row = await connection.fetchrow(
        """
        select
            i.id,i.inventory_code,i.owner_id,i.catalogue_id,i.status,
            i.condition,i.grading_company,i.grade,i.certificate_number,
            i.language,i.store_price_minor,i.market_value_minor,i.version
        from tcg.inventory_items i
        where i.id=$1 and i.owner_id=$2
        """,
        inventory_id,
        owner_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return dict(row)


async def _existing_run(connection, owner_id: UUID, idempotency_key: str):
    return await connection.fetchrow(
        """
        select *
        from tcg.recognition_runs
        where owner_id=$1 and idempotency_key=$2
        """,
        owner_id,
        idempotency_key,
    )


async def _run_payload(connection, run_id: UUID, owner_id: UUID) -> dict:
    run = await connection.fetchrow(
        """
        select *
        from tcg.recognition_runs
        where id=$1 and owner_id=$2
        """,
        run_id,
        owner_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Recognition run not found")
    candidates = await connection.fetch(
        """
        select *
        from tcg.recognition_candidates
        where run_id=$1
        order by rank,id
        """,
        run_id,
    )
    return {
        "run": dict(run),
        "candidates": [dict(row) for row in candidates],
        "inventory_mutated": False,
    }


async def _create_run(
    request: Request,
    user: AuthenticatedUser,
    *,
    inventory_id: UUID | None,
    idempotency_key: str,
    source_image_sha256: str | None,
    source_mime_type: str | None,
    source_size_bytes: int | None,
    ai_provider: str,
    ai_model: str | None,
) -> tuple[UUID, UUID, dict | None, dict | None]:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]
        inventory = await _inventory_context(connection, owner_id, inventory_id)
        existing = await _existing_run(connection, owner_id, idempotency_key)
        if existing is not None:
            return existing["id"], owner_id, inventory, dict(existing)

        row = await connection.fetchrow(
            """
            insert into tcg.recognition_runs(
                owner_id,inventory_id,idempotency_key,source_image_sha256,
                source_mime_type,source_size_bytes,status,ai_provider,ai_model,
                created_by_user_id
            ) values(
                $1,$2,$3,$4,$5,$6,'OBSERVING',$7,$8,$9
            )
            returning *
            """,
            owner_id,
            inventory_id,
            idempotency_key,
            source_image_sha256,
            source_mime_type,
            source_size_bytes,
            ai_provider,
            ai_model,
            user.user_id,
        )
        return row["id"], owner_id, inventory, None


async def _mark_failed(
    request: Request,
    user: AuthenticatedUser,
    *,
    run_id: UUID,
    owner_id: UUID,
    code: str,
    detail: str,
) -> None:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await connection.execute(
            """
            update tcg.recognition_runs
            set status='FAILED',decision='FAILED',error_code=$1,error_detail=$2,
                decision_reasons=jsonb_build_array($2),
                completed_at=clock_timestamp(),updated_at=clock_timestamp(),
                version=version+1
            where id=$3 and owner_id=$4 and status='OBSERVING'
            """,
            code[:120],
            detail[:1000],
            run_id,
            owner_id,
        )


async def _resolve_and_persist(
    request: Request,
    user: AuthenticatedUser,
    *,
    run_id: UUID,
    owner_id: UUID,
    observation: RecognitionObservation,
    inventory_context: Mapping[str, Any] | None,
    source_hashes: tuple[int, ...] | None,
    provider_evidence: dict[str, Any] | None = None,
) -> dict:
    settings = get_settings()

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        candidates = await load_catalogue_candidates(connection, observation)

    evidence = provider_evidence or await discover_provider_evidence(observation)
    evidence_items = [
        item for item in evidence.get("items", [])
        if isinstance(item, Mapping)
    ]

    if source_hashes and candidates:
        await attach_visual_evidence(source_hashes, candidates)

    resolution = resolve_candidates(
        observation,
        candidates,
        provider_evidence=evidence_items,
        exact_threshold=settings.recognition_exact_threshold_bps / 10_000,
        min_margin=settings.recognition_min_margin_bps / 10_000,
        high_value_review_minor=settings.recognition_high_value_review_minor,
        inventory_context=inventory_context,
    )

    system_code = SYSTEM_BY_GAME.get(observation.game)
    raw_candidates = list(resolution["candidates"])
    raw_candidates.sort(
        key=lambda item: (
            bool(item.get("hard_rejected")),
            -float(item.get("score") or 0),
            str(item.get("candidate_key") or ""),
        )
    )
    ranked_candidates = []
    for rank, item in enumerate(raw_candidates, start=1):
        ranked_candidates.append({**item, "rank": rank})

    top = resolution.get("top")
    runner = resolution.get("runner_up")
    decision = str(resolution["decision"])
    top_catalogue_id = top.get("catalogue_id") if top else None
    top_score = float(top["score"]) if top else None
    runner_score = float(runner["score"]) if runner else None

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        async with connection.transaction():
            locked = await connection.fetchrow(
                """
                select id,status,system_code
                from tcg.recognition_runs
                where id=$1 and owner_id=$2
                for update
                """,
                run_id,
                owner_id,
            )
            if locked is None:
                raise HTTPException(status_code=404, detail="Recognition run not found")
            if locked["status"] not in {"OBSERVING", "CANDIDATES_READY"}:
                return await _run_payload(connection, run_id, owner_id)

            await connection.execute(
                """
                update tcg.recognition_runs
                set status='CANDIDATES_READY',system_code=$1,
                    ai_observation=$2::jsonb,provider_evidence=$3::jsonb,
                    updated_at=clock_timestamp(),version=version+1
                where id=$4 and owner_id=$5
                """,
                system_code,
                json.dumps(observation.model_dump()),
                json.dumps(evidence),
                run_id,
                owner_id,
            )

            for item in ranked_candidates:
                await connection.execute(
                    """
                    insert into tcg.recognition_candidates(
                        run_id,candidate_key,source_kind,system_code,catalogue_id,
                        provider,provider_id,provider_language,rank,score,
                        hard_rejected,rejection_reasons,signals,candidate_snapshot
                    ) values(
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                        $12::jsonb,$13::jsonb,$14::jsonb
                    )
                    on conflict (run_id,candidate_key) do nothing
                    """,
                    run_id,
                    item["candidate_key"],
                    item["source_kind"],
                    item.get("system_code") or system_code,
                    item.get("catalogue_id"),
                    item.get("provider"),
                    item.get("provider_id"),
                    item.get("provider_language"),
                    item["rank"],
                    float(item.get("score") or 0),
                    bool(item.get("hard_rejected")),
                    json.dumps(item.get("rejection_reasons") or []),
                    json.dumps(item.get("signals") or {}),
                    json.dumps(item.get("candidate_snapshot") or {}, default=str),
                )

            await connection.execute(
                """
                update tcg.recognition_runs
                set status=$1,decision=$1,top_catalogue_id=$2,
                    top_score=$3,runner_up_score=$4,score_margin=$5,
                    decision_reasons=$6::jsonb,risk_flags=$7::jsonb,
                    completed_at=clock_timestamp(),updated_at=clock_timestamp(),
                    version=version+1
                where id=$8 and owner_id=$9
                """,
                decision,
                top_catalogue_id,
                top_score,
                runner_score,
                resolution.get("margin"),
                json.dumps(resolution.get("reasons") or []),
                json.dumps(resolution.get("risk_flags") or []),
                run_id,
                owner_id,
            )
            return await _run_payload(connection, run_id, owner_id)


@router.get("/status")
async def recognition_status(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    return {
        "configured": bool(settings.openai_api_key),
        "vision_provider": "OpenAI",
        "vision_model": settings.recognition_model,
        "supported_games": ["Pokemon", "One Piece"],
        "supported_languages": ["English", "Japanese"],
        "exact_threshold": settings.recognition_exact_threshold_bps / 10_000,
        "minimum_margin": settings.recognition_min_margin_bps / 10_000,
        "high_value_review_minor": settings.recognition_high_value_review_minor,
        "max_image_bytes": settings.recognition_max_image_bytes,
        "automatic_inventory_mutation": False,
        "provider_evidence": {
            "Pokemon Japanese": "TCGdex",
            "One Piece Japanese": "Punk Records",
        },
        "safety": {
            "ambiguous_printings_fail_closed": True,
            "graded_items_require_review": True,
            "high_value_items_require_review": True,
            "counterfeit_concerns_require_review": True,
        },
    }


@router.post("/analyze")
async def analyze_card(
    payload: RecognitionAnalyzeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=409,
            detail="Recognition vision is not configured; add TCG_OPENAI_API_KEY",
        )

    try:
        image = decode_image_data_url(
            payload.image_data_url,
            max_bytes=settings.recognition_max_image_bytes,
        )
    except RecognitionImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    key = payload.idempotency_key or f"scan:{image.sha256}:{payload.inventory_id or 'new'}"
    run_id, owner_id, inventory, existing = await _create_run(
        request,
        user,
        inventory_id=payload.inventory_id,
        idempotency_key=key,
        source_image_sha256=image.sha256,
        source_mime_type=image.mime_type,
        source_size_bytes=image.size_bytes,
        ai_provider="OpenAI",
        ai_model=settings.recognition_model,
    )
    if existing is not None:
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            return jsonable_encoder(await _run_payload(connection, run_id, owner_id))

    client = OpenAIRecognitionVisionClient(
        api_key=settings.openai_api_key,
        model=settings.recognition_model,
    )
    try:
        observation = await client.observe(payload.image_data_url)
    except RecognitionVisionError as exc:
        await _mark_failed(
            request,
            user,
            run_id=run_id,
            owner_id=owner_id,
            code="VISION_PROVIDER_ERROR",
            detail=exc.detail,
        )
        raise HTTPException(
            status_code=502 if exc.retryable else 422,
            detail=exc.detail,
        ) from exc

    try:
        result = await _resolve_and_persist(
            request,
            user,
            run_id=run_id,
            owner_id=owner_id,
            observation=observation,
            inventory_context=inventory,
            source_hashes=image.hashes,
        )
    except Exception:
        await _mark_failed(
            request,
            user,
            run_id=run_id,
            owner_id=owner_id,
            code="RESOLUTION_ERROR",
            detail="Recognition evidence could not be resolved safely",
        )
        raise

    return jsonable_encoder(result)


@router.post("/evaluate-observation")
async def evaluate_observation(
    payload: RecognitionEvaluateRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Evaluate structured evidence without invoking vision.

    This endpoint exists for deterministic testing, provider diagnostics and
    future interchangeable vision providers. It never confirms inventory.
    """

    key = payload.idempotency_key or f"evidence:{uuid4()}"
    run_id, owner_id, inventory, existing = await _create_run(
        request,
        user,
        inventory_id=payload.inventory_id,
        idempotency_key=key,
        source_image_sha256=None,
        source_mime_type=None,
        source_size_bytes=None,
        ai_provider="STRUCTURED_EVIDENCE",
        ai_model=None,
    )
    if existing is not None:
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            return jsonable_encoder(await _run_payload(connection, run_id, owner_id))

    result = await _resolve_and_persist(
        request,
        user,
        run_id=run_id,
        owner_id=owner_id,
        observation=payload.observation,
        inventory_context=inventory,
        source_hashes=None,
    )
    return jsonable_encoder(result)


@router.get("/runs/{run_id}")
async def recognition_run(
    run_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        return jsonable_encoder(await _run_payload(connection, run_id, owner["id"]))


@router.get("/runs")
async def recent_recognition_runs(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                r.id,r.inventory_id,r.status,r.system_code,r.ai_provider,r.ai_model,
                r.top_catalogue_id,r.top_score,r.runner_up_score,r.score_margin,
                r.decision,r.decision_reasons,r.risk_flags,r.started_at,r.completed_at,
                p.name as top_name,p.set_name as top_set_name,p.card_number as top_card_number,
                p.variant as top_variant,p.rarity as top_rarity
            from tcg.recognition_runs r
            left join tcg.catalogue_products p on p.id=r.top_catalogue_id
            where r.owner_id=$1
            order by r.created_at desc
            limit 50
            """,
            owner["id"],
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})
