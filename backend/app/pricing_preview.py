from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import NormalizedMarketObservation, get_adapter
from .market_ingestion import _owner, fetch_source_evidence
from .pricing_engine import (
    ComparableTarget,
    MarketObservation,
    PricingPolicy,
    calculate_price,
)


router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])

# eBay sold remains deliberately excluded while the upstream sold-search endpoint
# returns an empty result set. These sources consume at most five Parse calls for
# one mapping each (Cardmarket 2, TCGPlayer 2, Collectr 1).
PREVIEW_SOURCES = ("CARDMARKET", "TCGPLAYER", "COLLECTR")


def _pricing_policy(row: dict[str, Any] | None) -> PricingPolicy:
    if row is None:
        return PricingPolicy()
    return PricingPolicy(
        min_confidence=float(row["min_confidence"]),
        min_sources=int(row["min_sources"]),
        max_auto_change_pct=float(row["max_auto_change_pct"]),
        high_value_review_minor=int(row["high_value_review_minor"]),
        min_price_change_minor=int(row["min_price_change_minor"]),
        min_price_change_pct=float(row["min_price_change_pct"]),
        max_volatility_pct=float(row["max_volatility_pct"]),
        retail_multiplier=float(row["retail_multiplier"]),
        quick_sale_multiplier=float(row["quick_sale_multiplier"]),
        acquisition_multiplier=float(row["acquisition_multiplier"]),
    )


def _evidence_sample(item: NormalizedMarketObservation) -> dict[str, Any]:
    """Expose only normalized, decision-useful evidence to the diagnostic UI."""

    return {
        "source": item.source,
        "observation_type": item.observation_type,
        "observed_at": item.observed_at,
        "price_gbp_minor": item.price_gbp_minor,
        "shipping_gbp_minor": item.shipping_gbp_minor,
        "condition": item.condition,
        "grading_company": item.grading_company,
        "grade": item.grade,
        "language": item.language,
        "seal_status": item.seal_status,
        "source_country": item.source_country,
        "sample_size": item.sample_size,
        "evidence_quality": item.evidence_quality,
    }


def _pricing_observation(item: NormalizedMarketObservation) -> MarketObservation:
    return MarketObservation(
        source=item.source,
        observation_type=item.observation_type,
        observed_at=item.observed_at,
        price_gbp_minor=item.price_gbp_minor,
        sample_size=item.sample_size,
        evidence_quality=item.evidence_quality,
        condition=item.condition,
        grading_company=item.grading_company,
        grade=item.grade,
        language=item.language,
        seal_status=item.seal_status,
        source_country=item.source_country,
    )


async def _preview_snapshot(
    request: Request,
    user: AuthenticatedUser,
    inventory_id: UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]], PricingPolicy]:
    """Snapshot all DB state, then release the connection before provider I/O."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        item = await connection.fetchrow(
            """
            select
                i.id, i.inventory_code, i.catalogue_id, i.condition,
                i.grading_company, i.grade, i.language, i.seal_status,
                i.store_price_minor, i.identity_confirmed, i.status,
                p.game, p.name, p.set_name, p.card_number, p.variant
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            where i.id = $1 and i.owner_id = $2
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if item["status"] in {"SOLD", "WITHDRAWN"}:
            raise HTTPException(
                status_code=409,
                detail="Pricing preview is unavailable for sold or withdrawn inventory",
            )

        mapping_rows = await connection.fetch(
            """
            select id, catalogue_id, source, source_product_id, source_variant_id, version
            from tcg.market_source_mappings
            where catalogue_id = $1
              and match_status = 'VERIFIED'
              and source = any($2::text[])
            order by source
            """,
            item["catalogue_id"],
            list(PREVIEW_SOURCES),
        )
        policy_row = await connection.fetchrow(
            "select * from tcg.pricing_policies where owner_id = $1",
            owner["id"],
        )

    return dict(item), [dict(row) for row in mapping_rows], _pricing_policy(
        dict(policy_row) if policy_row is not None else None
    )


