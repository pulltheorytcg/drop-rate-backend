from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .access_control import require_platform_admin_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .recognition_engine import (
    SYSTEM_BY_GAME,
    attach_provider_visual_evidence,
    attach_visual_evidence,
    discover_provider_evidence,
    load_catalogue_candidates,
    resolve_candidates,
    visual_work_short_circuit_reason,
)
from .recognition_images import (
    RecognitionImageError,
    decode_image_data_url,
    reference_image_bytes,
)
from .recognition_learning import (
    attach_learning_visual_evidence,
    discover_learning_candidate_hints,
    encode_fingerprints,
    learning_status,
    materialize_learning_example,
    register_runtime_model,
)
from .recognition_reference_index import (
    attach_reference_candidate_hints,
    discover_reference_candidate_hints,
    rebuild_reference_index,
    reference_index_status,
)
from .recognition_vision import (
    OpenAIRecognitionVisionClient,
    RecognitionVisionError,
)
from .settings import get_settings


router = APIRouter(prefix="/api/v1/recognition", tags=["recognition"])
ENGINE_VERSION = "v1.5.1"
TERMINAL_STATUSES = {"EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH", "FAILED"}


class RecognitionRequest(BaseModel):
    image_data_url: str = Field(min_length=100, max_length=12_000_000)
    inventory_id: UUID | None = None
    force_refresh: bool = False


class RecognitionFeedbackRequest(BaseModel):
    outcome: Literal["CONFIRMED_TOP", "CORRECTED_TO_CANDIDATE", "CORRECTED_BY_SEARCH", "REJECTED_ALL"]
    selected_catalogue_id: UUID | None = None
    notes: str = Field(default="", max_length=2000)


class RecognitionReferenceIndexRebuildRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=500)
    catalogue_ids: list[UUID] | None = Field(default=None, max_length=500)


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


