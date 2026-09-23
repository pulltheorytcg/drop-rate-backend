from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import (
    SUPPORTED_MARKET_SOURCES,
    MarketDataAdapter,
    NormalizedMarketObservation,
    adapter_availability,
    get_adapter,
)


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select id
        from tcg.owners
        where active
        order by founder_slot nulls last
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


def validate_provider_observation(
    observation: NormalizedMarketObservation,
    *,
    expected_source: str,
    expected_catalogue_id: UUID,
) -> NormalizedMarketObservation:
    observation.validate()
    if observation.source != expected_source:
        raise ValueError(
            f"Adapter returned source {observation.source}; expected {expected_source}"
        )
    if observation.catalogue_id != str(expected_catalogue_id):
        raise ValueError("Adapter returned an observation for the wrong catalogue product")
    return observation


def derive_run_status(*, mapping_count: int, failed_mapping_count: int, accepted_count: int) -> str:
    if mapping_count == 0:
        return "BLOCKED"
    if failed_mapping_count == 0:
        return "SUCCEEDED"
    if failed_mapping_count >= mapping_count and accepted_count == 0:
        return "FAILED"
    return "PARTIAL"


async def _record_run(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    source: str,
    trigger_type: str,
    status: str,
    mapping_count: int,
    fetched_count: int,
    inserted_count: int,
    duplicate_count: int,
    failed_mapping_count: int,
    errors: list[dict],
    started_at: datetime,
    metadata: dict | None = None,
) -> asyncpg.Record:
    return await connection.fetchrow(
        """
        insert into tcg.market_ingestion_runs(
            requested_by_owner_id,
            source,
            trigger_type,
            status,
            mapping_count,
            fetched_count,
            inserted_count,
            duplicate_count,
            failed_mapping_count,
            errors,
            metadata,
            started_at,
            completed_at
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,now())
        returning *
        """,
        owner_id,
        source,
        trigger_type,
        status,
        mapping_count,
        fetched_count,
        inserted_count,
        duplicate_count,
        failed_mapping_count,
        json.dumps(errors),
        json.dumps(metadata or {}),
        started_at,
    )


async def _insert_observation(
    connection: asyncpg.Connection,
    observation: NormalizedMarketObservation,
) -> bool:
    row = await connection.fetchrow(
        """
        insert into tcg.market_observations(
            catalogue_id,
            source,
            source_record_key,
            observation_type,
            observed_at,
            price_minor,
            shipping_minor,
            currency,
            price_gbp_minor,
            shipping_gbp_minor,
            fx_rate_to_gbp,
            condition,
            grading_company,
            grade,
            language,
            seal_status,
            source_country,
            sample_size,
            evidence_quality,
            metadata
        ) values (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20::jsonb
        )
        on conflict (source, source_record_key) do nothing
        returning id
        """,
        UUID(observation.catalogue_id),
        observation.source,
        observation.source_record_key,
        observation.observation_type,
        observation.observed_at,
        observation.price_minor,
        observation.shipping_minor,
        observation.currency.upper(),
        observation.price_gbp_minor,
        observation.shipping_gbp_minor,
        observation.fx_rate_to_gbp,
        observation.condition,
        observation.grading_company,
        observation.grade,
        observation.language,
        observation.seal_status,
        observation.source_country.upper() if observation.source_country else None,
        observation.sample_size,
        observation.evidence_quality,
        json.dumps(observation.metadata),
    )
    return row is not None


