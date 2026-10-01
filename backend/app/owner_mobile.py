"""Read-only mobile browsing, with the same restricted Seller Hub boundary."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection

router = APIRouter(prefix="/api/v1/owner/mobile", tags=["owner-mobile"])


def catalogue_filters(query: str, game: str, language: str) -> tuple[str, list[str]]:
    filters = ["p.product_type='CARD'"]
    values: list[str] = []
    if query.strip():
        # Treat user input literally, including SQL wildcard characters.
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.append(f"%{escaped}%")
        n = len(values)
        filters.append(f"(p.name ilike ${n} or p.card_number ilike ${n} or p.set_name ilike ${n})")
    if game.strip():
        values.append(game.strip())
        filters.append(f"p.game=${len(values)}")
    if language.strip():
        values.append(language.strip())
        filters.append(f"p.language=${len(values)}")
    return " and ".join(filters), values


@router.get("/games")
async def games(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch("""
            select game,count(*)::int as card_count from tcg.catalogue_products
            where product_type='CARD' and nullif(game,'') is not null
            group by game order by game
        """)
    return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.get("/catalogue")
async def catalogue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    q: str = Query(default="", max_length=80),
    game: str = Query(default="", max_length=100),
    language: str = Query(default="", max_length=80),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=30, ge=1, le=50),
) -> dict:
    where, values = catalogue_filters(q, game, language)
    params = [*values, limit + 1, offset]
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch(f"""
            select p.id,p.name,p.game,p.set_name,p.card_number,p.variant,p.language,
                value.market_value_minor,value.recommended_retail_minor,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where m.catalogue_id=p.id and m.inventory_id is null
                      and m.scope='CANONICAL_CARD' and m.side='FRONT' and m.media_kind='IMAGE'
                      and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED' and m.source_status='ACTIVE'
                      and m.revoked_at is null
                    order by m.approved_at desc nulls last,m.id limit 1
                ) as image_url
            from tcg.catalogue_products p
            left join lateral tcg.recognition_catalogue_reference_value(p.id,nullif(p.language,'')) value on true
            where {where}
            order by p.game,p.set_name,p.card_number,p.name,p.id
            limit ${len(params)-1} offset ${len(params)}
        """, *params)
    return jsonable_encoder({"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit})
