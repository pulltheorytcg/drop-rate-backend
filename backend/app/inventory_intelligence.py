from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .inventory_reference_values import reference_portfolio, reference_totals, reference_top_groups
from .inventory_market_movers import shared_weekly_movers, weekly_change_pct
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


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
    # A real penny movement can round to 0.00%. Keep its direction from the
    # exact monetary difference, including callers without a precomputed delta.
    gainers = sorted(
        (row for row in values if row["change_minor"] > 0),
        key=lambda row: (row["change_pct"], row["change_minor"]),
        reverse=True,
    )[:limit]
    decliners = sorted(
        (row for row in values if row["change_minor"] < 0),
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

        shared = await reference_portfolio(connection, [owner_id])
        refs = reference_totals(shared)
        asking = [item["store_price_minor"] for item in shared if item.get("store_price_minor") is not None]
        totals = {
            "active_inventory_count": len(shared),
            "market_valued_item_count": refs["valued_count"],
            "guide_estimate_count": refs["estimate_count"],
            "store_priced_item_count": len(asking),
            "inventory_market_value_minor": refs["total_minor"],
            "inventory_store_value_minor": sum(asking),
            "valued_pricing_group_count": len(reference_top_groups(shared, limit=len(shared))),
            "valuation_basis": "SHARED_CATALOGUE_V1",
        }
        top_rows = reference_top_groups(shared, top_limit)
        movement = await shared_weekly_movers(connection, shared, window_days=window_days)

    ranked = rank_weekly_movers(movement["movers"], limit=top_limit)
    summary = movement["summary"]
    return jsonable_encoder(
        {
            "window_days": window_days,
            "history_cutoff": summary["as_of"] - timedelta(days=window_days),
            "totals": totals,
            "top_valuable": top_rows,
            "weekly_movers": {
                **summary,
                "gainers": ranked["gainers"],
                "decliners": ranked["decliners"],
                "groups_with_prior_value": summary["comparable_product_count"],
            },
        }
    )