@router.get("/preview-items/{catalogue_id}")
async def pricing_preview_items(
    catalogue_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """List physical copies that can be used as a diagnostic comparable target."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select id, inventory_code, condition, grading_company, grade, language,
                   seal_status, identity_confirmed, status, store_price_minor
            from tcg.inventory_items
            where owner_id = $1
              and catalogue_id = $2
              and status not in ('SOLD', 'WITHDRAWN')
            order by inventory_code
            """,
            owner["id"],
            catalogue_id,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/preview/{inventory_id}")
async def preview_inventory_price(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Calculate a live diagnostic price without persisting provider evidence."""

    item, mappings, policy = await _preview_snapshot(request, user, inventory_id)
    if not mappings:
        return jsonable_encoder(
            {
                "persisted": False,
                "publishable": False,
                "status": "BLOCKED",
                "inventory": item,
                "block_reasons": ["No VERIFIED market mappings are available"],
                "sources": [],
            }
        )

    by_source: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        by_source.setdefault(str(mapping["source"]), []).append(mapping)

    normalized: list[NormalizedMarketObservation] = []
    source_results: list[dict[str, Any]] = []

    for source in PREVIEW_SOURCES:
        source_mappings = by_source.get(source, [])
        if not source_mappings:
            continue

        adapter = get_adapter(source)
        if adapter is None:
            source_results.append(
                {
                    "source": source,
                    "status": "FAILED",
                    "observation_count": 0,
                    "error": {"detail": "Provider adapter access is not configured"},
                }
            )
            continue

        mapping_results, fetched_count = await fetch_source_evidence(
            source_mappings,
            source=source,
            adapter=adapter,
        )
        accepted_count = 0
        errors: list[dict[str, Any]] = []
        source_observations: list[NormalizedMarketObservation] = []
        for mapping_result in mapping_results:
            if mapping_result["error"] is not None:
                errors.append(mapping_result["error"])
                continue
            observations = mapping_result["observations"]
            normalized.extend(observations)
            source_observations.extend(observations)
            accepted_count += len(observations)

        source_results.append(
            {
                "source": source,
                "status": "SUCCEEDED" if accepted_count else ("FAILED" if errors else "EMPTY"),
                "fetched_count": fetched_count,
                "observation_count": accepted_count,
                "errors": errors,
                "evidence_sample": [
                    _evidence_sample(observation)
                    for observation in sorted(
                        source_observations,
                        key=lambda observation: observation.observed_at,
                        reverse=True,
                    )[:8]
                ],
            }
        )

    target = ComparableTarget(
        condition=item["condition"],
        grading_company=item["grading_company"],
        grade=item["grade"],
        language=item["language"],
        seal_status=item["seal_status"],
    )
    warnings: list[str] = []
    if not item["identity_confirmed"]:
        warnings.append("Physical card identity has not yet been confirmed")
    if item["condition"] is None and item["grading_company"] is None and item["seal_status"] is None:
        warnings.append("Physical condition/state is incomplete, so comparable evidence may be unavailable")

    observations = [_pricing_observation(row) for row in normalized]
    try:
        result = calculate_price(
            observations,
            target=target,
            policy=policy,
            current_store_price_minor=item["store_price_minor"],
            as_of=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        return jsonable_encoder(
            {
                "persisted": False,
                "publishable": False,
                "status": "BLOCKED",
                "inventory": item,
                "block_reasons": [str(exc)],
                "warnings": warnings,
                "sources": source_results,
                "observation_count": len(observations),
            }
        )

    return jsonable_encoder(
        {
            "persisted": False,
            "publishable": False,
            "status": "PREVIEW",
            "inventory": item,
            "warnings": warnings,
            "sources": source_results,
            "pricing": {
                "market_value_minor": result.market_value_minor,
                "recommended_retail_minor": result.recommended_retail_minor,
                "quick_sale_minor": result.quick_sale_minor,
                "target_acquisition_minor": result.target_acquisition_minor,
                "confidence": result.confidence,
                "source_count": result.source_count,
                "observation_count": result.observation_count,
                "sold_observation_count": result.sold_observation_count,
                "volatility_pct": result.volatility_pct,
                "newest_observation_at": result.newest_observation_at,
                "algorithm_version": result.algorithm_version,
                "engine_auto_publish_eligible": result.auto_publish_eligible,
                "engine_block_reasons": list(result.block_reasons),
                "source_estimates": [
                    {
                        "source": estimate.source,
                        "estimate_minor": estimate.estimate_minor,
                        "weight": estimate.weight,
                        "observation_count": estimate.observation_count,
                        "sold_observation_count": estimate.sold_observation_count,
                        "freshness": estimate.freshness,
                        "evidence_quality": estimate.evidence_quality,
                        "newest_observation_at": estimate.newest_observation_at,
                    }
                    for estimate in result.source_estimates
                ],
            },
        }
    )
