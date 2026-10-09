from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import mean, median
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import adapter_availability
from .pricing_engine import ComparableTarget, MarketObservation, PricingPolicy, calculate_price


router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


class PricingPolicyPatch(BaseModel):
    auto_reprice_enabled: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    min_sources: int | None = Field(default=None, ge=1, le=10)
    max_auto_change_pct: float | None = Field(default=None, gt=0, le=100)
    high_value_review_minor: int | None = Field(default=None, ge=0)
    min_price_change_minor: int | None = Field(default=None, ge=0)
    min_price_change_pct: float | None = Field(default=None, ge=0, le=100)
    max_volatility_pct: float | None = Field(default=None, ge=0, le=500)
    retail_multiplier: float | None = Field(default=None, gt=0, le=5)
    quick_sale_multiplier: float | None = Field(default=None, gt=0, le=5)
    acquisition_multiplier: float | None = Field(default=None, gt=0, le=5)
    version: int = Field(ge=1)


class BatchRecalculate(BaseModel):
    inventory_ids: list[UUID] = Field(min_length=1, max_length=100)



SOLD_EVIDENCE_MIN_COMPS = 5
SOLD_EVIDENCE_TARGET_COMPS = 10
SOLD_EVIDENCE_DEFAULT_FRESHNESS_DAYS = 7


def _evidence_norm(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().casefold()
    return cleaned or None


def _same_pricing_identity(observation: dict, target: dict) -> bool:
    """Require exact physical pricing identity for sold-history reuse."""
    for field in ("condition", "grading_company", "grade", "language", "seal_status"):
        if _evidence_norm(observation.get(field)) != _evidence_norm(target.get(field)):
            return False
    return True


def _sold_identity_key(observation: dict) -> tuple[str, str]:
    metadata = observation.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    external_id = (
        metadata.get("provider_item_id")
        or metadata.get("item_id")
        or metadata.get("listing_id")
    )
    source = str(observation.get("source") or "").strip().upper()
    if external_id is not None and str(external_id).strip():
        return source, str(external_id).strip()
    return source, str(observation.get("source_record_key") or "").strip()


def summarize_sold_evidence(
    observations: list[dict],
    *,
    target: dict,
    as_of: datetime,
    freshness_days: int = SOLD_EVIDENCE_DEFAULT_FRESHNESS_DAYS,
) -> dict:
    """Summarize our own exact SOLD history without calling any provider."""
    if freshness_days < 1:
        raise ValueError("freshness_days must be at least 1")
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    exact = [
        dict(item)
        for item in observations
        if str(item.get("observation_type") or "").upper() == "SOLD"
        and _same_pricing_identity(item, target)
    ]

    deduped: dict[tuple[str, str], dict] = {}
    for item in exact:
        key = _sold_identity_key(item)
        current = deduped.get(key)
        if current is None or item["observed_at"] > current["observed_at"]:
            deduped[key] = item

    ordered = sorted(deduped.values(), key=lambda item: item["observed_at"], reverse=True)
    selected = ordered[:SOLD_EVIDENCE_TARGET_COMPS]

    newest = selected[0]["observed_at"] if selected else None
    oldest = selected[-1]["observed_at"] if selected else None
    if newest is not None and newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)

    newest_age_days = None
    if newest is not None:
        newest_age_days = max((as_of - newest).total_seconds(), 0.0) / 86_400.0

    reasons: list[str] = []
    if not selected:
        reasons.append("NO_SOLD_EVIDENCE")
    elif len(selected) < SOLD_EVIDENCE_MIN_COMPS:
        reasons.append("INSUFFICIENT_COMPS")
    if newest_age_days is not None and newest_age_days > freshness_days:
        reasons.append("STALE_NEWEST_COMP")

    prices = [int(item["price_gbp_minor"]) for item in selected]
    source_counts: dict[str, int] = {}
    for item in selected:
        source = str(item.get("source") or "").upper()
        source_counts[source] = source_counts.get(source, 0) + 1

    if not selected:
        status = "EMPTY"
    elif len(selected) < SOLD_EVIDENCE_MIN_COMPS:
        status = "INSUFFICIENT"
    elif newest_age_days is not None and newest_age_days > freshness_days:
        status = "STALE"
    else:
        status = "FRESH"

    return {
        "status": status,
        "refresh_recommended": bool(reasons),
        "refresh_reasons": reasons,
        "available_exact_sold_count": len(ordered),
        "selected_comp_count": len(selected),
        "minimum_comp_count": SOLD_EVIDENCE_MIN_COMPS,
        "target_comp_count": SOLD_EVIDENCE_TARGET_COMPS,
        "target_reached": len(selected) >= SOLD_EVIDENCE_TARGET_COMPS,
        "freshness_days": freshness_days,
        "newest_observation_at": newest,
        "oldest_selected_observation_at": oldest,
        "newest_age_days": round(newest_age_days, 3) if newest_age_days is not None else None,
        "raw_mean_minor": round(mean(prices)) if prices else None,
        "median_minor": round(median(prices)) if prices else None,
        "source_counts": source_counts,
        "selected_comps": [
            {
                "source": item.get("source"),
                "source_record_key": item.get("source_record_key"),
                "observed_at": item.get("observed_at"),
                "price_gbp_minor": int(item["price_gbp_minor"]),
                "shipping_gbp_minor": (
                    int(item["shipping_gbp_minor"])
                    if item.get("shipping_gbp_minor") is not None
                    else None
                ),
                "source_country": item.get("source_country"),
            }
            for item in selected
        ],
    }


