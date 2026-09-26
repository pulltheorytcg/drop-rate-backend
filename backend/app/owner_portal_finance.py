from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .finance import _balance_components


router = APIRouter(prefix="/api/v1/owner/finance", tags=["owner-portal-finance"])


@router.get("/summary")
async def owner_finance_summary(
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
        owner = await connection.fetchrow(
            "select commission_bps from tcg.owners where id=$1",
            owner_id,
        )
        ledger = await connection.fetchrow(
            """
            select
              coalesce(sum(amount_minor)
                filter (where entry_type='SALE_REVENUE'),0)::bigint
                as sales_revenue_minor,
              coalesce(sum(amount_minor)
                filter (where entry_type='SHIPPING_REVENUE'),0)::bigint
                as shipping_revenue_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='PLATFORM_FEE'),0)::bigint
                as platform_fees_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='PAYMENT_FEE'),0)::bigint
                as payment_fees_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='SHIPPING_COST'),0)::bigint
                as shipping_cost_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='FULFILMENT_MATERIAL_COST'),0)::bigint
                as fulfilment_material_cost_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type in ('COMMISSION','COMMISSION_REVERSAL')),0)::bigint
                as commission_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='REFUND'),0)::bigint
                as refunds_minor,
              coalesce(-sum(amount_minor)
                filter (where entry_type='SHIPPING_REFUND'),0)::bigint
                as shipping_refunds_minor,
              coalesce(sum(amount_minor)
                filter (where entry_type='ADJUSTMENT'),0)::bigint
                as adjustments_minor,
              coalesce(sum(amount_minor)
                filter (where entry_type <> 'PAYOUT'),0)::bigint
                as lifetime_owner_proceeds_minor,
              count(distinct order_item_id)
                filter (where entry_type='SALE_REVENUE')::int
                as sold_items
            from tcg.financial_ledger_entries
            where owner_id=$1
            """,
            owner_id,
        )
        reconciliation = await connection.fetchrow(
            """
            select
              count(*) filter (
                where o.source in ('SHOPIFY','EBAY')
                  and (
                    rec.fees_reconciled_at is null
                    or rec.shipping_cost_reconciled_at is null
                  )
              )::int as unreconciled_sales
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            left join tcg.order_item_reconciliations rec
              on rec.order_item_id=oi.id
            where oi.owner_id=$1
            """,
            owner_id,
        )
        balances = await _balance_components(connection, owner_id)

    return jsonable_encoder(
        {
            "currency": "GBP",
            "commission_bps": int(owner["commission_bps"] or 0),
            "sales_revenue_minor": int(ledger["sales_revenue_minor"] or 0),
            "shipping_revenue_minor": int(ledger["shipping_revenue_minor"] or 0),
            "platform_fees_minor": int(ledger["platform_fees_minor"] or 0),
            "payment_fees_minor": int(ledger["payment_fees_minor"] or 0),
            "shipping_cost_minor": int(ledger["shipping_cost_minor"] or 0),
            "fulfilment_material_cost_minor": int(
                ledger["fulfilment_material_cost_minor"] or 0
            ),
            "commission_minor": int(ledger["commission_minor"] or 0),
            "refunds_minor": int(ledger["refunds_minor"] or 0),
            "shipping_refunds_minor": int(ledger["shipping_refunds_minor"] or 0),
            "adjustments_minor": int(ledger["adjustments_minor"] or 0),
            "lifetime_owner_proceeds_minor": int(
                ledger["lifetime_owner_proceeds_minor"] or 0
            ),
            "sold_items": int(ledger["sold_items"] or 0),
            "unreconciled_sales": int(reconciliation["unreconciled_sales"] or 0),
            "financials_complete": int(reconciliation["unreconciled_sales"] or 0) == 0,
            **balances,
        }
    )


@router.get("/sales")
async def owner_sales(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    owner_id = access["owner_id"]

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        total = await connection.fetchval(
            "select count(*)::int from tcg.order_items where owner_id=$1",
            owner_id,
        )
        rows = await connection.fetch(
            """
            select
              oi.id as sale_id,
              i.inventory_code,
              p.game,
              p.name,
              p.set_name,
              p.card_number,
              p.variant,
              o.source,
              o.order_number,
              o.status as order_status,
              oi.sale_price_minor,
              oi.discount_minor,
              oi.net_sale_minor,
              oi.commission_bps_snapshot,
              oi.sold_at,
              coalesce(sum(le.amount_minor)
                filter (where le.entry_type='SHIPPING_REVENUE'),0)::bigint
                as shipping_revenue_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='PLATFORM_FEE'),0)::bigint
                as platform_fee_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='PAYMENT_FEE'),0)::bigint
                as payment_fee_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='SHIPPING_COST'),0)::bigint
                as shipping_cost_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='FULFILMENT_MATERIAL_COST'),0)::bigint
                as fulfilment_material_cost_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type in ('COMMISSION','COMMISSION_REVERSAL')),0)::bigint
                as commission_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='REFUND'),0)::bigint
                as refund_minor,
              coalesce(-sum(le.amount_minor)
                filter (where le.entry_type='SHIPPING_REFUND'),0)::bigint
                as shipping_refund_minor,
              coalesce(sum(le.amount_minor)
                filter (where le.entry_type='ADJUSTMENT'),0)::bigint
                as adjustment_minor,
              coalesce(sum(le.amount_minor),0)::bigint as owner_proceeds_minor,
              coalesce(sum(le.amount_minor)
                filter (where le.funds_status='PENDING'),0)::bigint
                as pending_minor,
              coalesce(sum(le.amount_minor)
                filter (where le.funds_status='AVAILABLE'),0)::bigint
                as available_minor,
              case
                when o.source in ('SHOPIFY','EBAY')
                  then rec.fees_reconciled_at is not null
                else true
              end as fees_reconciled,
              case
                when o.source in ('SHOPIFY','EBAY')
                  then rec.shipping_cost_reconciled_at is not null
                else true
              end as shipping_cost_reconciled
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i on i.id=oi.inventory_id
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.financial_ledger_entries le
              on le.order_item_id=oi.id
            left join tcg.order_item_reconciliations rec
              on rec.order_item_id=oi.id
            where oi.owner_id=$1
            group by oi.id,i.id,p.id,o.id,rec.fees_reconciled_at,
                     rec.shipping_cost_reconciled_at
            order by oi.sold_at desc,oi.id
            limit $2 offset $3
            """,
            owner_id,
            limit,
            offset,
        )

    items = []
    for row in rows:
        item = dict(row)
        item["financials_complete"] = bool(
            item["fees_reconciled"] and item["shipping_cost_reconciled"]
        )
        items.append(item)

    return jsonable_encoder(
        {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    )


@router.get("/settlements")
async def owner_settlements(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    owner_id = access["owner_id"]

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        total = await connection.fetchval(
            "select count(distinct order_id)::int from tcg.order_items where owner_id=$1",
            owner_id,
        )
        rows = await connection.fetch(
            """
            with scoped_orders as (
              select
                oi.order_id,
                count(*)::int as item_count,
                bool_and(
                  case
                    when o.source in ('SHOPIFY','EBAY')
                      then rec.fees_reconciled_at is not null
                    else true
                  end
                ) as fees_reconciled,
                bool_and(
                  case
                    when o.source in ('SHOPIFY','EBAY')
                      then rec.shipping_cost_reconciled_at is not null
                    else true
                  end
                ) as shipping_cost_reconciled
              from tcg.order_items oi
              join tcg.orders o on o.id=oi.order_id
              left join tcg.order_item_reconciliations rec
                on rec.order_item_id=oi.id
              where oi.owner_id=$1
              group by oi.order_id
            ),
            ledger as (
              select
                order_id,
                coalesce(sum(amount_minor)
                  filter (where entry_type='SALE_REVENUE'),0)::bigint
                  as sales_revenue_minor,
                coalesce(sum(amount_minor)
                  filter (where entry_type='SHIPPING_REVENUE'),0)::bigint
                  as shipping_revenue_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='PLATFORM_FEE'),0)::bigint
                  as platform_fees_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='PAYMENT_FEE'),0)::bigint
                  as payment_fees_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='SHIPPING_COST'),0)::bigint
                  as shipping_cost_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='FULFILMENT_MATERIAL_COST'),0)::bigint
                  as fulfilment_material_cost_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type in ('COMMISSION','COMMISSION_REVERSAL')),0)::bigint
                  as commission_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='REFUND'),0)::bigint
                  as refunds_minor,
                coalesce(-sum(amount_minor)
                  filter (where entry_type='SHIPPING_REFUND'),0)::bigint
                  as shipping_refunds_minor,
                coalesce(sum(amount_minor)
                  filter (where entry_type='ADJUSTMENT'),0)::bigint
                  as adjustments_minor,
                coalesce(sum(amount_minor)
                  filter (where entry_type <> 'PAYOUT'),0)::bigint
                  as owner_proceeds_minor,
                coalesce(sum(amount_minor)
                  filter (where funds_status='PENDING'),0)::bigint
                  as pending_minor,
                coalesce(sum(amount_minor)
                  filter (where funds_status='AVAILABLE'),0)::bigint
                  as available_minor
              from tcg.financial_ledger_entries
              where owner_id=$1 and order_id is not null
              group by order_id
            )
            select
              o.order_number,
              o.source,
              o.status as order_status,
              o.currency,
              o.placed_at,
              so.item_count,
              so.fees_reconciled,
              so.shipping_cost_reconciled,
              coalesce(l.sales_revenue_minor,0)::bigint as sales_revenue_minor,
              coalesce(l.shipping_revenue_minor,0)::bigint as shipping_revenue_minor,
              coalesce(l.platform_fees_minor,0)::bigint as platform_fees_minor,
              coalesce(l.payment_fees_minor,0)::bigint as payment_fees_minor,
              coalesce(l.shipping_cost_minor,0)::bigint as shipping_cost_minor,
              coalesce(l.fulfilment_material_cost_minor,0)::bigint
                as fulfilment_material_cost_minor,
              coalesce(l.commission_minor,0)::bigint as commission_minor,
              coalesce(l.refunds_minor,0)::bigint as refunds_minor,
              coalesce(l.shipping_refunds_minor,0)::bigint as shipping_refunds_minor,
              coalesce(l.adjustments_minor,0)::bigint as adjustments_minor,
              coalesce(l.owner_proceeds_minor,0)::bigint as owner_proceeds_minor,
              coalesce(l.pending_minor,0)::bigint as pending_minor,
              coalesce(l.available_minor,0)::bigint as available_minor
            from scoped_orders so
            join tcg.orders o on o.id=so.order_id
            left join ledger l on l.order_id=so.order_id
            order by o.placed_at desc,o.id
            limit $2 offset $3
            """,
            owner_id,
            limit,
            offset,
        )

    items = []
    for row in rows:
        item = dict(row)
        item["financials_complete"] = bool(
            item["fees_reconciled"] and item["shipping_cost_reconciled"]
        )
        items.append(item)

    return jsonable_encoder(
        {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    )


@router.get("/payouts")
async def owner_payout_history(
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
        rows = await connection.fetch(
            """
            select
              payout_code,
              amount_minor,
              currency,
              status,
              request_origin,
              scheduled_for,
              requested_at,
              resolved_at
            from tcg.payout_requests
            where owner_id=$1
            order by requested_at desc
            """,
            owner_id,
        )

    return jsonable_encoder({"items": [dict(row) for row in rows]})