async def _run_payload(connection, run_id: UUID) -> dict[str, Any]:
    run = await connection.fetchrow(
        """
        select
            id,owner_id,inventory_id,idempotency_key,source_image_sha256,
            source_mime_type,source_size_bytes,source_width,source_height,
            source_fingerprints,status,system_code,ai_provider,
            ai_model,ai_observation,provider_evidence,top_catalogue_id,
            top_score,runner_up_score,score_margin,decision,decision_reasons,
            risk_flags,error_code,error_detail,started_at,completed_at,
            created_at,updated_at,version
        from tcg.recognition_runs
        where id=$1
        """,
        run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Recognition run not found")
    candidates = await connection.fetch(
        """
        select
            rc.id,rc.candidate_key,rc.source_kind,rc.system_code,rc.catalogue_id,
            rc.provider,rc.provider_id,rc.provider_language,rc.rank,rc.score,
            rc.hard_rejected,rc.rejection_reasons,rc.signals,
            rc.candidate_snapshot,rc.created_at,
            price.market_value_minor,
            price.recommended_retail_minor,
            price.pricing_updated_at,
            price.pricing_confidence,
            price.pricing_source_count,
            price.pricing_observation_count,
            price.pricing_newest_observation_at,
            price.pricing_algorithm_version
        from tcg.recognition_candidates rc
        left join lateral (
            select
                v.market_value_minor,
                v.recommended_retail_minor,
                v.pricing_updated_at,
                null::numeric as pricing_confidence,
                null::integer as pricing_source_count,
                null::integer as pricing_observation_count,
                null::timestamptz as pricing_newest_observation_at,
                'REFERENCE_SNAPSHOT'::text as pricing_algorithm_version
            from tcg.recognition_catalogue_reference_value(
                rc.catalogue_id,
                nullif(rc.candidate_snapshot->>'language','')
            ) v
        ) price on rc.catalogue_id is not null
        where rc.run_id=$1
        order by rc.rank
        """,
        run_id,
    )
    feedback = await connection.fetch(
        """
        select
            id,outcome,selected_catalogue_id,supersedes_feedback_id,
            actor_user_id,notes,created_at
        from tcg.recognition_feedback
        where run_id=$1
        order by created_at desc,id desc
        """,
        run_id,
    )
    return {
        "run": dict(run),
        "candidates": [dict(row) for row in candidates],
        "feedback": [dict(row) for row in feedback],
        "engine_version": ENGINE_VERSION,
        "auto_applied": False,
    }


@router.get("/status")
async def recognition_status(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    return {
        "configured": bool(settings.openai_api_key),
        "engine_version": ENGINE_VERSION,
        "vision_provider": "OpenAI",
        "vision_model": settings.recognition_model,
        "supported_games": ["Pokemon", "One Piece"],
        "exact_threshold": settings.recognition_exact_threshold_bps / 10_000,
        "minimum_runner_up_margin": settings.recognition_min_margin_bps / 10_000,
        "high_value_review_minor": settings.recognition_high_value_review_minor,
        "max_image_bytes": settings.recognition_max_image_bytes,
        "stores_source_image": False,
        "verified_learning_enabled": True,
        "persistent_reference_index_enabled": True,
        "reference_index_provisional_is_retrieval_only": True,
        "learning_labels": "HUMAN_VERIFIED_ONLY",
        "learning_raw_pixels_stored": False,
        "auto_applies_inventory_identity": False,
        "ai_can_self_verify": False,
    }


@router.get("/reference-index/status")
async def recognition_reference_index_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    _access: Annotated[dict, Depends(require_platform_admin_request)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)
        return jsonable_encoder(await reference_index_status(connection))


@router.post("/reference-index/rebuild")
async def recognition_reference_index_rebuild(
    payload: RecognitionReferenceIndexRebuildRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    _access: Annotated[dict, Depends(require_platform_admin_request)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)
        result = await rebuild_reference_index(
            connection,
            actor_user_id=user.user_id,
            limit=payload.limit,
            catalogue_ids=payload.catalogue_ids,
        )
        result["status"] = await reference_index_status(connection)
        return jsonable_encoder(result)


@router.get("/learning/status")
async def recognition_learning_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    _access: Annotated[dict, Depends(require_platform_admin_request)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        return jsonable_encoder(
            await learning_status(connection, owner_id=owner["id"])
        )


@router.get("/runs")
async def recognition_runs(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=100),
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
                r.id,r.inventory_id,i.inventory_code,r.status,r.system_code,
                r.ai_model,r.top_catalogue_id,r.top_score,r.runner_up_score,
                r.score_margin,r.decision,r.decision_reasons,r.risk_flags,
                r.created_at,r.completed_at,
                p.game as top_game,p.name as top_name,p.set_name as top_set_name,
                p.card_number as top_card_number,p.variant as top_variant,
                p.rarity as top_rarity,p.language as top_language
            from tcg.recognition_runs r
            left join tcg.inventory_items i on i.id=r.inventory_id
            left join tcg.catalogue_products p on p.id=r.top_catalogue_id
            where r.owner_id=$1
            order by r.created_at desc
            limit $2
            """,
            owner["id"],
            limit,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


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
        allowed = await connection.fetchval(
            "select exists(select 1 from tcg.recognition_runs where id=$1 and owner_id=$2)",
            run_id,
            owner["id"],
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="Recognition run not found")
        return jsonable_encoder(await _run_payload(connection, run_id))


@router.get("/runs/{run_id}/candidates/{candidate_id}/image")
async def recognition_candidate_image(
    run_id: UUID,
    candidate_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    """Proxy a trusted candidate image so browser hotlink rules cannot break the UI."""
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        image_url = await connection.fetchval(
            """
            select coalesce(
                nullif(rc.candidate_snapshot->>'reference_image_url',''),
                nullif(rc.candidate_snapshot->>'image_url','')
            )
            from tcg.recognition_candidates rc
            join tcg.recognition_runs rr on rr.id=rc.run_id
            where rr.id=$1
              and rr.owner_id=$2
              and rc.id=$3
            """,
            run_id,
            owner["id"],
            candidate_id,
        )

    if not image_url:
        raise HTTPException(status_code=404, detail="Candidate reference image not found")

    payload = await reference_image_bytes(str(image_url))
    if payload is None:
        raise HTTPException(status_code=502, detail="Candidate reference image is unavailable")

    return Response(
        content=payload.data,
        media_type=payload.content_type,
        headers={"Content-Disposition": "inline"},
    )


@router.post("/runs/{run_id}/feedback")
async def record_recognition_feedback(
    run_id: UUID,
    payload: RecognitionFeedbackRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    if payload.outcome in {"CONFIRMED_TOP", "CORRECTED_TO_CANDIDATE", "CORRECTED_BY_SEARCH"}:
        if payload.selected_catalogue_id is None:
            raise HTTPException(
                status_code=422,
                detail="Selected catalogue product is required for this feedback outcome",
            )
    elif payload.selected_catalogue_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Rejected-all feedback must not select a catalogue product",
        )

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        async with connection.transaction():
            run = await connection.fetchrow(
                """
                select id,owner_id,status,top_catalogue_id
                from tcg.recognition_runs
                where id=$1 and owner_id=$2
                for update
                """,
                run_id,
                owner["id"],
            )
            if run is None:
                raise HTTPException(status_code=404, detail="Recognition run not found")
            if run["status"] not in {"EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH"}:
                raise HTTPException(
                    status_code=409,
                    detail="Recognition run is not ready for human feedback",
                )

            if payload.outcome == "CONFIRMED_TOP":
                if payload.selected_catalogue_id != run["top_catalogue_id"]:
                    raise HTTPException(
                        status_code=422,
                        detail="Confirmed-top feedback must select the top candidate",
                    )

            if payload.outcome == "CORRECTED_TO_CANDIDATE":
                candidate_exists = await connection.fetchval(
                    """
                    select exists(
                        select 1
                        from tcg.recognition_candidates
                        where run_id=$1
                          and catalogue_id=$2
                          and not hard_rejected
                    )
                    """,
                    run_id,
                    payload.selected_catalogue_id,
                )
                if not candidate_exists:
                    raise HTTPException(
                        status_code=422,
                        detail="Selected catalogue product is not a viable candidate from this run",
                    )

            if payload.outcome == "CORRECTED_BY_SEARCH":
                searchable_card = await connection.fetchval(
                    """
                    select exists(
                        select 1
                        from tcg.catalogue_products p
                        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
                        where p.id=$1 and p.product_type='CARD'
                    )
                    """,
                    payload.selected_catalogue_id,
                )
                if not searchable_card:
                    raise HTTPException(
                        status_code=422,
                        detail="Search correction must select a recognised catalogue card",
                    )

            previous_feedback_id = await connection.fetchval(
                """
                select id
                from tcg.recognition_feedback
                where run_id=$1 and owner_id=$2
                order by created_at desc,id desc
                limit 1
                """,
                run_id,
                owner["id"],
            )

            feedback = await connection.fetchrow(
                """
                insert into tcg.recognition_feedback(
                    run_id,owner_id,outcome,selected_catalogue_id,
                    supersedes_feedback_id,actor_user_id,notes
                ) values($1,$2,$3,$4,$5,$6,$7)
                returning *
                """,
                run_id,
                owner["id"],
                payload.outcome,
                payload.selected_catalogue_id,
                previous_feedback_id,
                user.user_id,
                payload.notes.strip(),
            )
            if owner["role"] == "PLATFORM_ADMIN":
                learning_example = await materialize_learning_example(
                    connection,
                    run_id=run_id,
                    feedback_id=feedback["id"],
                    engine_version=ENGINE_VERSION,
                )
            else:
                learning_example = {
                    "skipped": True,
                    "reason": "PENDING_DROP_RATE_VERIFICATION",
                    "feedback_id": str(feedback["id"]),
                }

        result = await _run_payload(connection, run_id)
        result["recorded_feedback"] = dict(feedback)
        result["recorded_learning_example"] = learning_example
        return jsonable_encoder(result)


@router.post("/resolve")
async def recognize_card(
    payload: RecognitionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    pipeline_started = time.perf_counter()
    timings_ms: dict[str, float] = {}

    async def _timed(name: str, awaitable):
        started = time.perf_counter()
        try:
            return await awaitable
        finally:
            timings_ms[name] = round((time.perf_counter() - started) * 1000, 2)

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=409,
            detail="Recognition vision is not configured yet",
        )

    decode_started = time.perf_counter()
    try:
        image = decode_image_data_url(
            payload.image_data_url,
            max_bytes=settings.recognition_max_image_bytes,
        )
    except RecognitionImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    timings_ms["decode_image"] = round((time.perf_counter() - decode_started) * 1000, 2)

    inventory_context: dict[str, Any] | None = None
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]

        if payload.inventory_id is not None:
            row = await connection.fetchrow(
                """
                select
                    i.id,i.inventory_code,i.catalogue_id,i.language,
                    i.condition,i.grading_company,i.grade,i.certificate_number,
                    i.identity_confirmed,i.status,i.market_value_minor,
                    i.recommended_retail_minor,i.store_price_minor,i.version
                from tcg.inventory_items i
                where i.id=$1 and i.owner_id=$2
                """,
                payload.inventory_id,
                owner_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            inventory_context = dict(row)

        idempotency_key = (
            f"recognition:{ENGINE_VERSION}:{settings.recognition_model}:"
            f"{payload.inventory_id or 'unassigned'}:{image.sha256}"
        )
        if payload.force_refresh:
            idempotency_key = f"{idempotency_key}:{request.state.request_id}"

        existing = await connection.fetchrow(
            """
            select id,status
            from tcg.recognition_runs
            where owner_id=$1 and idempotency_key=$2
            """,
            owner_id,
            idempotency_key,
        )
        if existing is not None:
            if existing["status"] in TERMINAL_STATUSES:
                return jsonable_encoder(
                    await _run_payload(connection, existing["id"])
                )
            raise HTTPException(
                status_code=409,
                detail="An identical recognition run is already in progress",
            )

        if owner["role"] == "PLATFORM_ADMIN":
            await register_runtime_model(
                connection,
                engine_version=ENGINE_VERSION,
                vision_model=settings.recognition_model,
                actor_user_id=user.user_id,
            )
        run = await connection.fetchrow(
            """
            insert into tcg.recognition_runs(
                owner_id,inventory_id,idempotency_key,source_image_sha256,
                source_mime_type,source_size_bytes,source_width,source_height,
                source_fingerprints,status,ai_provider,ai_model,
                created_by_user_id
            ) values(
                $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,
                'OBSERVING','OpenAI',$10,$11
            )
            returning id
            """,
            owner_id,
            payload.inventory_id,
            idempotency_key,
            image.sha256,
            image.mime_type,
            image.size_bytes,
            image.width,
            image.height,
            json.dumps(encode_fingerprints(image.hashes)),
            settings.recognition_model,
            user.user_id,
        )
        run_id = run["id"]

    async def _load_reference_hints():
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            return await discover_reference_candidate_hints(
                connection,
                image.hashes,
            )

    vision = OpenAIRecognitionVisionClient(
        api_key=settings.openai_api_key,
        model=settings.recognition_model,
    )
    try:
        observation, reference_hints = await asyncio.gather(
            _timed("vision", vision.observe(payload.image_data_url)),
            _timed("reference_retrieval", _load_reference_hints()),
        )
    except RecognitionVisionError as exc:
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            await connection.execute(
                """
                update tcg.recognition_runs
                set status='FAILED',decision='FAILED',
                    error_code='VISION_PROVIDER_ERROR',
                    error_detail=$1,decision_reasons=$2::jsonb,
                    completed_at=clock_timestamp(),updated_at=clock_timestamp(),
                    version=version+1
                where id=$3 and owner_id=$4
                """,
                exc.detail[:1000],
                json.dumps([exc.detail]),
                run_id,
                owner_id,
            )
            result = await _run_payload(connection, run_id)
        return jsonable_encoder(result)

    system_code = SYSTEM_BY_GAME.get(observation.game)
    if system_code is None:
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            await connection.execute(
                """
                update tcg.recognition_runs
                set status='NEEDS_REVIEW',decision='NEEDS_REVIEW',
                    ai_observation=$1::jsonb,
                    decision_reasons=$2::jsonb,
                    risk_flags=$3::jsonb,
                    completed_at=clock_timestamp(),updated_at=clock_timestamp(),
                    version=version+1
                where id=$4 and owner_id=$5
                """,
                json.dumps(observation.model_dump(mode="json")),
                json.dumps(["Vision could not establish a supported game."]),
                json.dumps(["UNSUPPORTED_OR_UNKNOWN_GAME"]),
                run_id,
                owner_id,
            )
            return jsonable_encoder(await _run_payload(connection, run_id))

    reference_hints = [
        item
        for item in reference_hints
        if str(item.get("system_code") or "") == system_code
    ]

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await connection.execute(
            """
            update tcg.recognition_runs
            set status='CANDIDATES_READY',system_code=$1,
                ai_observation=$2::jsonb,updated_at=clock_timestamp(),
                version=version+1
            where id=$3 and owner_id=$4
            """,
            system_code,
            json.dumps(observation.model_dump(mode="json")),
            run_id,
            owner_id,
        )

    # v1.4 latency path: provider discovery and verified-learning hint lookup are
    # independent after vision, so run them concurrently.
    async def _load_learning_hints():
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            return await discover_learning_candidate_hints(
                connection,
                image.hashes,
                system_code=system_code,
            )

    provider_result, learning_hints = await asyncio.gather(
        _timed("provider_discovery", discover_provider_evidence(observation)),
        _timed("learning_hints", _load_learning_hints()),
    )
    provider_items = [
        dict(item)
        for item in provider_result.get("items", [])
        if isinstance(item, dict)
    ]

    visual_short_circuit = visual_work_short_circuit_reason(
        observation,
        inventory_context,
    )

    async def _load_candidates():
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            return await load_catalogue_candidates(
                connection,
                observation,
                provider_evidence=provider_items,
                learning_catalogue_ids=[
                    item["catalogue_id"] for item in learning_hints
                ],
                reference_catalogue_ids=[
                    item["catalogue_id"] for item in reference_hints
                ],
            )

    # Provider-image hashing does not affect which catalogue rows are selected;
    # it only enriches printing evidence. Run it beside catalogue I/O when exact
    # resolution is still possible.
    if visual_short_circuit:
        timings_ms["provider_visual"] = 0.0
        candidates = await _timed("catalogue_lookup", _load_candidates())
    else:
        candidates, _ = await asyncio.gather(
            _timed("catalogue_lookup", _load_candidates()),
            _timed(
                "provider_visual",
                attach_provider_visual_evidence(image.hashes, provider_items),
            ),
        )

    attach_reference_candidate_hints(candidates, reference_hints)

    # Prior human-verified TRAIN evidence remains active even when remote visual
    # work is safely short-circuited. It is bounded and cannot clear hard gates.
    async def _attach_learning_visual():
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            await attach_learning_visual_evidence(
                connection,
                image.hashes,
                candidates,
            )

    if visual_short_circuit:
        timings_ms["catalogue_visual"] = 0.0
        await _timed("learning_visual", _attach_learning_visual())
    else:
        await asyncio.gather(
            _timed("catalogue_visual", attach_visual_evidence(image.hashes, candidates)),
            _timed("learning_visual", _attach_learning_visual()),
        )

    resolve_started = time.perf_counter()
    resolved = resolve_candidates(
        observation,
        candidates,
        provider_evidence=provider_items,
        exact_threshold=settings.recognition_exact_threshold_bps / 10_000,
        min_margin=settings.recognition_min_margin_bps / 10_000,
        high_value_review_minor=settings.recognition_high_value_review_minor,
        inventory_context=inventory_context,
    )
    timings_ms["resolve"] = round((time.perf_counter() - resolve_started) * 1000, 2)
    timings_ms["pipeline_before_persist"] = round(
        (time.perf_counter() - pipeline_started) * 1000,
        2,
    )

    combined = list(resolved["candidates"])
    combined.sort(
        key=lambda item: (
            bool(item.get("hard_rejected")),
            -float(item.get("score") or 0),
            str(item.get("candidate_key") or ""),
        )
    )
    top = resolved.get("top")
    runner = resolved.get("runner_up")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        current_owner = await _owner(connection)
        if current_owner["id"] != owner_id:
            raise HTTPException(
                status_code=409,
                detail="Owner context changed during recognition",
            )
        async with connection.transaction():
            for index, candidate in enumerate(combined[:25], start=1):
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
                    """,
                    run_id,
                    str(candidate["candidate_key"]),
                    str(candidate["source_kind"]),
                    str(candidate["system_code"]),
                    candidate.get("catalogue_id"),
                    candidate.get("provider"),
                    candidate.get("provider_id"),
                    candidate.get("provider_language"),
                    index,
                    _decimal(candidate.get("score")),
                    bool(candidate.get("hard_rejected")),
                    json.dumps(candidate.get("rejection_reasons") or []),
                    json.dumps(candidate.get("signals") or {}),
                    json.dumps(candidate.get("candidate_snapshot") or {}, default=str),
                )

            await connection.execute(
                """
                update tcg.recognition_runs
                set status=$1,decision=$1,provider_evidence=$2::jsonb,
                    top_catalogue_id=$3,top_score=$4,runner_up_score=$5,
                    score_margin=$6,decision_reasons=$7::jsonb,
                    risk_flags=$8::jsonb,completed_at=clock_timestamp(),
                    updated_at=clock_timestamp(),version=version+1
                where id=$9 and owner_id=$10
                """,
                resolved["decision"],
                json.dumps(
                    {
                        "items": provider_items,
                        "errors": provider_result.get("errors", []),
                        "reference_index_hints": reference_hints,
                        "timings_ms": timings_ms,
                        "visual_short_circuit_reason": visual_short_circuit,
                        "reference_fingerprint_cache": "TTL_LRU_POSITIVE_ONLY",
                    },
                    default=str,
                ),
                top.get("catalogue_id") if top else None,
                _decimal(top.get("score")) if top else None,
                _decimal(runner.get("score")) if runner else None,
                _decimal(resolved.get("margin")),
                json.dumps(resolved.get("reasons") or []),
                json.dumps(resolved.get("risk_flags") or []),
                run_id,
                owner_id,
            )
        result = await _run_payload(connection, run_id)

    return jsonable_encoder(result)