async def _policy_row(connection: asyncpg.Connection, owner_id: UUID) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select * from tcg.pricing_policies where owner_id = $1
        """,
        owner_id,
    )
    if row is not None:
        return row
    return await connection.fetchrow(
        """
        insert into tcg.pricing_policies(owner_id)
        values ($1)
        on conflict (owner_id) do update set owner_id = excluded.owner_id
        returning *
        """,
        owner_id,
    )


def _policy_from_row(row: asyncpg.Record) -> PricingPolicy:
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


async def _recalculate_one(connection: asyncpg.Connection, owner_id: UUID, inventory_id: UUID) -> dict:
    item = await connection.fetchrow(
        """
        select
            i.id,
            i.catalogue_id,
            i.condition,
            i.grading_company,
            i.grade,
            i.language,
            i.seal_status,
            i.store_price_minor,
            i.status,
            p.name,
            p.set_name,
            p.card_number
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id = i.catalogue_id
        where i.id = $1 and i.owner_id = $2
        for update of i
        """,
        inventory_id,
        owner_id,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if item["status"] in {"SOLD", "WITHDRAWN"}:
        raise HTTPException(
            status_code=409,
            detail="Sold or withdrawn inventory cannot be repriced",
        )

    rows = await connection.fetch(
        """
        select
            source,
            source_record_key,
            metadata,
            observation_type,
            observed_at,
            price_gbp_minor,
            sample_size,
            evidence_quality,
            condition,
            grading_company,
            grade,
            language,
            seal_status,
            source_country
        from tcg.market_observations
        where catalogue_id = $1
          and source='EBAY' and source_country='GB' and observation_type='SOLD'
          and observed_at between now()-interval '90 days' and now()
        order by observed_at desc
        limit 500
        """,
        item["catalogue_id"],
    )
    # Prefer five exact UK sales. A matched Cardmarket guide is an explicitly
    # labelled, non-publishable fallback when that evidence is unavailable.
    exact = {}
    for row in rows:
        if _same_pricing_identity(dict(row),dict(item)):
            exact.setdefault(_sold_identity_key(dict(row)),row)
    rows = list(exact.values())[:5]
    if len(rows)<5:
        from .cardmarket_valuations import apply_cached_inventory_guide
        snapshot=await apply_cached_inventory_guide(connection,item['id'],owner_id,item['catalogue_id'])
        if snapshot is not None:
            return {'inventory_id':item['id'],'name':item['name'],'set_name':item['set_name'],
                'card_number':item['card_number'],'snapshot':dict(snapshot),'auto_reprice_enabled':False}
        raise HTTPException(status_code=422, detail="Five exact recent eBay UK sold observations or an eligible matched Cardmarket guide are required")

    observations = [
        MarketObservation(
            source=row["source"],
            observation_type=row["observation_type"],
            observed_at=row["observed_at"],
            price_gbp_minor=int(row["price_gbp_minor"]),
            sample_size=int(row["sample_size"]),
            evidence_quality=float(row["evidence_quality"]),
            condition=row["condition"],
            grading_company=row["grading_company"],
            grade=row["grade"],
            language=row["language"],
            seal_status=row["seal_status"],
            source_country=row["source_country"],
        )
        for row in rows
    ]
    target = ComparableTarget(
        condition=item["condition"],
        grading_company=item["grading_company"],
        grade=item["grade"],
        language=item["language"],
        seal_status=item["seal_status"],
    )
    policy_row = await _policy_row(connection, owner_id)
    result = calculate_price(
        observations,
        target=target,
        policy=_policy_from_row(policy_row),
        current_store_price_minor=item["store_price_minor"],
        as_of=datetime.now(timezone.utc),
    )

    evidence = {
        "method": "LIVE_EBAY_MARKET_V1",
        "source_record_keys": [row["source_record_key"] for row in rows],
        "sources": [
            {
                "source": estimate.source,
                "estimate_minor": estimate.estimate_minor,
                "weight": estimate.weight,
                "observation_count": estimate.observation_count,
                "sold_observation_count": estimate.sold_observation_count,
                "freshness": estimate.freshness,
                "evidence_quality": estimate.evidence_quality,
                "newest_observation_at": estimate.newest_observation_at.isoformat(),
            }
            for estimate in result.source_estimates
        ]
    }
    snapshot = await connection.fetchrow(
        """
        insert into tcg.pricing_snapshots(
            inventory_id,
            catalogue_id,
            owner_id,
            market_value_minor,
            recommended_retail_minor,
            quick_sale_minor,
            target_acquisition_minor,
            confidence,
            source_count,
            observation_count,
            sold_observation_count,
            volatility_pct,
            newest_observation_at,
            algorithm_version,
            evidence,
            auto_publish_eligible,
            block_reasons
        ) values (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,$17::jsonb
        )
        returning *
        """,
        item["id"],
        item["catalogue_id"],
        owner_id,
        result.market_value_minor,
        result.recommended_retail_minor,
        result.quick_sale_minor,
        result.target_acquisition_minor,
        result.confidence,
        result.source_count,
        result.observation_count,
        result.sold_observation_count,
        result.volatility_pct,
        result.newest_observation_at,
        result.algorithm_version,
        json.dumps(evidence),
        result.auto_publish_eligible,
        json.dumps(list(result.block_reasons)),
    )
    await connection.execute(
        """
        update tcg.inventory_items
        set
            market_value_minor = $2,
            recommended_retail_minor = $3,
            pricing_updated_at = now(),
            latest_pricing_snapshot_id = $4,
            updated_at = now(),
            version = version + 1
        where id = $1
        """,
        item["id"],
        result.market_value_minor,
        result.recommended_retail_minor,
        snapshot["id"],
    )
    return {
        "inventory_id": item["id"],
        "name": item["name"],
        "set_name": item["set_name"],
        "card_number": item["card_number"],
        "snapshot": dict(snapshot),
        "auto_reprice_enabled": bool(policy_row["auto_reprice_enabled"]),
    }


@router.get("/adapters")
async def pricing_adapters(user: Annotated[AuthenticatedUser, Depends(require_user)]) -> dict:
    return {"items": adapter_availability()}


@router.get("/policy")
async def get_pricing_policy(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        row = await _policy_row(connection, owner["id"])
        return jsonable_encoder(dict(row))


@router.patch("/policy")
async def update_pricing_policy(
    payload: PricingPolicyPatch,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    supplied = payload.model_fields_set - {"version"}
    if not supplied:
        raise HTTPException(status_code=422, detail="At least one pricing policy field is required")
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        current = await _policy_row(connection, owner["id"])
        if int(current["version"]) != payload.version:
            raise HTTPException(status_code=409, detail="Pricing policy changed; refresh and retry")
        values = payload.model_dump(exclude_unset=True)
        values.pop("version", None)
        assignments: list[str] = []
        args: list[object] = [owner["id"], payload.version]
        for field, value in values.items():
            args.append(value)
            assignments.append(f"{field} = ${len(args)}")
        assignments.extend(["version = version + 1", "updated_at = now()"])
        row = await connection.fetchrow(
            f"""
            update tcg.pricing_policies
            set {', '.join(assignments)}
            where owner_id = $1 and version = $2
            returning *
            """,
            *args,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Pricing policy changed; refresh and retry")
        return jsonable_encoder(dict(row))


@router.post("/recalculate/{inventory_id}")
async def recalculate_inventory_price(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        return jsonable_encoder(await _recalculate_one(connection, owner["id"], inventory_id))


@router.post("/recalculate")
async def recalculate_inventory_batch(
    payload: BatchRecalculate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    if len(payload.inventory_ids) != len(set(payload.inventory_ids)):
        raise HTTPException(status_code=422, detail="Inventory IDs must be unique")
    results: list[dict] = []
    failures: list[dict] = []
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        for inventory_id in payload.inventory_ids:
            try:
                results.append(await _recalculate_one(connection, owner["id"], inventory_id))
            except HTTPException as exc:
                failures.append({"inventory_id": str(inventory_id), "status_code": exc.status_code, "detail": exc.detail})
    return jsonable_encoder({"updated": results, "failures": failures})


@router.get("/inventory/{inventory_id}/evidence-status")
async def pricing_evidence_status(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    freshness_days: int = Query(
        default=SOLD_EVIDENCE_DEFAULT_FRESHNESS_DAYS,
        ge=1,
        le=90,
    ),
) -> dict:
    """Read-only status of exact SOLD evidence already stored by Drop Rate."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        item = await connection.fetchrow(
            """
            select
                i.id,
                i.catalogue_id,
                i.inventory_code,
                i.identity_confirmed,
                i.condition,
                i.grading_company,
                i.grade,
                i.language,
                i.seal_status,
                p.name,
                p.set_name,
                p.card_number,
                p.variant
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where i.id=$1 and i.owner_id=$2
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if not item["identity_confirmed"]:
            raise HTTPException(
                status_code=422,
                detail="Canonical card identity must be confirmed before sold-history status can be trusted",
            )

        rows = await connection.fetch(
            """
            select
                source,
                source_record_key,
                observation_type,
                observed_at,
                price_gbp_minor,
                shipping_gbp_minor,
                condition,
                grading_company,
                grade,
                language,
                seal_status,
                source_country,
                metadata
            from tcg.market_observations
            where catalogue_id=$1
              and observation_type='SOLD'
            order by observed_at desc
            limit 500
            """,
            item["catalogue_id"],
        )
        as_of = await connection.fetchval("select clock_timestamp()")

    target = {
        "condition": item["condition"],
        "grading_company": item["grading_company"],
        "grade": item["grade"],
        "language": item["language"],
        "seal_status": item["seal_status"],
    }
    status = summarize_sold_evidence(
        [dict(row) for row in rows],
        target=target,
        as_of=as_of,
        freshness_days=freshness_days,
    )
    return jsonable_encoder(
        {
            "inventory_id": item["id"],
            "inventory_code": item["inventory_code"],
            "catalogue_id": item["catalogue_id"],
            "identity": {
                "name": item["name"],
                "set_name": item["set_name"],
                "card_number": item["card_number"],
                "variant": item["variant"],
                **target,
            },
            **status,
        }
    )


@router.get("/inventory/{inventory_id}/history")
async def pricing_history(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select *
            from tcg.pricing_snapshots
            where inventory_id = $1 and owner_id = $2
            order by calculated_at desc
            limit $3
            """,
            inventory_id,
            owner["id"],
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.get("/inventory")
async def pricing_inventory_overview(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                i.id,
                i.inventory_code,
                i.status,
                i.store_price_minor,
                i.market_value_minor,
                i.recommended_retail_minor,
                i.pricing_updated_at,
                p.name,
                p.set_name,
                p.card_number,
                s.confidence,
                s.source_count,
                s.observation_count,
                s.volatility_pct,
                s.auto_publish_eligible,
                s.block_reasons,
                s.calculated_at
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            left join tcg.pricing_snapshots s on s.id = i.latest_pricing_snapshot_id
            where i.owner_id = $1
            order by i.pricing_updated_at desc nulls last, i.created_at desc
            limit $2 offset $3
            """,
            owner["id"],
            limit,
            offset,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})
