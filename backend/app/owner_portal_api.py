from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .brands import brand_sql
from .db import user_connection


router = APIRouter(prefix="/api/v1/owner", tags=["owner-portal"])
BRAND_SQL = brand_sql("p")
VISIBLE_STATUSES = ("DRAFT", "INSPECTION", "APPROVED", "RESERVED", "SOLD", "WITHDRAWN")


@router.get("/overview")
async def owner_overview(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
) -> dict:
    owner_id = access["owner_id"]
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        summary = await connection.fetchrow(
            """
            select
                count(*)::int as total_inventory_count,
                count(*) filter (where status='DRAFT')::int as draft_count,
                count(*) filter (where status='INSPECTION')::int as inspection_count,
                count(*) filter (where status='APPROVED')::int as approved_count,
                count(*) filter (where status='RESERVED')::int as reserved_count,
                count(*) filter (where status='SOLD')::int as sold_count,
                count(*) filter (where status='WITHDRAWN')::int as withdrawn_count,
                coalesce(sum(market_value_minor) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_market_value_minor,
                coalesce(sum(store_price_minor) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_store_price_minor
            from tcg.inventory_items
            where owner_id=$1
            """,
            owner_id,
        )

    return jsonable_encoder(
        {
            "owner": {
                "display_name": access["display_name"],
                "owner_type": access["owner_type"],
            },
            "summary": dict(summary),
        }
    )


@router.get("/inventory")
async def owner_inventory(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    search: str | None = Query(default=None, max_length=160),
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    owner_id = access["owner_id"]
    search_value = (search or "").strip()
    status_value = (status or "").strip().upper()

    params: list[object] = [owner_id]
    filters = ["i.owner_id=$1"]

    if search_value:
        params.append(f"%{search_value}%")
        idx = len(params)
        filters.append(
            f"""(
                i.inventory_code ilike ${idx}
                or p.name ilike ${idx}
                or p.set_name ilike ${idx}
                or coalesce(p.card_number,'') ilike ${idx}
                or p.game ilike ${idx}
            )"""
        )

    if status_value:
        if status_value not in VISIBLE_STATUSES:
            filters.append("false")
        else:
            params.append(status_value)
            filters.append(f"i.status=${len(params)}")

    where = " and ".join(filters)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        total = await connection.fetchval(
            f"""
            select count(*)::int
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where {where}
            """,
            *params,
        )

        page_params = [*params, limit, offset]
        rows = await connection.fetch(
            f"""
            select
                i.inventory_code,
                p.product_type,
                p.game,
                {BRAND_SQL} as brand,
                p.name,
                p.set_name,
                p.card_number,
                p.variant,
                p.rarity,
                coalesce(i.language,p.language) as language,
                i.condition,
                i.grading_company,
                i.grade,
                i.status,
                i.market_value_minor,
                i.store_price_minor,
                i.pricing_updated_at,
                i.created_at,
                i.updated_at,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        m.inventory_id=i.id
                        or (m.inventory_id is null and m.catalogue_id=i.catalogue_id)
                    )
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by
                      (m.inventory_id=i.id) desc,
                      (m.side='FRONT') desc,
                      m.approved_at desc nulls last,
                      m.created_at desc
                    limit 1
                ) as image_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where {where}
            order by i.updated_at desc,i.inventory_code
            limit ${len(page_params)-1} offset ${len(page_params)}
            """,
            *page_params,
        )

    return jsonable_encoder(
        {
            "owner": {
                "display_name": access["display_name"],
                "owner_type": access["owner_type"],
            },
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }
    )
