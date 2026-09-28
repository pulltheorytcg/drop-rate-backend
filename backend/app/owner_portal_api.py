from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .brands import brand_sql
from .db import user_connection
from .physical_state import validate_physical_state
from .pricing import _recalculate_one
from .settings import get_settings


router = APIRouter(prefix="/api/v1/owner", tags=["owner-portal"])
BRAND_SQL = brand_sql("p")
VISIBLE_STATUSES = ("DRAFT", "INSPECTION", "APPROVED", "RESERVED", "SOLD", "WITHDRAWN")
OWNER_SCAN_SOURCE = "OWNER_SCAN"


class OwnerRecognitionIntakeRequest(BaseModel):
    recognition_run_id: UUID
    selected_catalogue_id: UUID
    condition: str | None = Field(default=None, max_length=80)
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_physical_details(self) -> "OwnerRecognitionIntakeRequest":
        self.condition = self.condition.strip() if self.condition else None
        self.grading_company = self.grading_company.strip() if self.grading_company else None
        self.grade = self.grade.strip() if self.grade else None
        self.certificate_number = self.certificate_number.strip() if self.certificate_number else None
        self.language = self.language.strip() if self.language else None

        if (self.grading_company is None) != (self.grade is None):
            raise ValueError("grading_company and grade must both be set or both cleared")
        if self.certificate_number and not self.grading_company:
            raise ValueError("certificate_number requires grading_company and grade")
        if self.condition is None and self.grading_company is None:
            raise ValueError("Choose a raw-card condition or provide grading company and grade")
        return self


