from __future__ import annotations

from statistics import median
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import SUPPORTED_MARKET_SOURCES, get_adapter
from .market_ingestion import _owner, safe_ingestion_error, validate_provider_observation


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])


class MarketSmokeRequest(BaseModel):
    catalogue_id: UUID
    source_product_id: str = Field(min_length=1, max_length=10000)
    source_variant_id: str | None = Field(default=None, max_length=1000)


async def _catalogue_exists(connection: asyncpg.Connection, catalogue_id: UUID) -> bool:
    return bool(
        await connection.fetchval(
            "select exists(select 1 from tcg.catalogue_products where id = $1)",
            catalogue_id,
        )
    )


def _price_summary(values: list[int]) -> dict[str, int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min_minor": ordered[0],
        "median_minor": int(median(ordered)),
        "max_minor": ordered[-1],
    }


@router.post("/smoke-test/{source}")
async def smoke_test_market_source(
    source: str,
    payload: MarketSmokeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Fetch and validate live provider evidence without persisting observations.

    This endpoint is intentionally authenticated and owner-scoped. It is an
    operator diagnostic for verifying mappings before they are promoted to
    VERIFIED and used by the normal ingestion pipeline.
    """

    source = source.upper().strip()
    if source not in SUPPORTED_MARKET_SOURCES:
        raise HTTPException(status_code=404, detail="Unsupported market data source")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)
        if not await _catalogue_exists(connection, payload.catalogue_id):
            raise HTTPException(status_code=404, detail="Catalogue product not found")

        adapter = get_adapter(source)
        if adapter is None:
            raise HTTPException(status_code=409, detail="Provider adapter access is not configured")

        try:
            observations = await adapter.fetch_observations(
                catalogue_id=str(payload.catalogue_id),
                source_product_id=payload.source_product_id,
                source_variant_id=payload.source_variant_id,
            )
            validated = [
                validate_provider_observation(
                    observation,
                    expected_source=source,
                    expected_catalogue_id=payload.catalogue_id,
                )
                for observation in observations
            ]
        except Exception as exc:
            safe_error = safe_ingestion_error(exc)
            status_code = 502 if safe_error["error_type"] == "PROVIDER_ERROR" else 422
            raise HTTPException(status_code=status_code, detail=safe_error) from exc

        type_counts: dict[str, int] = {}
        for observation in validated:
            type_counts[observation.observation_type] = type_counts.get(observation.observation_type, 0) + 1

        prices = [observation.price_gbp_minor for observation in validated]
        samples = []
        for observation in validated[:5]:
            samples.append(
                {
                    "observation_type": observation.observation_type,
                    "price_gbp_minor": observation.price_gbp_minor,
                    "shipping_gbp_minor": observation.shipping_gbp_minor,
                    "condition": observation.condition,
                    "grading_company": observation.grading_company,
                    "grade": observation.grade,
                    "language": observation.language,
                    "source_country": observation.source_country,
                    "title": observation.metadata.get("title") or observation.metadata.get("listing_title"),
                }
            )

        return jsonable_encoder(
            {
                "source": source,
                "catalogue_id": payload.catalogue_id,
                "observation_count": len(validated),
                "counts_by_type": type_counts,
                "price_summary_gbp": _price_summary(prices),
                "samples": samples,
                "persisted": False,
            }
        )
