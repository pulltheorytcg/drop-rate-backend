from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any
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
from .parse_client import ParseApiError


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
    if failed_mapping_count >= mapping_count and accepted_count == 0:
        return "FAILED"
    if failed_mapping_count > 0:
        return "PARTIAL"
    if accepted_count == 0:
        return "BLOCKED"
    return "SUCCEEDED"


def safe_ingestion_error(exc: Exception) -> dict[str, object]:
    """Return a persistence-safe error payload without provider secrets or raw bodies."""
    if isinstance(exc, ParseApiError):
        return {
            "detail": exc.detail,
            "provider_status_code": exc.status_code,
            "retryable": exc.retryable,
            "error_type": "PROVIDER_ERROR",
        }
    if isinstance(exc, (ValueError, TypeError)):
        return {
            "detail": "Provider data failed validation",
            "retryable": False,
            "error_type": "VALIDATION_ERROR",
        }
    return {
        "detail": "Unexpected market ingestion failure",
        "retryable": False,
        "error_type": "INTERNAL_ERROR",
    }


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
        ) values (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,
            greatest(clock_timestamp(), $12)
        )
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


async def _load_verified_mappings(
    connection: asyncpg.Connection,
    source: str,
) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        select id, catalogue_id, source, source_product_id, source_variant_id, version
        from tcg.market_source_mappings
        where source = $1 and match_status = 'VERIFIED'
        order by created_at, id
        """,
        source,
    )
    return [dict(row) for row in rows]


async def fetch_source_evidence(
    mappings: list[dict[str, Any]],
    *,
    source: str,
    adapter: MarketDataAdapter,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch and validate provider evidence without holding a database connection.

    All observations for one mapping are validated before any can be persisted.
    This avoids partial writes from a provider response that later proves invalid.
    """

    results: list[dict[str, Any]] = []
    fetched_count = 0

    for mapping in mappings:
        try:
            observations = await adapter.fetch_observations(
                catalogue_id=str(mapping["catalogue_id"]),
                source_product_id=mapping["source_product_id"],
                source_variant_id=mapping["source_variant_id"],
            )
            fetched_count += len(observations)
            validated = [
                validate_provider_observation(
                    observation,
                    expected_source=source,
                    expected_catalogue_id=mapping["catalogue_id"],
                )
                for observation in observations
            ]
            results.append(
                {
                    "mapping": mapping,
                    "observations": validated,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "mapping": mapping,
                    "observations": [],
                    "error": safe_ingestion_error(exc),
                }
            )

    return results, fetched_count


async def _current_mapping_rows(
    connection: asyncpg.Connection,
    mapping_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not mapping_ids:
        return {}
    rows = await connection.fetch(
        """
        select id, catalogue_id, source, source_product_id, source_variant_id,
               match_status, version
        from tcg.market_source_mappings
        where id = any($1::uuid[])
        """,
        mapping_ids,
    )
    return {row["id"]: dict(row) for row in rows}


def _mapping_is_current(snapshot: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None or current.get("match_status") != "VERIFIED":
        return False
    keys = (
        "catalogue_id",
        "source",
        "source_product_id",
        "source_variant_id",
        "version",
    )
    return all(current.get(key) == snapshot.get(key) for key in keys)


async def persist_source_evidence(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    source: str,
    trigger_type: str,
    mapping_results: list[dict[str, Any]],
    fetched_count: int,
    started_at: datetime,
) -> dict:
    """Persist only evidence whose VERIFIED mapping is unchanged since fetch time."""

    mapping_ids = [result["mapping"]["id"] for result in mapping_results]
    current_rows = await _current_mapping_rows(connection, mapping_ids)

    inserted_count = 0
    duplicate_count = 0
    failed_mapping_count = 0
    errors: list[dict] = []

    for result in mapping_results:
        mapping = result["mapping"]
        mapping_id = mapping["id"]
        error = result["error"]

        if error is not None:
            failed_mapping_count += 1
            errors.append(
                {
                    "mapping_id": str(mapping_id),
                    "catalogue_id": str(mapping["catalogue_id"]),
                    **error,
                }
            )
            continue

        if not _mapping_is_current(mapping, current_rows.get(mapping_id)):
            failed_mapping_count += 1
            errors.append(
                {
                    "mapping_id": str(mapping_id),
                    "catalogue_id": str(mapping["catalogue_id"]),
                    "detail": "Source mapping changed during provider fetch",
                    "retryable": True,
                    "error_type": "STALE_MAPPING",
                }
            )
            continue

        for observation in result["observations"]:
            if await _insert_observation(connection, observation):
                inserted_count += 1
            else:
                duplicate_count += 1

    status = derive_run_status(
        mapping_count=len(mapping_results),
        failed_mapping_count=failed_mapping_count,
        accepted_count=inserted_count + duplicate_count,
    )
    if status == "BLOCKED" and not errors:
        errors.append({"detail": "Provider returned no acceptable observations"})

    run = await _record_run(
        connection,
        owner_id=owner_id,
        source=source,
        trigger_type=trigger_type,
        status=status,
        mapping_count=len(mapping_results),
        fetched_count=fetched_count,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        failed_mapping_count=failed_mapping_count,
        errors=errors,
        started_at=started_at,
        metadata={"transaction_safe_provider_fetch": True},
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

    adapter = get_adapter(source)
    blocked_error: dict[str, Any] | None = None
    blocked_run: dict[str, Any] | None = None

    # Phase 1: authorise and snapshot VERIFIED mappings in one short transaction.
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]
        started_at = await connection.fetchval("select clock_timestamp()")
        mappings = await _load_verified_mappings(connection, source)

        if adapter is None:
            run = await _record_run(
                connection,
                owner_id=owner_id,
                source=source,
                trigger_type="MANUAL",
                status="BLOCKED",
                mapping_count=len(mappings),
                fetched_count=0,
                inserted_count=0,
                duplicate_count=0,
                failed_mapping_count=0,
                errors=[{"detail": "Provider adapter access is not configured"}],
                started_at=started_at,
                metadata={"transaction_safe_provider_fetch": True},
            )
            blocked_run = dict(run)
            blocked_error = {
                "message": "Provider adapter access is not configured",
                "source": source,
                "run_id": str(run["id"]),
            }
        elif not mappings:
            run = await _record_run(
                connection,
                owner_id=owner_id,
                source=source,
                trigger_type="MANUAL",
                status="BLOCKED",
                mapping_count=0,
                fetched_count=0,
                inserted_count=0,
                duplicate_count=0,
                failed_mapping_count=0,
                errors=[{"detail": "No VERIFIED source mappings are available"}],
                started_at=started_at,
                metadata={"transaction_safe_provider_fetch": True},
            )
            blocked_run = dict(run)

    # Raising only after the transaction has exited ensures the diagnostic run is committed.
    if blocked_error is not None:
        raise HTTPException(status_code=409, detail=blocked_error)
    if blocked_run is not None:
        return jsonable_encoder(blocked_run)

    # Phase 2: provider I/O happens with no database connection or transaction held.
    mapping_results, fetched_count = await fetch_source_evidence(
        mappings,
        source=source,
        adapter=adapter,
    )

    # Phase 3: re-check mapping versions and persist immutable observations atomically.
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        current_owner = await _owner(connection)
        if current_owner["id"] != owner_id:
            raise HTTPException(status_code=409, detail="Owner context changed during ingestion")
        result = await persist_source_evidence(
            connection,
            owner_id=owner_id,
            source=source,
            trigger_type="MANUAL",
            mapping_results=mapping_results,
            fetched_count=fetched_count,
            started_at=started_at,
        )

    return jsonable_encoder(result)