async def execute_source_ingestion(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    source: str,
    adapter: MarketDataAdapter,
    trigger_type: str = "MANUAL",
) -> dict:
    source = source.upper().strip()
    if source not in SUPPORTED_MARKET_SOURCES:
        raise ValueError(f"Unsupported market source: {source}")
    if adapter.source.upper().strip() != source:
        raise ValueError("Adapter source does not match requested source")

    started_at = datetime.now(timezone.utc)
    mappings = await connection.fetch(
        """
        select id, catalogue_id, source_product_id, source_variant_id
        from tcg.market_source_mappings
        where source = $1 and match_status = 'VERIFIED'
        order by created_at, id
        """,
        source,
    )
    mapping_count = len(mappings)
    fetched_count = 0
    inserted_count = 0
    duplicate_count = 0
    failed_mapping_count = 0
    errors: list[dict] = []

    if not mappings:
        run = await _record_run(
            connection,
            owner_id=owner_id,
            source=source,
            trigger_type=trigger_type,
            status="BLOCKED",
            mapping_count=0,
            fetched_count=0,
            inserted_count=0,
            duplicate_count=0,
            failed_mapping_count=0,
            errors=[{"detail": "No VERIFIED source mappings are available"}],
            started_at=started_at,
        )
        return dict(run)

    for mapping in mappings:
        try:
            observations = await adapter.fetch_observations(
                catalogue_id=str(mapping["catalogue_id"]),
                source_product_id=mapping["source_product_id"],
                source_variant_id=mapping["source_variant_id"],
            )
            fetched_count += len(observations)
            for observation in observations:
                validate_provider_observation(
                    observation,
                    expected_source=source,
                    expected_catalogue_id=mapping["catalogue_id"],
                )
                if await _insert_observation(connection, observation):
                    inserted_count += 1
                else:
                    duplicate_count += 1
        except Exception as exc:
            failed_mapping_count += 1
            errors.append(
                {
                    "mapping_id": str(mapping["id"]),
                    "catalogue_id": str(mapping["catalogue_id"]),
                    "detail": str(exc)[:500],
                }
            )

    status = derive_run_status(
        mapping_count=mapping_count,
        failed_mapping_count=failed_mapping_count,
        accepted_count=inserted_count + duplicate_count,
    )
    run = await _record_run(
        connection,
        owner_id=owner_id,
        source=source,
        trigger_type=trigger_type,
        status=status,
        mapping_count=mapping_count,
        fetched_count=fetched_count,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        failed_mapping_count=failed_mapping_count,
        errors=errors,
        started_at=started_at,
    )
    return dict(run)


@router.get("/status")
async def market_data_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        mapping_rows = await connection.fetch(
            """
            select source, count(*)::int as count
            from tcg.market_source_mappings
            where match_status = 'VERIFIED'
            group by source
            """
        )
        observation_rows = await connection.fetch(
            """
            select source, count(*)::int as count, max(observed_at) as newest_observation_at
            from tcg.market_observations
            group by source
            """
        )
        latest_runs = await connection.fetch(
            """
            select distinct on (source)
                source, status, mapping_count, fetched_count, inserted_count,
                duplicate_count, failed_mapping_count, completed_at
            from tcg.market_ingestion_runs
            where requested_by_owner_id = $1
            order by source, completed_at desc
            """,
            owner["id"],
        )

        mapping_counts = {row["source"]: row["count"] for row in mapping_rows}
        observation_counts = {row["source"]: row for row in observation_rows}
        runs = {row["source"]: row for row in latest_runs}
        items = []
        for adapter in adapter_availability():
            source = str(adapter["source"])
            observation = observation_counts.get(source)
            latest = runs.get(source)
            items.append(
                {
                    **adapter,
                    "verified_mapping_count": mapping_counts.get(source, 0),
                    "observation_count": observation["count"] if observation else 0,
                    "newest_observation_at": observation["newest_observation_at"] if observation else None,
                    "latest_run": dict(latest) if latest else None,
                }
            )
        return jsonable_encoder({"items": items})


@router.get("/ingestion/runs")
async def market_ingestion_runs(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select *
            from tcg.market_ingestion_runs
            where requested_by_owner_id = $1
            order by completed_at desc
            limit $2
            """,
            owner["id"],
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/ingestion/{source}")
async def run_market_ingestion(
    source: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    source = source.upper().strip()
    if source not in SUPPORTED_MARKET_SOURCES:
        raise HTTPException(status_code=404, detail="Unsupported market data source")

    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        adapter = get_adapter(source)
        if adapter is None:
            mapping_count = await connection.fetchval(
                """
                select count(*)
                from tcg.market_source_mappings
                where source = $1 and match_status = 'VERIFIED'
                """,
                source,
            )
            run = await _record_run(
                connection,
                owner_id=owner["id"],
                source=source,
                trigger_type="MANUAL",
                status="BLOCKED",
                mapping_count=int(mapping_count or 0),
                fetched_count=0,
                inserted_count=0,
                duplicate_count=0,
                failed_mapping_count=0,
                errors=[{"detail": "Provider adapter access is not configured"}],
                started_at=datetime.now(timezone.utc),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Provider adapter access is not configured",
                    "source": source,
                    "run_id": str(run["id"]),
                },
            )

        result = await execute_source_ingestion(
            connection,
            owner_id=owner["id"],
            source=source,
            adapter=adapter,
        )
        return jsonable_encoder(result)