def _owner_scan_payload_hash(payload: OwnerRecognitionIntakeRequest) -> str:
    canonical = payload.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _owner_scan_inventory_payload(row: object, catalogue: object, *, replayed: bool, valuation: dict | None = None, valuation_error: str | None = None) -> dict:
    inventory = dict(row)
    catalogue_row = dict(catalogue)
    recommended = inventory.get("recommended_retail_minor")
    store_price = inventory.get("store_price_minor")
    has_valuation = (
        valuation is not None
        or inventory.get("market_value_minor") is not None
        or recommended is not None
        or store_price is not None
    )
    return {
        "inventory": {
            "id": inventory.get("id"),
            "inventory_code": inventory.get("inventory_code"),
            "catalogue_id": inventory.get("catalogue_id"),
            "status": inventory.get("status"),
            "condition": inventory.get("condition"),
            "grading_company": inventory.get("grading_company"),
            "grade": inventory.get("grade"),
            "certificate_number": inventory.get("certificate_number"),
            "language": inventory.get("language"),
            "identity_confirmed": bool(inventory.get("identity_confirmed")),
            "market_value_minor": inventory.get("market_value_minor"),
            "recommended_retail_minor": recommended,
            "store_price_minor": store_price,
            "store_value_minor": store_price if store_price is not None else recommended,
            "pricing_updated_at": inventory.get("pricing_updated_at"),
            "created_at": inventory.get("created_at"),
            "updated_at": inventory.get("updated_at"),
        },
        "catalogue": {
            "id": catalogue_row.get("id"),
            "product_type": catalogue_row.get("product_type"),
            "game": catalogue_row.get("game"),
            "name": catalogue_row.get("name"),
            "set_name": catalogue_row.get("set_name"),
            "card_number": catalogue_row.get("card_number"),
            "variant": catalogue_row.get("variant"),
            "rarity": catalogue_row.get("rarity"),
            "language": catalogue_row.get("language"),
        },
        "identity_status": "SELLER_CONFIRMED_PENDING_DROP_RATE_VERIFICATION",
        "valuation": {
            "status": "CALCULATED" if has_valuation else "UNAVAILABLE",
            "snapshot": valuation.get("snapshot") if valuation is not None else None,
            "detail": valuation_error,
        },
        "replayed": replayed,
    }


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
                ),0)::bigint as active_store_price_minor,
                coalesce(sum(coalesce(store_price_minor,recommended_retail_minor)) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_store_value_minor
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


@router.get("/insights")
async def owner_insights(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
) -> dict:
    """Owner-scoped portfolio insights using persisted pricing snapshots only."""

    owner_id = access["owner_id"]
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        top_valued = await connection.fetch(
            """
            select
                i.id as inventory_id,
                i.inventory_code,
                i.status,
                i.condition,
                i.grading_company,
                i.grade,
                coalesce(i.language,p.language) as language,
                i.market_value_minor,
                coalesce(i.store_price_minor,i.recommended_retail_minor)
                    as store_value_minor,
                i.pricing_updated_at,
                p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        (m.scope='INVENTORY_ITEM' and m.inventory_id=i.id)
                        or (
                            m.scope='CANONICAL_CARD'
                            and m.inventory_id is null
                            and m.catalogue_id=i.catalogue_id
                        )
                    )
                      and m.side='FRONT'
                      and m.media_kind='IMAGE'
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by
                      (m.inventory_id=i.id) desc,
                      m.approved_at desc nulls last,
                      m.created_at desc,
                      m.id
                    limit 1
                ) as image_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
              and i.market_value_minor is not null
            order by i.market_value_minor desc,i.pricing_updated_at desc nulls last,i.id
            limit 6
            """,
            owner_id,
        )

        movers = await connection.fetch(
            """
            with latest as (
                select distinct on (ps.inventory_id)
                    ps.inventory_id,
                    ps.market_value_minor as current_value_minor,
                    ps.calculated_at as current_at
                from tcg.pricing_snapshots ps
                join tcg.inventory_items i on i.id=ps.inventory_id
                where ps.owner_id=$1
                  and i.owner_id=$1
                  and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                order by ps.inventory_id,ps.calculated_at desc,ps.id desc
            ),
            compared as (
                select
                    latest.inventory_id,
                    latest.current_value_minor,
                    latest.current_at,
                    baseline.market_value_minor as baseline_value_minor,
                    baseline.calculated_at as baseline_at
                from latest
                join lateral (
                    select ps.market_value_minor,ps.calculated_at
                    from tcg.pricing_snapshots ps
                    where ps.owner_id=$1
                      and ps.inventory_id=latest.inventory_id
                      and ps.calculated_at <= latest.current_at - interval '6 days'
                      and ps.calculated_at >= latest.current_at - interval '14 days'
                    order by ps.calculated_at desc,ps.id desc
                    limit 1
                ) baseline on true
                where baseline.market_value_minor > 0
            )
            select
                i.id as inventory_id,
                i.inventory_code,
                i.status,
                i.condition,
                i.grading_company,
                i.grade,
                coalesce(i.language,p.language) as language,
                p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
                compared.current_value_minor,
                compared.baseline_value_minor,
                compared.current_value_minor-compared.baseline_value_minor
                    as change_minor,
                round(
                    ((compared.current_value_minor-compared.baseline_value_minor)::numeric
                    * 100) / compared.baseline_value_minor,
                    2
                ) as change_pct,
                compared.current_at,
                compared.baseline_at,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        (m.scope='INVENTORY_ITEM' and m.inventory_id=i.id)
                        or (
                            m.scope='CANONICAL_CARD'
                            and m.inventory_id is null
                            and m.catalogue_id=i.catalogue_id
                        )
                    )
                      and m.side='FRONT'
                      and m.media_kind='IMAGE'
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by
                      (m.inventory_id=i.id) desc,
                      m.approved_at desc nulls last,
                      m.created_at desc,
                      m.id
                    limit 1
                ) as image_url
            from compared
            join tcg.inventory_items i on i.id=compared.inventory_id and i.owner_id=$1
            join tcg.catalogue_products p on p.id=i.catalogue_id
            order by abs(
                ((compared.current_value_minor-compared.baseline_value_minor)::numeric
                * 100) / compared.baseline_value_minor
            ) desc,
            compared.current_value_minor desc,
            i.id
            limit 6
            """,
            owner_id,
        )

    return jsonable_encoder(
        {
            "top_valued": [dict(row) for row in top_valued],
            "weekly_movers": [dict(row) for row in movers],
            "weekly_window_days": 7,
        }
    )


@router.get("/channels")
async def owner_channels(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    search: str | None = Query(default=None, max_length=160),
    channel: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=60, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Owner-scoped sales-channel state. Postgres remains the inventory source of truth."""

    owner_id = access["owner_id"]
    query = (search or "").strip()
    selected_channel = (channel or "ALL").strip().upper()
    if selected_channel not in {"ALL", "SHOPIFY", "EBAY"}:
        raise HTTPException(status_code=422, detail="Unsupported channel filter")

    params: list[object] = [owner_id]
    filters = ["i.owner_id=$1"]
    if query:
        params.append(f"%{query}%")
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
    if selected_channel == "SHOPIFY":
        filters.append("shopify.sync_state is not null")
    elif selected_channel == "EBAY":
        filters.append("ebay.state is not null")
    where = " and ".join(filters)

    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        shopify_counts = await connection.fetch(
            """
            select sync_state as state,count(*)::int as count
            from tcg.shopify_inventory_links
            where owner_id=$1
            group by sync_state
            order by sync_state
            """,
            owner_id,
        )
        ebay_counts = await connection.fetch(
            """
            select state,count(*)::int as count
            from tcg.ebay_inventory_links
            where owner_id=$1
            group by state
            order by state
            """,
            owner_id,
        )
        ebay_connection = await connection.fetchrow(
            """
            select status,marketplace_id,connected_at,last_verified_at,last_error_code
            from tcg.ebay_seller_connections
            where owner_id=$1
            order by connected_at desc,id desc
            limit 1
            """,
            owner_id,
        )
        total = await connection.fetchval(
            f"""
            select count(*)::int
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join lateral (
                select l.sync_state
                from tcg.shopify_inventory_links l
                where l.owner_id=$1 and l.inventory_id=i.id
                order by l.linked_at desc,l.id desc
                limit 1
            ) shopify on true
            left join lateral (
                select l.state
                from tcg.ebay_inventory_links l
                where l.owner_id=$1 and l.inventory_id=i.id
                order by l.created_at desc,l.id desc
                limit 1
            ) ebay on true
            where ${where}
              and (shopify.sync_state is not null or ebay.state is not null)
            """,
            *params,
        )
        page_params = [*params, limit, offset]
        rows = await connection.fetch(
            f"""
            select
                i.id as inventory_id,
                i.inventory_code,
                i.status as inventory_status,
                i.market_value_minor,
                coalesce(i.store_price_minor,i.recommended_retail_minor)
                    as store_value_minor,
                p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
                coalesce(i.language,p.language) as language,
                shopify.sync_state as shopify_state,
                shopify.synced_price_minor as shopify_price_minor,
                shopify.last_synced_at as shopify_last_synced_at,
                shopify.test_mode as shopify_test_mode,
                ebay.state as ebay_state,
                ebay.listed_price_minor as ebay_price_minor,
                ebay.last_verified_at as ebay_last_verified_at,
                ebay.last_error_code as ebay_last_error_code,
                ebay.listing_id as ebay_listing_id,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        (m.scope='INVENTORY_ITEM' and m.inventory_id=i.id)
                        or (
                            m.scope='CANONICAL_CARD'
                            and m.inventory_id is null
                            and m.catalogue_id=i.catalogue_id
                        )
                    )
                      and m.side='FRONT'
                      and m.media_kind='IMAGE'
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by
                      (m.inventory_id=i.id) desc,
                      m.approved_at desc nulls last,
                      m.created_at desc,
                      m.id
                    limit 1
                ) as image_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join lateral (
                select
                    l.sync_state,l.synced_price_minor,l.last_synced_at,l.test_mode
                from tcg.shopify_inventory_links l
                where l.owner_id=$1 and l.inventory_id=i.id
                order by l.linked_at desc,l.id desc
                limit 1
            ) shopify on true
            left join lateral (
                select
                    l.state,l.listed_price_minor,l.last_verified_at,
                    l.last_error_code,l.listing_id
                from tcg.ebay_inventory_links l
                where l.owner_id=$1 and l.inventory_id=i.id
                order by l.created_at desc,l.id desc
                limit 1
            ) ebay on true
            where ${where}
              and (shopify.sync_state is not null or ebay.state is not null)
            order by greatest(
                coalesce(shopify.last_synced_at,'epoch'::timestamptz),
                coalesce(ebay.last_verified_at,'epoch'::timestamptz)
            ) desc,
            i.inventory_code
            limit ${len(page_params)-1} offset ${len(page_params)}
            """,
            *page_params,
        )

    shopify_configured = bool(
        settings.shopify_shop_domain
        and settings.shopify_client_id
        and settings.shopify_client_secret
    )
    ebay_data = dict(ebay_connection) if ebay_connection is not None else None
    return jsonable_encoder(
        {
            "channels": [
                {
                    "code": "SHOPIFY",
                    "label": "Shopify",
                    "available": True,
                    "connected": shopify_configured,
                    "connection_status": (
                        "PLATFORM_MANAGED" if shopify_configured else "NOT_CONFIGURED"
                    ),
                    "states": [dict(row) for row in shopify_counts],
                },
                {
                    "code": "EBAY",
                    "label": "eBay",
                    "available": True,
                    "connected": bool(
                        ebay_data
                        and ebay_data.get("status") in {"CONNECTED", "READY"}
                    ),
                    "connection_status": (
                        ebay_data.get("status") if ebay_data else "NOT_CONNECTED"
                    ),
                    "marketplace_id": (
                        ebay_data.get("marketplace_id") if ebay_data else None
                    ),
                    "last_verified_at": (
                        ebay_data.get("last_verified_at") if ebay_data else None
                    ),
                    "last_error_code": (
                        ebay_data.get("last_error_code") if ebay_data else None
                    ),
                    "states": [dict(row) for row in ebay_counts],
                },
                {
                    "code": "WHATNOT",
                    "label": "Whatnot",
                    "available": False,
                    "connected": False,
                    "connection_status": "PLANNED",
                    "states": [],
                },
            ],
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
            "source_of_truth": "DROP_RATE",
        }
    )


@router.get("/catalogue-search")
async def owner_catalogue_search(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    q: str = Query(min_length=2, max_length=80),
    limit: int = Query(default=12, ge=1, le=30),
) -> dict:
    """Search safe canonical card identity for seller recognition corrections."""

    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search needs at least 2 characters")
    normalised = "".join(character for character in query.upper() if character.isalnum())

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select
                p.id,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language,
                pr.system_code,
                value.market_value_minor,
                value.recommended_retail_minor,
                value.pricing_updated_at,
                value.basis_condition,
                value.basis_language,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where m.catalogue_id=p.id
                      and m.scope='CANONICAL_CARD'
                      and m.side='FRONT'
                      and m.media_kind='IMAGE'
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by m.approved_at desc nulls last,m.created_at desc,m.id
                    limit 1
                ) as image_url
            from tcg.catalogue_products p
            join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
            left join lateral tcg.recognition_catalogue_reference_value(
                p.id,
                nullif(p.language,'')
            ) value on true
            where p.product_type='CARD'
              and (
                p.card_number ilike '%'||$1||'%'
                or p.name ilike '%'||$1||'%'
                or p.set_name ilike '%'||$1||'%'
                or upper(regexp_replace(coalesce(p.card_number,''),'[^A-Za-z0-9]','','g'))
                   = $2
              )
            order by
              case
                when $2 <> '' and upper(regexp_replace(coalesce(p.card_number,''),'[^A-Za-z0-9]','','g'))=$2 then 0
                when lower(coalesce(p.card_number,''))=lower($1) then 1
                when lower(coalesce(p.name,''))=lower($1) then 2
                when p.card_number ilike $1||'%' then 3
                else 4
              end,
              p.game,p.set_name,p.card_number,p.name,p.id
            limit $3
            """,
            query,
            normalised,
            limit,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows], "query": query})


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
                i.recommended_retail_minor,
                i.pricing_updated_at,
                i.created_at,
                i.updated_at,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        (m.scope='INVENTORY_ITEM' and m.inventory_id=i.id)
                        or (
                            m.scope='CANONICAL_CARD'
                            and m.inventory_id is null
                            and m.catalogue_id=i.catalogue_id
                        )
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


