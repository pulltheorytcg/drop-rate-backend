"""Founder-only oversight. Cross-account access here is strictly read-only."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_platform_admin
from .auth import AuthenticatedUser, require_user
from .db import user_connection

router = APIRouter(prefix="/api/v1/founder/accounts", tags=["founder-accounts"])


@router.get("")
async def accounts(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as conn:
        access = await require_platform_admin(conn)
        rows = await conn.fetch("""
          select o.id,o.display_name,o.owner_type,o.founder_slot,
            coalesce(i.items,0) as inventory_count,coalesce(i.for_sale,0) as for_sale_count,
            i.market_value_minor,coalesce(i.unvalued,0) as unvalued_count,
            coalesce(f.revenue,0) as sales_revenue_minor,
            coalesce(f.refunds,0) as refunds_minor,
            coalesce(f.pending,0) as pending_minor,
            greatest(coalesce(f.available,0)-coalesce(p.reserved,0),0) as available_to_withdraw_minor,
            coalesce(f.paid_out,0) as paid_out_minor,
            coalesce(s.published,0) as shopify_published,coalesce(e.live,0) as ebay_live
          from tcg.owners o
          left join lateral (
            select count(*)::int as items,
              count(*) filter(where sale_intent='FOR_SALE' and status='APPROVED')::int as for_sale,
              sum(market_value_minor) filter(where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')) as market_value_minor,
              count(*) filter(where market_value_minor is null and status in ('DRAFT','INSPECTION','APPROVED','RESERVED'))::int as unvalued
            from tcg.inventory_items where owner_id=o.id
          ) i on true
          left join lateral (
            select sum(amount_minor) filter(where entry_type='SALE_REVENUE') as revenue,
              -sum(amount_minor) filter(where entry_type='REFUND') as refunds,
              sum(amount_minor) filter(where funds_status='PENDING') as pending,
              sum(amount_minor) filter(where funds_status='AVAILABLE') as available,
              -sum(amount_minor) filter(where entry_type='PAYOUT') as paid_out
            from tcg.financial_ledger_entries where owner_id=o.id
          ) f on true
          left join lateral (select sum(amount_minor) as reserved from tcg.payout_requests
            where owner_id=o.id and status in ('REQUESTED','APPROVED')) p on true
          left join lateral (select count(*)::int as published from tcg.shopify_inventory_links
            where owner_id=o.id and sync_state='PUBLISHED' and not test_mode) s on true
          left join lateral (select count(*)::int as live from tcg.ebay_inventory_links
            where owner_id=o.id and state='LIVE') e on true
          where o.active order by o.founder_slot nulls last,o.display_name,o.id
        """)
    return jsonable_encoder({"accounts":[dict(r) for r in rows],"own_owner_id":access["owner_id"],"read_only":True})


@router.get("/inventory")
async def account_inventory(
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
    owner_id: UUID | None = None, search: str = Query(default="",max_length=160),
    limit: int = Query(default=40,ge=1,le=100), offset: int = Query(default=0,ge=0),
):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as conn:
        await require_platform_admin(conn)
        where = "o.active and ($1::uuid is null or i.owner_id=$1) and ($2='' or concat_ws(' ',i.inventory_code,p.name,p.card_number,p.set_name) ilike '%'||$2||'%')"
        total = await conn.fetchval(f"select count(*) from tcg.inventory_items i join tcg.owners o on o.id=i.owner_id join tcg.catalogue_products p on p.id=i.catalogue_id where {where}",owner_id,search.strip())
        rows = await conn.fetch(f"""
          select i.id,i.inventory_code,i.owner_id,o.display_name as owner_name,
            p.name,p.card_number,p.set_name,p.game,i.language,i.condition,i.grading_company,i.grade,
            i.status,i.sale_intent,i.market_value_minor,i.store_price_minor,
            s.sync_state as shopify_state,e.state as ebay_state
          from tcg.inventory_items i join tcg.owners o on o.id=i.owner_id
          join tcg.catalogue_products p on p.id=i.catalogue_id
          left join lateral (select sync_state from tcg.shopify_inventory_links
            where inventory_id=i.id and owner_id=i.owner_id order by linked_at desc limit 1) s on true
          left join lateral (select state from tcg.ebay_inventory_links
            where inventory_id=i.id and owner_id=i.owner_id order by created_at desc limit 1) e on true
          where {where} order by i.updated_at desc,i.id limit $3 offset $4
        """,owner_id,search.strip(),limit,offset)
    return jsonable_encoder({"items":[dict(r) for r in rows],"total":total,"limit":limit,"offset":offset,"read_only":True})


@router.get("/activity")
async def account_activity(
    request: Request,user: Annotated[AuthenticatedUser, Depends(require_user)],
    owner_id: UUID | None = None,
    limit: int = Query(default=40,ge=1,le=100),offset: int = Query(default=0,ge=0),
):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as conn:
        await require_platform_admin(conn)
        sales = await conn.fetch("""
          select oi.id,oi.inventory_id,oi.sale_price_minor,oi.owner_id,
            o.display_name as owner_name,ord.order_number,ord.source,ord.status,ord.created_at
          from tcg.order_items oi join tcg.orders ord on ord.id=oi.order_id
          join tcg.owners o on o.id=oi.owner_id
          where o.active and ($1::uuid is null or oi.owner_id=$1)
          order by ord.created_at desc,oi.id limit $2 offset $3
        """,owner_id,limit,offset)
        payouts = await conn.fetch("""
          select p.payout_code,p.amount_minor,p.currency,p.status,p.created_at,
            p.owner_id,o.display_name as owner_name
          from tcg.payout_requests p join tcg.owners o on o.id=p.owner_id
          where o.active and ($1::uuid is null or p.owner_id=$1)
          order by p.created_at desc,p.id limit $2 offset $3
        """,owner_id,limit,offset)
    return jsonable_encoder({"sales":[dict(r) for r in sales],"payouts":[dict(r) for r in payouts],"read_only":True,"limit":limit,"offset":offset})
