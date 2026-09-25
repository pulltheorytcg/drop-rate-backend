from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


def weekly_change_pct(current_minor: int | None, prior_minor: int | None) -> float | None:
    """Return deterministic percentage change, failing closed without a valid baseline."""
    if current_minor is None or prior_minor is None or prior_minor <= 0:
        return None
    return round(((int(current_minor) - int(prior_minor)) / int(prior_minor)) * 100.0, 2)


def rank_weekly_movers(rows: list[dict[str, Any]], *, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Rank unique pricing identities into weekly gainers and decliners."""
    if limit < 1:
        raise ValueError("limit must be positive")

    deduped: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        key = str(row.get("pricing_key") or "").strip()
        if not key:
            continue
        change_pct = weekly_change_pct(
            row.get("current_market_value_minor"),
            row.get("prior_market_value_minor"),
        )
        if change_pct is None:
            continue
        row["change_pct"] = change_pct
        row["change_minor"] = (
            int(row["current_market_value_minor"]) - int(row["prior_market_value_minor"])
        )

        existing = deduped.get(key)
        if existing is None:
            deduped[key] = row
            continue
        current_at = row.get("current_pricing_updated_at")
        existing_at = existing.get("current_pricing_updated_at")
        if current_at is not None and (existing_at is None or current_at > existing_at):
            deduped[key] = row

    values = list(deduped.values())
    gainers = sorted(
        (row for row in values if row["change_pct"] > 0),
        key=lambda row: (row["change_pct"], row["change_minor"]),
        reverse=True,
    )[:limit]
    decliners = sorted(
        (row for row in values if row["change_pct"] < 0),
        key=lambda row: (row["change_pct"], row["change_minor"]),
    )[:limit]
    return {"gainers": gainers, "decliners": decliners}


@router.get("/intelligence")
async def inventory_intelligence(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    top_limit: int = Query(default=5, ge=1, le=10),
    window_days: int = Query(default=7, ge=1, le=90),
) -> dict:
    """Founder-scoped portfolio value, top-value identities and weekly movers."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]

        totals = await connection.fetchrow(
            """
            select
                count(*)::int as active_inventory_count,
                count(*) filter(where i.market_value_minor is not null)::int
                    as market_valued_item_count,
                count(*) filter(where i.store_price_minor is not null)::int
                    as store_priced_item_count,
                coalesce(sum(i.market_value_minor),0)::bigint
                    as inventory_market_value_minor,
                coalesce(sum(i.store_price_minor),0)::bigint
                    as inventory_store_value_minor,
                count(distinct (
                    i.catalogue_id,
                    i.condition,
                    i.grading_company,
                    i.grade,
                    i.language,
                    i.seal_status
                )) filter(where i.market_value_minor is not null)::int
                    as valued_pricing_group_count
            from tcg.inventory_items i
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
            """,
            owner_id,
        )

        top_rows = await connection.fetch(
            """
            with grouped as (
                select
                    i.catalogue_id,
                    i.condition,
                    i.grading_company,
                    i.grade,
                    i.language,
                    i.seal_status,
                    p.product_type,
                    p.game,
                    p.name,
                    p.set_name,
                    p.card_number,
                    p.variant,
                    p.rarity,
                    count(*)::int as quantity,
                    (array_agg(
                        i.market_value_minor
                        order by i.pricing_updated_at desc nulls last,
                                 i.updated_at desc,
                                 i.id
                    ))[1]::bigint as market_value_minor,
                    sum(i.market_value_minor)::bigint as holding_value_minor
                from tcg.inventory_items i
                join tcg.catalogue_products p on p.id=i.catalogue_id
                where i.owner_id=$1
                  and i.status in ('DRAFT','INSPECTION','APPROVED')
                  and i.market_value_minor is not null
                group by
                    i.catalogue_id,i.condition,i.grading_company,i.grade,
                    i.language,i.seal_status,
                    p.product_type,p.game,p.name,p.set_name,p.card_number,
                    p.variant,p.rarity
            )
            select *
            from grouped
            order by market_value_minor desc, holding_value_minor desc, name, card_number
            limit $2
            """,
            owner_id,
            top_limit,
        )

        mover_rows = await connection.fetch(
            """
            with current_groups as (
                select
                    concat_ws(
                        '|',
                        i.catalogue_id::text,
                        coalesce(i.condition,''),
                        coalesce(i.grading_company,''),
                        coalesce(i.grade,''),
                        coalesce(i.language,''),
                        coalesce(i.seal_status::text,'')
                    ) as pricing_key,
                    array_agg(i.id) as inventory_ids,
                    i.catalogue_id,
                    i.condition,
                    i.grading_company,
                    i.grade,
                    i.language,
                    i.seal_status,
                    p.game,
                    p.name,
                    p.set_name,
                    p.card_number,
                    p.variant,
                    count(*)::int as quantity,
                    (array_agg(
                        i.market_value_minor
                        order by i.pricing_updated_at desc nulls last,
                                 i.updated_at desc,
                                 i.id
                    ))[1]::bigint as current_market_value_minor,
                    max(i.pricing_updated_at) as current_pricing_updated_at
                from tcg.inventory_items i
                join tcg.catalogue_products p on p.id=i.catalogue_id
                where i.owner_id=$1
                  and i.status in ('DRAFT','INSPECTION','APPROVED')
                  and i.market_value_minor is not null
                  and i.market_value_minor > 0
                group by
                    i.catalogue_id,i.condition,i.grading_company,i.grade,
                    i.language,i.seal_status,
                    p.game,p.name,p.set_name,p.card_number,p.variant
            )
            select
                cg.*,
                prior.market_value_minor::bigint as prior_market_value_minor,
                prior.calculated_at as prior_calculated_at
            from current_groups cg
            left join lateral (
                select ps.market_value_minor,ps.calculated_at
                from tcg.pricing_snapshots ps
                where ps.inventory_id = any(cg.inventory_ids)
                  and ps.calculated_at <= clock_timestamp() - make_interval(days => $2)
                  and ps.market_value_minor > 0
                order by ps.calculated_at desc,ps.id desc
                limit 1
            ) prior on true
            """,
            owner_id,
            window_days,
        )

        cutoff = await connection.fetchval(
            "select clock_timestamp() - make_interval(days => $1)",
            window_days,
        )

    mover_dicts = [dict(row) for row in mover_rows]
    ranked = rank_weekly_movers(mover_dicts, limit=top_limit)
    groups_with_prior = sum(
        1
        for row in mover_dicts
        if row.get("prior_market_value_minor") is not None
        and int(row["prior_market_value_minor"]) > 0
    )

    return jsonable_encoder(
        {
            "window_days": window_days,
            "history_cutoff": cutoff,
            "totals": dict(totals),
            "top_valuable": [dict(row) for row in top_rows],
            "weekly_movers": {
                "gainers": ranked["gainers"],
                "decliners": ranked["decliners"],
                "groups_with_prior_value": groups_with_prior,
                "history_ready": groups_with_prior > 0,
            },
        }
    )