@router.post("/recognition-intake", status_code=201)
async def owner_recognition_intake(
    payload: OwnerRecognitionIntakeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
) -> dict:
    """Create restricted seller-owned DRAFT inventory from a human-confirmed scan."""

    try:
        request_key = UUID(idempotency_key.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Idempotency-Key must be a UUID") from exc

    owner_id = UUID(str(access["owner_id"]))
    payload_hash = _owner_scan_payload_hash(payload)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        existing = await connection.fetchrow(
            """
            select i.*
            from tcg.inventory_items i
            where i.owner_id=$1 and i.intake_request_key=$2
            """,
            owner_id,
            request_key,
        )
        if existing is not None:
            source_record = existing["source_record"] or {}
            if isinstance(source_record, str):
                try:
                    source_record = json.loads(source_record)
                except json.JSONDecodeError:
                    source_record = {}
            if (
                not isinstance(source_record, dict)
                or source_record.get("source") != OWNER_SCAN_SOURCE
                or source_record.get("payload_hash") != payload_hash
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used for a different seller intake",
                )
            catalogue = await connection.fetchrow(
                "select * from tcg.catalogue_products where id=$1",
                existing["catalogue_id"],
            )
            if catalogue is None:
                raise HTTPException(status_code=409, detail="Seller intake catalogue is missing")
            return jsonable_encoder(
                _owner_scan_inventory_payload(existing, catalogue, replayed=True)
            )

        run = await connection.fetchrow(
            """
            select
                r.id,r.status,r.decision,r.top_catalogue_id,
                c.id as candidate_id,c.catalogue_id,c.hard_rejected
            from tcg.recognition_runs r
            left join tcg.recognition_candidates c
              on c.run_id=r.id and c.catalogue_id=$3
            where r.id=$1
              and r.owner_id=$2
            order by c.rank nulls last
            limit 1
            """,
            payload.recognition_run_id,
            owner_id,
            payload.selected_catalogue_id,
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail="Recognition run was not found for this seller",
            )
        if run["status"] not in {"EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH"}:
            raise HTTPException(status_code=409, detail="Recognition run is not ready for confirmation")
        if run["candidate_id"] is not None and run["hard_rejected"]:
            raise HTTPException(status_code=422, detail="A rejected recognition candidate cannot be added")

        feedback = await connection.fetchrow(
            """
            select outcome,selected_catalogue_id
            from tcg.recognition_feedback
            where run_id=$1 and owner_id=$2
            order by created_at desc,id desc
            limit 1
            """,
            payload.recognition_run_id,
            owner_id,
        )
        if (
            feedback is None
            or feedback["outcome"] not in {
                "CONFIRMED_TOP",
                "CORRECTED_TO_CANDIDATE",
                "CORRECTED_BY_SEARCH",
            }
            or feedback["selected_catalogue_id"] != payload.selected_catalogue_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Confirm or correct the recognition result before adding it to inventory",
            )
        if feedback["outcome"] != "CORRECTED_BY_SEARCH" and run["candidate_id"] is None:
            raise HTTPException(
                status_code=409,
                detail="Confirmed recognition candidate is no longer available",
            )

        catalogue = await connection.fetchrow(
            "select * from tcg.catalogue_products where id=$1",
            payload.selected_catalogue_id,
        )
        if catalogue is None:
            raise HTTPException(status_code=404, detail="Catalogue product not found")
        if catalogue["product_type"] != "CARD":
            raise HTTPException(status_code=422, detail="Seller scan intake currently supports cards only")

        try:
            validate_physical_state(
                product_type=catalogue["product_type"],
                condition=payload.condition,
                seal_status=None,
                grading_company=payload.grading_company,
                grade=payload.grade,
                certificate_number=payload.certificate_number,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        inventory_id = uuid4()
        inventory_code = f"INV-{inventory_id.hex.upper()}"
        physical_language = payload.language or catalogue["language"]
        source_record = {
            "source": OWNER_SCAN_SOURCE,
            "recognition_run_id": str(payload.recognition_run_id),
            "selected_catalogue_id": str(payload.selected_catalogue_id),
            "payload_hash": payload_hash,
            "seller_confirmed": True,
            "confirmation_source": feedback["outcome"],
        }

        inventory = await connection.fetchrow(
            """
            insert into tcg.inventory_items(
                id,inventory_code,catalogue_id,owner_id,
                condition,grading_company,grade,certificate_number,language,
                identity_confirmed,status,intake_request_key,source_record,sale_intent
            ) values(
                $1,$2,$3,$4,
                $5,$6,$7,$8,$9,
                false,'DRAFT',$10,$11::jsonb,'FOR_SALE'
            )
            on conflict (intake_request_key) do nothing
            returning *
            """,
            inventory_id,
            inventory_code,
            payload.selected_catalogue_id,
            owner_id,
            payload.condition,
            payload.grading_company,
            payload.grade,
            payload.certificate_number,
            physical_language,
            request_key,
            json.dumps(source_record),
        )
        if inventory is None:
            raise HTTPException(
                status_code=409,
                detail="Seller intake conflicted; refresh inventory before retrying",
            )

        valuation: dict | None = None
        valuation_error: str | None = None
        try:
            valuation = await _recalculate_one(connection, owner_id, inventory_id)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            valuation_error = str(exc.detail)

        inventory = await connection.fetchrow(
            "select * from tcg.inventory_items where id=$1 and owner_id=$2",
            inventory_id,
            owner_id,
        )
        if inventory is None:
            raise HTTPException(status_code=409, detail="Seller inventory creation could not be verified")

        return jsonable_encoder(
            _owner_scan_inventory_payload(
                inventory,
                catalogue,
                replayed=False,
                valuation=valuation,
                valuation_error=valuation_error,
            )
        )
