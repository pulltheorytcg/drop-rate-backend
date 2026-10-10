from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Literal, Mapping
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .access_control import require_platform_admin, require_platform_admin_request
from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


router = APIRouter(prefix="/api/v1")


FundsStatus = Literal["PENDING", "AVAILABLE"]


class ManualSaleItem(BaseModel):
    inventory_id: UUID
    sale_price_minor: int = Field(ge=0)
    discount_minor: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_discount(self) -> "ManualSaleItem":
        if self.discount_minor > self.sale_price_minor:
            raise ValueError("discount_minor cannot exceed sale_price_minor")
        return self


class ManualSaleCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=96)
    order_number: str | None = Field(default=None, max_length=96)
    placed_at: datetime | None = None
    funds_status: FundsStatus = "AVAILABLE"
    shipping_revenue_minor: int = Field(default=0, ge=0)
    shipping_cost_minor: int = Field(default=0, ge=0)
    platform_fee_minor: int = Field(default=0, ge=0)
    payment_fee_minor: int = Field(default=0, ge=0)
    items: list[ManualSaleItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_sale(self) -> "ManualSaleCreate":
        self.reference = self.reference.strip()
        self.order_number = self.order_number.strip() if self.order_number else None
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each physical inventory item may appear only once")
        return self


class PayoutRequestCreate(BaseModel):
    amount_minor: int = Field(gt=0)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def normalise(self) -> "PayoutRequestCreate":
        self.notes = self.notes.strip()
        return self


class PayoutCancel(BaseModel):
    version: int = Field(ge=1)


class EbayFeeReconcile(BaseModel):
    amount_minor: int = Field(ge=0)
    reference: str = Field(min_length=1, max_length=96)
    notes: str = Field(default="", max_length=1000)
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def normalise(self) -> "EbayFeeReconcile":
        self.reference = self.reference.strip()
        self.notes = self.notes.strip()
        return self


class ShopifyPostageReconcile(BaseModel):
    amount_minor: int = Field(ge=0)
    reference: str = Field(min_length=1, max_length=96)
    notes: str = Field(default="", max_length=1000)
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def normalise(self) -> "ShopifyPostageReconcile":
        self.reference = self.reference.strip()
        self.notes = self.notes.strip()
        return self


def _shopify_client() -> ShopifyAdminClient:
    settings = get_settings()
    if (
        not settings.shopify_shop_domain
        or not settings.shopify_client_id
        or not settings.shopify_client_secret
    ):
        raise HTTPException(status_code=409, detail="Shopify is not configured")
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


def _shopify_money_minor(value: object, *, field: str) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Shopify returned invalid {field}",
        ) from exc
    if amount < 0:
        raise HTTPException(
            status_code=409,
            detail=f"Shopify returned a negative {field}; manual review required",
        )
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))



UK_BUSINESS_TZ = ZoneInfo("Europe/London")


def _sales_period_bounds(
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime | None, datetime | None]:
    """Convert inclusive UK business dates to an exclusive UTC timestamp range."""
    if start_date is None and end_date is None:
        return None, None
    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=422,
            detail="start_date and end_date must be supplied together",
        )
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date")
    if (end_date - start_date).days > 3660:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 10 years")
    start_local = datetime.combine(start_date, time.min, tzinfo=UK_BUSINESS_TZ)
    end_local = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=UK_BUSINESS_TZ,
    )
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _sales_bucket(start_date: date | None, end_date: date | None) -> str:
    if start_date is None or end_date is None:
        return "month"
    days = (end_date - start_date).days + 1
    if days <= 45:
        return "day"
    if days <= 210:
        return "week"
    return "month"


def _sales_bucket_for_data(
    start_date: date | None,
    end_date: date | None,
    first_sale_date: date | None,
    last_sale_date: date | None,
) -> str:
    """Choose chart granularity from the selected range, or actual data for all-time."""
    if start_date is not None and end_date is not None:
        return _sales_bucket(start_date, end_date)
    if first_sale_date is None or last_sale_date is None:
        return "day"
    return _sales_bucket(first_sale_date, last_sale_date)


def allocate_minor(total: int, weights: list[int]) -> list[int]:
    """Deterministically allocate pennies without losing or creating money."""
    if total < 0:
        raise ValueError("total must be non-negative")
    if not weights:
        return []
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative")
    effective = weights if sum(weights) > 0 else [1] * len(weights)
    denominator = sum(effective)
    base = [(total * weight) // denominator for weight in effective]
    remainders = [(total * weight) % denominator for weight in effective]
    pennies = total - sum(base)
    order = sorted(range(len(base)), key=lambda index: (-remainders[index], index))
    for index in order[:pennies]:
        base[index] += 1
    return base


def _fulfilment_material_allocations(
    items: list[Mapping[str, object]],
    components: list[Mapping[str, object]],
) -> list[int]:
    """Allocate configured material costs without losing or creating pennies."""
    if not items:
        raise ValueError("At least one order item is required")
    if not components:
        raise ValueError("No active fulfilment cost components are configured")

    weights = [int(item["net_sale_minor"]) for item in items]
    allocations = [0] * len(items)
    for component in components:
        unit_cost = component["accounting_unit_cost_minor_gbp"]
        if unit_cost is None:
            raise ValueError("Fulfilment component is missing its GBP accounting cost")
        quantity = Decimal(str(component["quantity"]))
        component_cost = int(
            (Decimal(int(unit_cost)) * quantity).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        basis = str(component["allocation_basis"])
        if basis == "PER_ORDER":
            shared = allocate_minor(component_cost, weights)
            allocations = [
                current + shared[index]
                for index, current in enumerate(allocations)
            ]
        elif basis == "PER_ITEM":
            allocations = [current + component_cost for current in allocations]
        else:
            raise ValueError(f"Unsupported fulfilment allocation basis: {basis}")
    return allocations


def _settlement_reconciliation_state(
    *,
    source: str,
    fees_reconciled: bool,
    shipping_cost_reconciled: bool,
) -> tuple[str, list[str]]:
    if source not in {"SHOPIFY", "EBAY"}:
        return "VERIFIED", []

    blockers: list[str] = []
    if not fees_reconciled:
        blockers.append("Shopify/payment fees" if source == "SHOPIFY" else "eBay fees")
    if not shipping_cost_reconciled:
        blockers.append("postage/fulfilment cost")

    if not blockers:
        return "VERIFIED", []
    if len(blockers) == 2:
        return "WAITING_FEES_AND_POSTAGE", blockers
    if not fees_reconciled:
        return "WAITING_FEES", blockers
    return "WAITING_POSTAGE", blockers


def _settlement_amounts(
    *,
    item_revenue_minor: int,
    shipping_revenue_minor: int,
    item_refunds_minor: int,
    shipping_refunds_minor: int,
    platform_fees_minor: int,
    payment_fees_minor: int,
    shipping_cost_minor: int,
    fulfilment_material_cost_minor: int,
    commission_minor: int,
    adjustments_minor: int,
    effective_cogs_minor: int | None,
) -> dict[str, int | None]:
    gross_proceeds = (
        item_revenue_minor
        + shipping_revenue_minor
        - item_refunds_minor
        - shipping_refunds_minor
    )
    external_deductions = (
        platform_fees_minor
        + payment_fees_minor
        + shipping_cost_minor
        + fulfilment_material_cost_minor
    )
    net_owner_proceeds = (
        gross_proceeds
        - external_deductions
        - commission_minor
        + adjustments_minor
    )
    owner_profit = None if effective_cogs_minor is None else net_owner_proceeds - effective_cogs_minor
    return {
        "gross_proceeds_minor": gross_proceeds,
        "external_deductions_minor": external_deductions,
        "commission_minor": commission_minor,
        "net_owner_proceeds_minor": net_owner_proceeds,
        "owner_profit_minor": owner_profit,
    }


async def _balance_components(connection: asyncpg.Connection, owner_id: UUID) -> dict:
    ledger = await connection.fetchrow(
        """
        select
            coalesce(sum(amount_minor) filter (where funds_status = 'PENDING'), 0)::bigint as pending_minor,
            coalesce(sum(amount_minor) filter (where funds_status = 'AVAILABLE'), 0)::bigint as ledger_available_minor,
            coalesce(-sum(amount_minor) filter (where entry_type = 'PAYOUT'), 0)::bigint as paid_out_minor
        from tcg.financial_ledger_entries
        where owner_id = $1
        """,
        owner_id,
    )
    reserved = await connection.fetchval(
        """
        select coalesce(sum(amount_minor), 0)::bigint
        from tcg.payout_requests
        where owner_id = $1 and status in ('REQUESTED', 'APPROVED')
        """,
        owner_id,
    )
    ledger_available = int(ledger["ledger_available_minor"] or 0)
    reserved_minor = int(reserved or 0)
    return {
        "pending_minor": int(ledger["pending_minor"] or 0),
        "ledger_available_minor": ledger_available,
        "reserved_payout_minor": reserved_minor,
        "available_to_withdraw_minor": max(ledger_available - reserved_minor, 0),
        "paid_out_minor": int(ledger["paid_out_minor"] or 0),
    }


@router.get("/finance/summary")
async def finance_summary(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        ledger = await connection.fetchrow(
            """
            select
                coalesce(sum(amount_minor) filter (where entry_type = 'SALE_REVENUE'), 0)::bigint as sales_revenue_minor,
                coalesce(sum(amount_minor) filter (where entry_type = 'SHIPPING_REVENUE'), 0)::bigint as shipping_revenue_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'PLATFORM_FEE'), 0)::bigint as platform_fees_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'PAYMENT_FEE'), 0)::bigint as payment_fees_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'SHIPPING_COST'), 0)::bigint as shipping_cost_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'FULFILMENT_MATERIAL_COST'), 0)::bigint as fulfilment_material_cost_minor,
                coalesce(-sum(amount_minor) filter (where entry_type in ('COMMISSION','COMMISSION_REVERSAL')), 0)::bigint as commission_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'REFUND'), 0)::bigint as refunds_minor,
                coalesce(-sum(amount_minor) filter (where entry_type = 'SHIPPING_REFUND'), 0)::bigint as shipping_refunds_minor,
                count(distinct order_item_id) filter (where entry_type = 'SALE_REVENUE')::int as sold_items
            from tcg.financial_ledger_entries
            where owner_id = $1
            """,
            owner["id"],
        )
        cogs = await connection.fetchval(
            """
            select case when count(*) filter(where oi.cost_basis_minor is null)>0 then null else coalesce(sum(oi.cost_basis_minor), 0) end::bigint
            from tcg.order_items oi
            where oi.owner_id = $1
              and not exists (
                  select 1
                  from tcg.refund_events r
                  where r.order_item_id = oi.id and r.return_to_stock
              )
            """,
            owner["id"],
        )
        reconciliation = await connection.fetchrow(
            """
            select
              count(*) filter (
                where not exists (
                  select 1
                  from tcg.order_item_reconciliations r
                  where r.order_item_id = oi.id
                    and r.fees_reconciled_at is not null
                )
              )::int as missing_fee_sales,
              count(*) filter (
                where not exists (
                  select 1
                  from tcg.order_item_reconciliations r
                  where r.order_item_id = oi.id
                    and r.shipping_cost_reconciled_at is not null
                )
              )::int as missing_shipping_cost_sales
            from tcg.order_items oi
            join tcg.orders o on o.id = oi.order_id
            where oi.owner_id = $1
              and o.source in ('SHOPIFY','EBAY')
            """,
            owner["id"],
        )
        missing_fee_sales = int(reconciliation["missing_fee_sales"] or 0)
        missing_shipping_cost_sales = int(
            reconciliation["missing_shipping_cost_sales"] or 0
        )
        unreconciled_external_sales = max(
            missing_fee_sales,
            missing_shipping_cost_sales,
        )
        # Keep the original field/variable contract for the Founder Finance UI
        # while extending the underlying completeness check to eBay as well.
        unreconciled_shopify_sales = unreconciled_external_sales
        sales_revenue = int(ledger["sales_revenue_minor"] or 0)
        shipping_revenue = int(ledger["shipping_revenue_minor"] or 0)
        platform_fees = int(ledger["platform_fees_minor"] or 0)
        payment_fees = int(ledger["payment_fees_minor"] or 0)
        shipping_cost = int(ledger["shipping_cost_minor"] or 0)
        fulfilment_material_cost = int(
            ledger["fulfilment_material_cost_minor"] or 0
        )
        commission = int(ledger["commission_minor"] or 0)
        refunds = int(ledger["refunds_minor"] or 0)
        shipping_refunds = int(ledger["shipping_refunds_minor"] or 0)
        cost_of_goods = int(cogs or 0)
        gross_profit = sales_revenue - refunds - cost_of_goods
        net_profit = (
            sales_revenue
            + shipping_revenue
            - refunds
            - shipping_refunds
            - platform_fees
            - payment_fees
            - shipping_cost
            - fulfilment_material_cost
            - commission
            - cost_of_goods
        )
        balances = await _balance_components(connection, owner["id"])
        return jsonable_encoder({
            "owner": dict(owner),
            "currency": "GBP",
            "sales_revenue_minor": sales_revenue,
            "shipping_revenue_minor": shipping_revenue,
            "platform_fees_minor": platform_fees,
            "payment_fees_minor": payment_fees,
            "shipping_cost_minor": shipping_cost,
            "fulfilment_material_cost_minor": fulfilment_material_cost,
            "commission_minor": commission,
            "commission_bps": int(owner["commission_bps"] or 0),
            "refunds_minor": refunds,
            "shipping_refunds_minor": shipping_refunds,
            "cost_of_goods_minor": cost_of_goods if cogs is not None else None,
            "gross_profit_minor": gross_profit if cogs is not None else None,
            "net_profit_minor": net_profit if cogs is not None else None,
            "fees_complete": missing_fee_sales == 0,
            "shipping_cost_complete": missing_shipping_cost_sales == 0,
            "net_profit_complete": unreconciled_shopify_sales == 0 and cogs is not None,
            "unreconciled_external_sales": unreconciled_external_sales,
            "unreconciled_shopify_sales": unreconciled_external_sales,
            "sold_items": int(ledger["sold_items"] or 0),
            **balances,
        })


@router.get("/finance/sales")
async def finance_sales(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> dict:
    range_start, range_end = _sales_period_bounds(start_date, end_date)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        total = await connection.fetchval(
            """
            select count(*)
            from tcg.order_items
            where owner_id=$1
              and ($2::timestamptz is null or sold_at >= $2)
              and ($3::timestamptz is null or sold_at < $3)
            """,
            owner["id"],
            range_start,
            range_end,
        )
        rows = await connection.fetch(
            """
            select
                oi.id, oi.order_id, oi.inventory_id, i.inventory_code,
                p.game, p.name, p.set_name, p.card_number, p.variant,
                o.source, o.source_reference, o.order_number, o.status as order_status,
                oi.sale_price_minor, oi.discount_minor, oi.net_sale_minor,
                oi.commission_bps_snapshot, oi.commission_minor as commission_snapshot_minor,
                oi.cost_basis_minor, oi.sold_at,
                exists(
                    select 1 from tcg.refund_events r
                    where r.order_item_id = oi.id and r.return_to_stock
                ) as returned_to_stock,
                coalesce(sum(le.amount_minor) filter (where le.entry_type = 'SHIPPING_REVENUE'), 0)::bigint as shipping_revenue_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'PLATFORM_FEE'), 0)::bigint as platform_fee_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'PAYMENT_FEE'), 0)::bigint as payment_fee_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'SHIPPING_COST'), 0)::bigint as shipping_cost_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'FULFILMENT_MATERIAL_COST'), 0)::bigint as fulfilment_material_cost_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type in ('COMMISSION','COMMISSION_REVERSAL')), 0)::bigint as commission_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'REFUND'), 0)::bigint as refund_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'SHIPPING_REFUND'), 0)::bigint as shipping_refund_minor,
                (rec.fees_reconciled_at is not null) as fees_reconciled,
                (rec.shipping_cost_reconciled_at is not null) as shipping_cost_reconciled
            from tcg.order_items oi
            join tcg.orders o on o.id = oi.order_id
            join tcg.inventory_items i on i.id = oi.inventory_id
            join tcg.catalogue_products p on p.id = i.catalogue_id
            left join tcg.financial_ledger_entries le on le.order_item_id = oi.id
            left join tcg.order_item_reconciliations rec on rec.order_item_id = oi.id
            where oi.owner_id = $1
              and ($2::timestamptz is null or oi.sold_at >= $2)
              and ($3::timestamptz is null or oi.sold_at < $3)
            group by oi.id, o.id, i.id, p.id, rec.fees_reconciled_at, rec.shipping_cost_reconciled_at
            order by oi.sold_at desc, oi.id
            limit $4 offset $5
            """,
            owner["id"], range_start, range_end, limit, offset,
        )
        items = []
        for row in rows:
            item = dict(row)
            effective_cost = None
            if item["returned_to_stock"] or item["cost_basis_minor"] is not None:
                effective_cost = 0 if item["returned_to_stock"] else int(item["cost_basis_minor"])
            item["effective_cost_basis_minor"] = effective_cost
            item["fees_complete"] = (
                item["source"] not in {"SHOPIFY", "EBAY"} or bool(item["fees_reconciled"])
            )
            item["shipping_cost_complete"] = (
                item["source"] not in {"SHOPIFY", "EBAY"}
                or bool(item["shipping_cost_reconciled"])
            )
            item["profit_complete"] = (
                item["fees_complete"] and item["shipping_cost_complete"] and effective_cost is not None
            )
            item["profit_minor"] = (
                int(item["net_sale_minor"])
                + int(item["shipping_revenue_minor"])
                - int(item["platform_fee_minor"])
                - int(item["payment_fee_minor"])
                - int(item["shipping_cost_minor"])
                - int(item["fulfilment_material_cost_minor"])
                - int(item["commission_minor"])
                - int(item["refund_minor"])
                - int(item["shipping_refund_minor"])
                - (effective_cost or 0)
            ) if effective_cost is not None else None
            items.append(item)
        return jsonable_encoder({
            "total": total,
            "limit": limit,
            "offset": offset,
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
        })


@router.get("/finance/sales-analytics")
async def finance_sales_analytics(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> dict:
    range_start, range_end = _sales_period_bounds(start_date, end_date)

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)

        summary = await connection.fetchrow(
            """
            with scoped_items as (
              select
                oi.id,
                oi.order_id,
                oi.cost_basis_minor,
                oi.sold_at,
                o.source,
                exists(
                  select 1
                  from tcg.refund_events re
                  where re.order_item_id=oi.id and re.return_to_stock
                ) as returned_to_stock
              from tcg.order_items oi
              join tcg.orders o on o.id=oi.order_id
              where oi.owner_id=$1
                and ($2::timestamptz is null or oi.sold_at >= $2)
                and ($3::timestamptz is null or oi.sold_at < $3)
            ),
            scoped_orders as (
              select distinct order_id from scoped_items
            ),
            ledger as (
              select
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='SALE_REVENUE'),0)::bigint
                  as sales_revenue_minor,
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='SHIPPING_REVENUE'),0)::bigint
                  as shipping_revenue_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='REFUND'),0)::bigint
                  as refunds_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='SHIPPING_REFUND'),0)::bigint
                  as shipping_refunds_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='PLATFORM_FEE'),0)::bigint
                  as platform_fees_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='PAYMENT_FEE'),0)::bigint
                  as payment_fees_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='SHIPPING_COST'),0)::bigint
                  as shipping_cost_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type='FULFILMENT_MATERIAL_COST'),0)::bigint
                  as fulfilment_material_cost_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type in ('COMMISSION','COMMISSION_REVERSAL')),0)::bigint
                  as commission_minor,
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='ADJUSTMENT'),0)::bigint
                  as adjustments_minor
              from tcg.financial_ledger_entries le
              where le.owner_id=$1
                and le.order_id in (select order_id from scoped_orders)
            ),
            item_stats as (
              select
                count(*)::int as sold_items,
                count(distinct order_id)::int as orders,
                case when count(*) filter(where not returned_to_stock and cost_basis_minor is null)>0 then null
                else coalesce(sum(case when returned_to_stock then 0 else cost_basis_minor end),0)
                end::bigint as cost_of_goods_minor
              from scoped_items
            ),
            reconciliation as (
              select
                count(*) filter (
                  where si.source in ('SHOPIFY','EBAY')
                    and rec.fees_reconciled_at is null
                )::int as missing_fee_sales,
                count(*) filter (
                  where si.source in ('SHOPIFY','EBAY')
                    and rec.shipping_cost_reconciled_at is null
                )::int as missing_shipping_cost_sales
              from scoped_items si
              left join tcg.order_item_reconciliations rec
                on rec.order_item_id=si.id
            )
            select *
            from ledger cross join item_stats cross join reconciliation
            """,
            owner["id"],
            range_start,
            range_end,
        )

        first_last = await connection.fetchrow(
            """
            select
              min((sold_at at time zone 'Europe/London')::date) as first_sale_date,
              max((sold_at at time zone 'Europe/London')::date) as last_sale_date
            from tcg.order_items
            where owner_id=$1
              and ($2::timestamptz is null or sold_at >= $2)
              and ($3::timestamptz is null or sold_at < $3)
            """,
            owner["id"],
            range_start,
            range_end,
        )

        first_sale_date = first_last["first_sale_date"]
        last_sale_date = first_last["last_sale_date"]
        bucket = _sales_bucket_for_data(
            start_date,
            end_date,
            first_sale_date,
            last_sale_date,
        )

        series = await connection.fetch(
            """
            with scoped_items as (
              select
                oi.id,
                oi.order_id,
                oi.cost_basis_minor,
                oi.sold_at,
                date_trunc($4, oi.sold_at at time zone 'Europe/London')::date
                  as bucket_date,
                exists(
                  select 1
                  from tcg.refund_events re
                  where re.order_item_id=oi.id and re.return_to_stock
                ) as returned_to_stock
              from tcg.order_items oi
              where oi.owner_id=$1
                and ($2::timestamptz is null or oi.sold_at >= $2)
                and ($3::timestamptz is null or oi.sold_at < $3)
            ),
            order_buckets as (
              select order_id, min(bucket_date) as bucket_date
              from scoped_items
              group by order_id
            ),
            ledger_by_bucket as (
              select
                ob.bucket_date,
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='SALE_REVENUE'),0)::bigint
                  as sales_revenue_minor,
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='SHIPPING_REVENUE'),0)::bigint
                  as shipping_revenue_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type in ('REFUND','SHIPPING_REFUND')),0)::bigint
                  as refunds_minor,
                coalesce(-sum(le.amount_minor)
                  filter (where le.entry_type in (
                    'PLATFORM_FEE','PAYMENT_FEE','SHIPPING_COST',
                    'FULFILMENT_MATERIAL_COST','COMMISSION','COMMISSION_REVERSAL'
                  )),0)::bigint as operating_costs_minor,
                coalesce(sum(le.amount_minor)
                  filter (where le.entry_type='ADJUSTMENT'),0)::bigint
                  as adjustments_minor
              from order_buckets ob
              join tcg.financial_ledger_entries le
                on le.order_id=ob.order_id and le.owner_id=$1
              group by ob.bucket_date
            ),
            items_by_bucket as (
              select
                bucket_date,
                count(*)::int as sold_items,
                count(distinct order_id)::int as orders,
                case when count(*) filter(where not returned_to_stock and cost_basis_minor is null)>0 then null
                else coalesce(sum(case when returned_to_stock then 0 else cost_basis_minor end),0)
                end::bigint as cost_of_goods_minor
              from scoped_items
              group by bucket_date
            )
            select
              coalesce(i.bucket_date,l.bucket_date) as bucket_date,
              coalesce(l.sales_revenue_minor,0)::bigint as sales_revenue_minor,
              (
                coalesce(l.sales_revenue_minor,0)
                + coalesce(l.shipping_revenue_minor,0)
                - coalesce(l.refunds_minor,0)
              )::bigint as net_revenue_minor,
              case when i.sold_items>0 and i.cost_of_goods_minor is null then null else (
                coalesce(l.sales_revenue_minor,0)
                + coalesce(l.shipping_revenue_minor,0)
                - coalesce(l.refunds_minor,0)
                - coalesce(l.operating_costs_minor,0)
                - coalesce(i.cost_of_goods_minor,0)
                + coalesce(l.adjustments_minor,0)
              ) end::bigint as profit_minor,
              coalesce(i.orders,0)::int as orders,
              coalesce(i.sold_items,0)::int as sold_items
            from items_by_bucket i
            full join ledger_by_bucket l using(bucket_date)
            order by bucket_date
            """,
            owner["id"],
            range_start,
            range_end,
            bucket,
        )

    sales_revenue = int(summary["sales_revenue_minor"] or 0)
    shipping_revenue = int(summary["shipping_revenue_minor"] or 0)
    refunds = int(summary["refunds_minor"] or 0)
    shipping_refunds = int(summary["shipping_refunds_minor"] or 0)
    platform_fees = int(summary["platform_fees_minor"] or 0)
    payment_fees = int(summary["payment_fees_minor"] or 0)
    shipping_cost = int(summary["shipping_cost_minor"] or 0)
    material_cost = int(summary["fulfilment_material_cost_minor"] or 0)
    commission = int(summary["commission_minor"] or 0)
    adjustments = int(summary["adjustments_minor"] or 0)
    cogs = int(summary["cost_of_goods_minor"] or 0)
    orders = int(summary["orders"] or 0)
    sold_items = int(summary["sold_items"] or 0)
    gross_order_sales = sales_revenue + shipping_revenue
    net_revenue = sales_revenue + shipping_revenue - refunds - shipping_refunds
    net_profit = (
        net_revenue
        - platform_fees
        - payment_fees
        - shipping_cost
        - material_cost
        - commission
        - cogs
        + adjustments
    )
    missing_fees = int(summary["missing_fee_sales"] or 0)
    missing_postage = int(summary["missing_shipping_cost_sales"] or 0)

    return jsonable_encoder({
        "currency": "GBP",
        "business_timezone": "Europe/London",
        "start_date": start_date,
        "end_date": end_date,
        "first_sale_date": first_sale_date,
        "last_sale_date": last_sale_date,
        "bucket": bucket,
        "sales_revenue_minor": sales_revenue,
        "shipping_revenue_minor": shipping_revenue,
        "refunds_minor": refunds,
        "shipping_refunds_minor": shipping_refunds,
        "net_revenue_minor": net_revenue,
        "platform_fees_minor": platform_fees,
        "payment_fees_minor": payment_fees,
        "shipping_cost_minor": shipping_cost,
        "fulfilment_material_cost_minor": material_cost,
        "commission_minor": commission,
        "commission_bps": int(owner["commission_bps"] or 0),
        "adjustments_minor": adjustments,
        "cost_of_goods_minor": cogs if summary["cost_of_goods_minor"] is not None else None,
        "net_profit_minor": net_profit if summary["cost_of_goods_minor"] is not None else None,
        "net_profit_complete": missing_fees == 0 and missing_postage == 0 and summary["cost_of_goods_minor"] is not None,
        "unreconciled_external_sales": max(missing_fees, missing_postage),
        "unreconciled_shopify_sales": max(missing_fees, missing_postage),
        "orders": orders,
        "sold_items": sold_items,
        "average_order_value_minor": round(gross_order_sales / orders) if orders else 0,
        "series": [dict(row) for row in series],
    })


@router.get("/finance/settlements")
async def finance_settlements(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        total = await connection.fetchval(
            """
            select count(distinct oi.order_id)::int
            from tcg.order_items oi
            where oi.owner_id=$1
            """,
            owner["id"],
        )
        rows = await connection.fetch(
            """
            with item_rollup as (
              select
                oi.order_id,
                oi.owner_id,
                count(*)::int as item_count,
                case when count(*) filter(where oi.cost_basis_minor is null and not exists(
                    select 1 from tcg.refund_events r where r.order_item_id=oi.id and r.return_to_stock))>0
                then null else coalesce(
                  sum(
                    case
                      when exists (
                        select 1
                        from tcg.refund_events r
                        where r.order_item_id=oi.id
                          and r.return_to_stock
                      )
                      then 0
                      else oi.cost_basis_minor
                    end
                  ),
                  0
                ) end::bigint as effective_cogs_minor,
                bool_and(rec.fees_reconciled_at is not null) as fees_reconciled,
                bool_and(rec.shipping_cost_reconciled_at is not null)
                  as shipping_cost_reconciled
              from tcg.order_items oi
              left join tcg.order_item_reconciliations rec
                on rec.order_item_id=oi.id
              where oi.owner_id=$1
              group by oi.order_id,oi.owner_id
            ),
            ledger_rollup as (
              select
                le.order_id,
                le.owner_id,
                coalesce(
                  sum(le.amount_minor)
                    filter (where le.entry_type='SALE_REVENUE'),
                  0
                )::bigint as item_revenue_minor,
                coalesce(
                  sum(le.amount_minor)
                    filter (where le.entry_type='SHIPPING_REVENUE'),
                  0
                )::bigint as shipping_revenue_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='REFUND'),
                  0
                )::bigint as item_refunds_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='SHIPPING_REFUND'),
                  0
                )::bigint as shipping_refunds_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='PLATFORM_FEE'),
                  0
                )::bigint as platform_fees_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='PAYMENT_FEE'),
                  0
                )::bigint as payment_fees_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='SHIPPING_COST'),
                  0
                )::bigint as shipping_cost_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type='FULFILMENT_MATERIAL_COST'),
                  0
                )::bigint as fulfilment_material_cost_minor,
                coalesce(
                  -sum(le.amount_minor)
                    filter (where le.entry_type in ('COMMISSION','COMMISSION_REVERSAL')),
                  0
                )::bigint as commission_minor,
                coalesce(
                  sum(le.amount_minor)
                    filter (where le.entry_type='ADJUSTMENT'),
                  0
                )::bigint as adjustments_minor,
                coalesce(
                  sum(le.amount_minor)
                    filter (where le.funds_status='PENDING'),
                  0
                )::bigint as pending_ledger_minor,
                coalesce(
                  sum(le.amount_minor)
                    filter (where le.funds_status='AVAILABLE'),
                  0
                )::bigint as available_ledger_minor
              from tcg.financial_ledger_entries le
              where le.owner_id=$1 and le.order_id is not null
              group by le.order_id,le.owner_id
            )
            select
              o.id as order_id,
              o.source,
              o.source_reference,
              o.order_number,
              o.status as order_status,
              o.currency,
              o.placed_at,
              ir.item_count,
              ir.effective_cogs_minor,
              case
                when o.source in ('SHOPIFY','EBAY') then coalesce(ir.fees_reconciled,false)
                else true
              end as fees_reconciled,
              case
                when o.source in ('SHOPIFY','EBAY')
                  then coalesce(ir.shipping_cost_reconciled,false)
                else true
              end as shipping_cost_reconciled,
              coalesce(lr.item_revenue_minor,0)::bigint as item_revenue_minor,
              coalesce(lr.shipping_revenue_minor,0)::bigint
                as shipping_revenue_minor,
              coalesce(lr.item_refunds_minor,0)::bigint as item_refunds_minor,
              coalesce(lr.shipping_refunds_minor,0)::bigint
                as shipping_refunds_minor,
              coalesce(lr.platform_fees_minor,0)::bigint as platform_fees_minor,
              coalesce(lr.payment_fees_minor,0)::bigint as payment_fees_minor,
              coalesce(lr.shipping_cost_minor,0)::bigint as shipping_cost_minor,
              coalesce(lr.fulfilment_material_cost_minor,0)::bigint
                as fulfilment_material_cost_minor,
              coalesce(lr.commission_minor,0)::bigint as commission_minor,
              coalesce(lr.adjustments_minor,0)::bigint as adjustments_minor,
              coalesce(lr.pending_ledger_minor,0)::bigint as pending_ledger_minor,
              coalesce(lr.available_ledger_minor,0)::bigint
                as available_ledger_minor
            from item_rollup ir
            join tcg.orders o on o.id=ir.order_id
            left join ledger_rollup lr
              on lr.order_id=ir.order_id and lr.owner_id=ir.owner_id
            order by o.placed_at desc,o.id
            limit $2 offset $3
            """,
            owner["id"], limit, offset,
        )

        settlements = []
        for row in rows:
            item = dict(row)
            item_revenue = int(item["item_revenue_minor"] or 0)
            shipping_revenue = int(item["shipping_revenue_minor"] or 0)
            item_refunds = int(item["item_refunds_minor"] or 0)
            shipping_refunds = int(item["shipping_refunds_minor"] or 0)
            platform_fees = int(item["platform_fees_minor"] or 0)
            payment_fees = int(item["payment_fees_minor"] or 0)
            shipping_cost = int(item["shipping_cost_minor"] or 0)
            fulfilment_material_cost = int(
                item["fulfilment_material_cost_minor"] or 0
            )
            commission = int(item["commission_minor"] or 0)
            adjustments = int(item["adjustments_minor"] or 0)
            effective_cogs = int(item["effective_cogs_minor"]) if item["effective_cogs_minor"] is not None else None

            amounts = _settlement_amounts(
                item_revenue_minor=item_revenue,
                shipping_revenue_minor=shipping_revenue,
                item_refunds_minor=item_refunds,
                shipping_refunds_minor=shipping_refunds,
                platform_fees_minor=platform_fees,
                payment_fees_minor=payment_fees,
                shipping_cost_minor=shipping_cost,
                fulfilment_material_cost_minor=fulfilment_material_cost,
                commission_minor=commission,
                adjustments_minor=adjustments,
                effective_cogs_minor=effective_cogs,
            )

            reconciliation_state, blockers = _settlement_reconciliation_state(
                source=str(item["source"]),
                fees_reconciled=bool(item["fees_reconciled"]),
                shipping_cost_reconciled=bool(
                    item["shipping_cost_reconciled"]
                ),
            )
            item.update(amounts)
            item["reconciliation_state"] = reconciliation_state
            item["reconciliation_complete"] = not blockers
            item["blockers"] = blockers
            settlements.append(item)

        return jsonable_encoder({
            "owner": dict(owner),
            "currency": "GBP",
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": settlements,
        })


async def _shopify_fee_reconciliation_context(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    order_id: UUID,
) -> tuple[asyncpg.Record, asyncpg.Record]:
    order = await connection.fetchrow(
        """
        select o.id,o.source,o.source_reference,o.order_number,o.status
        from tcg.orders o
        where o.id=$1
          and exists (
            select 1
            from tcg.order_items oi
            where oi.order_id=o.id and oi.owner_id=$2
          )
        """,
        order_id, owner_id,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["source"] != "SHOPIFY":
        raise HTTPException(
            status_code=422,
            detail="Fee reconciliation is only available for Shopify orders",
        )

    items = await connection.fetch(
        """
        select oi.id,oi.owner_id
        from tcg.order_items oi
        where oi.order_id=$1 and oi.owner_id=$2
        order by oi.id
        """,
        order_id, owner_id,
    )
    if len(items) != 1:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Automatic Shopify fee allocation currently requires "
                    "exactly one visible order item"
                ),
                "item_count": len(items),
            },
        )
    return order, items[0]


def _parse_shopify_fee_transactions(
    transactions: list[dict],
) -> tuple[list[tuple[str, str, int]], list[str]]:
    unsettled = [
        str(tx.get("status") or "")
        for tx in transactions
        if str(tx.get("status") or "") in {
            "PENDING",
            "AWAITING_RESPONSE",
            "UNKNOWN",
        }
    ]
    supported_fee_types = {"processing_fee": "PAYMENT_FEE"}
    fee_rows: list[tuple[str, str, int]] = []
    unknown_fee_types: set[str] = set()

    for transaction in transactions:
        if str(transaction.get("status") or "") != "SUCCESS":
            continue
        transaction_id = str(transaction.get("id") or "").strip()
        fees = transaction.get("fees")
        if not isinstance(fees, list):
            raise HTTPException(
                status_code=502,
                detail="Shopify returned invalid transaction fee data",
            )
        for fee in fees:
            if not isinstance(fee, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Shopify returned invalid transaction fee data",
                )
            fee_type = str(fee.get("type") or "").strip()
            entry_type = supported_fee_types.get(fee_type)
            if entry_type is None:
                unknown_fee_types.add(fee_type or "(blank)")
                continue
            money = fee.get("amount")
            if not isinstance(money, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Shopify transaction fee is missing an amount",
                )
            if str(money.get("currencyCode") or "").upper() != "GBP":
                raise HTTPException(
                    status_code=409,
                    detail="Shopify transaction fee is not denominated in GBP",
                )
            amount_minor = _shopify_money_minor(
                money.get("amount"),
                field="transaction fee",
            )
            if amount_minor == 0:
                continue
            fee_id = str(fee.get("id") or "").strip()
            if not transaction_id or not fee_id:
                raise HTTPException(
                    status_code=502,
                    detail="Shopify transaction fee is missing an ID",
                )
            fee_rows.append(
                (entry_type, f"{transaction_id}:{fee_id}", amount_minor)
            )

    if unknown_fee_types:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Shopify returned an unmapped fee type",
                "fee_types": sorted(unknown_fee_types),
            },
        )
    return fee_rows, sorted(set(unsettled))


async def _apply_shopify_fee_reconciliation(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    order_id: UUID,
    item_id: UUID,
    fee_rows: list[tuple[str, str, int]],
    fees_complete: bool,
) -> tuple[int, int]:
    await connection.execute(
        "select pg_advisory_xact_lock(hashtext($1::text))",
        order_id,
    )
    current = await connection.fetchrow(
        """
        select oi.id
        from tcg.order_items oi
        join tcg.orders o on o.id=oi.order_id
        where oi.id=$1
          and oi.order_id=$2
          and oi.owner_id=$3
          and o.source='SHOPIFY'
        """,
        item_id, order_id, owner_id,
    )
    if current is None:
        raise HTTPException(
            status_code=409,
            detail="Shopify order allocation changed during fee reconciliation",
        )

    recorded_minor = 0
    for entry_type, source_fragment, amount_minor in fee_rows:
        source_key = f"shopify-fee:{source_fragment}:{item_id}"
        result = await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
              owner_id,order_id,order_item_id,entry_type,amount_minor,
              currency,funds_status,source_key,occurred_at,notes
            ) values($1,$2,$3,$4,$5,'GBP','PENDING',$6,clock_timestamp(),$7)
            on conflict(source_key) do nothing
            """,
            owner_id, order_id, item_id, entry_type,
            -amount_minor, source_key,
            "Shopify transaction fee imported from typed Admin API data.",
        )
        if result.endswith("1"):
            recorded_minor += amount_minor

    await connection.execute(
        """
        insert into tcg.order_item_reconciliations(
          order_item_id,order_id,owner_id,
          fees_reconciled_at,fees_source
        ) values(
          $1,$2,$3,
          case when $4 then clock_timestamp() else null end,
          case when $4 then 'SHOPIFY_ORDER_TRANSACTIONS' else null end
        )
        on conflict(order_item_id) do update
        set fees_reconciled_at=
              case when $4 then clock_timestamp() else null end,
            fees_source=
              case when $4 then 'SHOPIFY_ORDER_TRANSACTIONS' else null end,
            updated_at=clock_timestamp(),
            version=tcg.order_item_reconciliations.version+1
        """,
        item_id, order_id, owner_id, fees_complete,
    )

    total_payment_fees = await connection.fetchval(
        """
        select coalesce(-sum(amount_minor),0)::bigint
        from tcg.financial_ledger_entries
        where order_item_id=$1 and entry_type='PAYMENT_FEE'
        """,
        item_id,
    )
    return recorded_minor, int(total_payment_fees or 0)


async def _reconcile_shopify_fees_once(
    *,
    pool: asyncpg.Pool,
    user_id: UUID,
    request_id: str,
    order_id: UUID,
) -> dict:
    async with user_connection(pool, user_id, request_id) as connection:
        owner = await _owner(connection)
        order, item = await _shopify_fee_reconciliation_context(
            connection,
            owner_id=owner["id"],
            order_id=order_id,
        )
        owner_id = owner["id"]
        item_id = item["id"]
        order_number = order["order_number"]
        source_reference = str(order["source_reference"] or "").strip()

    if not source_reference.isdigit():
        raise HTTPException(
            status_code=409,
            detail="Shopify order reference is not a numeric Shopify order ID",
        )
    shopify_order_gid = f"gid://shopify/Order/{source_reference}"
    try:
        transactions = await _shopify_client().get_order_transactions(
            shopify_order_gid
        )
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Shopify fee reconciliation failed",
                "retryable": exc.retryable,
            },
        ) from exc

    fee_rows, unsettled = _parse_shopify_fee_transactions(transactions)
    fees_complete = not unsettled

    async with user_connection(pool, user_id, request_id) as connection:
        current_owner = await _owner(connection)
        if current_owner["id"] != owner_id:
            raise HTTPException(
                status_code=409,
                detail="Owner scope changed during fee reconciliation",
            )
        current_order, current_item = await _shopify_fee_reconciliation_context(
            connection,
            owner_id=owner_id,
            order_id=order_id,
        )
        if current_item["id"] != item_id:
            raise HTTPException(
                status_code=409,
                detail="Shopify order allocation changed during fee reconciliation",
            )
        if str(current_order["source_reference"] or "").strip() != source_reference:
            raise HTTPException(
                status_code=409,
                detail="Shopify order reference changed during fee reconciliation",
            )
        recorded_minor, total_payment_fees = await _apply_shopify_fee_reconciliation(
            connection,
            owner_id=owner_id,
            order_id=order_id,
            item_id=item_id,
            fee_rows=fee_rows,
            fees_complete=fees_complete,
        )

    return jsonable_encoder({
        "order_id": order_id,
        "order_number": order_number,
        "recorded_now_minor": recorded_minor,
        "payment_fees_minor": total_payment_fees,
        "fees_complete": fees_complete,
        "unsettled_transaction_statuses": unsettled,
    })


@router.post("/finance/shopify/orders/{order_id}/reconcile-fees", dependencies=[Depends(require_platform_admin_request)])
async def reconcile_shopify_fees(
    order_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    return await _reconcile_shopify_fees_once(
        pool=request.app.state.db_pool,
        user_id=user.user_id,
        request_id=request.state.request_id,
        order_id=order_id,
    )


@router.post("/finance/shopify/reconcile-pending-fees", dependencies=[Depends(require_platform_admin_request)])
async def reconcile_pending_shopify_fees(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=50),
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        await require_platform_admin(connection)
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select distinct o.id,o.order_number,o.placed_at
            from tcg.orders o
            join tcg.order_items oi
              on oi.order_id=o.id and oi.owner_id=$1
            left join tcg.order_item_reconciliations rec
              on rec.order_item_id=oi.id
            where o.source='SHOPIFY'
              and rec.fees_reconciled_at is null
            order by o.placed_at,o.id
            limit $2
            """,
            owner["id"], limit,
        )

    results: list[dict] = []
    reconciled = 0
    pending = 0
    blocked = 0
    for row in rows:
        try:
            result = await _reconcile_shopify_fees_once(
                pool=request.app.state.db_pool,
                user_id=user.user_id,
                request_id=request.state.request_id,
                order_id=row["id"],
            )
        except HTTPException as exc:
            blocked += 1
            results.append({
                "order_id": row["id"],
                "order_number": row["order_number"],
                "status": "BLOCKED",
                "http_status": exc.status_code,
                "detail": exc.detail,
            })
            continue

        if result["fees_complete"]:
            reconciled += 1
            status = "RECONCILED"
        else:
            pending += 1
            status = "PENDING"
        results.append({
            **result,
            "status": status,
        })

    return jsonable_encoder({
        "considered": len(rows),
        "reconciled": reconciled,
        "pending": pending,
        "blocked": blocked,
        "results": results,
    })


@router.post("/finance/ebay/orders/{order_id}/fees", dependencies=[Depends(require_platform_admin_request)])
async def reconcile_ebay_fees(
    order_id: UUID,
    payload: EbayFeeReconcile,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        await connection.execute(
            "select pg_advisory_xact_lock(hashtext($1::text))",
            order_id,
        )
        rows = await connection.fetch(
            """
            select
              o.source,o.order_number,
              oi.id as order_item_id,oi.net_sale_minor,
              rec.fees_reconciled_at,rec.fees_source
            from tcg.orders o
            join tcg.order_items oi on oi.order_id=o.id
            left join tcg.order_item_reconciliations rec
              on rec.order_item_id=oi.id
            where o.id=$1 and oi.owner_id=$2
            order by oi.id
            for update of oi
            """,
            order_id, owner["id"],
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Order not found")
        if rows[0]["source"] != "EBAY":
            raise HTTPException(
                status_code=422,
                detail="Manual eBay fee reconciliation is only available for eBay orders",
            )

        reconciliation_source = (
            f"MANUAL_EBAY_FEES:{payload.reference}:AMOUNT:{payload.amount_minor}"
        )
        reconciled = [row for row in rows if row["fees_reconciled_at"] is not None]
        if reconciled:
            if (
                len(reconciled) == len(rows)
                and all(row["fees_source"] == reconciliation_source for row in reconciled)
            ):
                total_fees = await connection.fetchval(
                    """
                    select coalesce(-sum(amount_minor),0)::bigint
                    from tcg.financial_ledger_entries
                    where order_id=$1 and owner_id=$2
                      and entry_type='PLATFORM_FEE'
                    """,
                    order_id, owner["id"],
                )
                return jsonable_encoder({
                    "order_id": order_id,
                    "order_number": rows[0]["order_number"],
                    "fees_complete": True,
                    "platform_fees_minor": int(total_fees or 0),
                    "idempotent": True,
                })
            raise HTTPException(
                status_code=409,
                detail="eBay fees were already reconciled with different values",
            )

        allocations = allocate_minor(
            payload.amount_minor,
            [int(row["net_sale_minor"]) for row in rows],
        )
        for index, row in enumerate(rows):
            amount_minor = allocations[index]
            source_key = (
                f"ebay-manual-fee:{order_id}:{row['order_item_id']}:"
                f"{payload.reference}:{payload.amount_minor}"
            )
            if amount_minor:
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,
                      currency,funds_status,source_key,occurred_at,notes
                    ) values($1,$2,$3,'PLATFORM_FEE',$4,'GBP','PENDING',$5,$6,$7)
                    on conflict(source_key) do nothing
                    """,
                    owner["id"], order_id, row["order_item_id"], -amount_minor,
                    source_key, occurred_at,
                    payload.notes or "Founder-verified eBay selling fees.",
                )
            await connection.execute(
                """
                insert into tcg.order_item_reconciliations(
                  order_item_id,order_id,owner_id,fees_reconciled_at,fees_source
                ) values($1,$2,$3,clock_timestamp(),$4)
                on conflict(order_item_id) do update
                set fees_reconciled_at=clock_timestamp(),
                    fees_source=$4,
                    updated_at=clock_timestamp(),
                    version=tcg.order_item_reconciliations.version+1
                """,
                row["order_item_id"], order_id, owner["id"], reconciliation_source,
            )

        total_fees = await connection.fetchval(
            """
            select coalesce(-sum(amount_minor),0)::bigint
            from tcg.financial_ledger_entries
            where order_id=$1 and owner_id=$2 and entry_type='PLATFORM_FEE'
            """,
            order_id, owner["id"],
        )
        return jsonable_encoder({
            "order_id": order_id,
            "order_number": rows[0]["order_number"],
            "fees_complete": True,
            "platform_fees_minor": int(total_fees or 0),
            "idempotent": False,
        })


@router.post("/finance/ebay/orders/{order_id}/postage", dependencies=[Depends(require_platform_admin_request)])
@router.post("/finance/shopify/orders/{order_id}/postage", dependencies=[Depends(require_platform_admin_request)])
async def reconcile_shopify_postage(
    order_id: UUID,
    payload: ShopifyPostageReconcile,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        await connection.execute(
            "select pg_advisory_xact_lock(hashtext($1::text))",
            order_id,
        )
        rows = await connection.fetch(
            """
            select
              o.source,o.order_number,
              oi.id as order_item_id,oi.net_sale_minor,
              p.product_type,i.grading_company,i.grade,
              rec.shipping_cost_reconciled_at,
              rec.shipping_cost_source
            from tcg.orders o
            join tcg.order_items oi on oi.order_id=o.id
            join tcg.inventory_items i on i.id=oi.inventory_id
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.order_item_reconciliations rec
              on rec.order_item_id=oi.id
            where o.id=$1 and oi.owner_id=$2
            order by oi.id
            """,
            order_id, owner["id"],
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Order not found")
        expected_source = (
            "EBAY" if "/finance/ebay/" in request.url.path else "SHOPIFY"
        )
        if rows[0]["source"] != expected_source:
            raise HTTPException(
                status_code=422,
                detail=f"Postage reconciliation path does not match {rows[0]['source']} order",
            )

        profile_keys: list[str] = []
        for row in rows:
            if row["product_type"] != "CARD":
                raise HTTPException(
                    status_code=409,
                    detail="No fulfilment profile is configured for this product type",
                )
            is_graded = bool(
                str(row["grading_company"] or "").strip()
                and str(row["grade"] or "").strip()
            )
            profile_keys.append("GRADED_CARD" if is_graded else "RAW_CARD")
        if len(set(profile_keys)) != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Mixed shipping profiles require an approved fulfilment "
                    "allocation policy"
                ),
            )
        profile_key = profile_keys[0]

        components = await connection.fetch(
            """
            select
              component_key,quantity,accounting_unit_cost_minor_gbp,
              allocation_basis
            from tcg.fulfilment_cost_components
            where owner_id=$1
              and shipping_profile_key=$2
              and active
            order by component_key
            """,
            owner["id"], profile_key,
        )
        try:
            material_allocations = _fulfilment_material_allocations(
                rows,
                components,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        material_total = sum(material_allocations)
        postage_allocations = allocate_minor(
            payload.amount_minor,
            [int(row["net_sale_minor"]) for row in rows],
        )
        reconciliation_source = (
            f"MANUAL_FULFILMENT:{payload.reference}:"
            f"POSTAGE:{payload.amount_minor}:MATERIALS:{material_total}"
        )

        reconciled = [
            row for row in rows
            if row["shipping_cost_reconciled_at"] is not None
        ]
        if reconciled:
            if (
                len(reconciled) == len(rows)
                and all(
                    row["shipping_cost_source"] == reconciliation_source
                    for row in reconciled
                )
            ):
                return jsonable_encoder({
                    "order_id": order_id,
                    "order_number": rows[0]["order_number"],
                    "shipping_cost_minor": payload.amount_minor,
                    "fulfilment_material_cost_minor": material_total,
                    "replayed": True,
                })
            raise HTTPException(
                status_code=409,
                detail=(
                    "Fulfilment cost is already reconciled; use an audited "
                    "adjustment workflow"
                ),
            )

        for index, row in enumerate(rows):
            postage = postage_allocations[index]
            materials = material_allocations[index]
            if postage:
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,
                      currency,funds_status,source_key,occurred_at,notes
                    ) values($1,$2,$3,'SHIPPING_COST',$4,'GBP','PENDING',$5,$6,$7)
                    on conflict(source_key) do nothing
                    """,
                    owner["id"], order_id, row["order_item_id"], -postage,
                    f"postage:{payload.reference}:{row['order_item_id']}",
                    occurred_at,
                    payload.notes or "Actual Royal Mail postage cost.",
                )
            if materials:
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,
                      currency,funds_status,source_key,occurred_at,notes
                    ) values(
                      $1,$2,$3,'FULFILMENT_MATERIAL_COST',$4,
                      'GBP','PENDING',$5,$6,$7
                    )
                    on conflict(source_key) do nothing
                    """,
                    owner["id"], order_id, row["order_item_id"], -materials,
                    (
                        f"fulfilment-material:{payload.reference}:"
                        f"{row['order_item_id']}"
                    ),
                    occurred_at,
                    f"Configured {profile_key} fulfilment materials.",
                )
            await connection.execute(
                """
                insert into tcg.order_item_reconciliations(
                  order_item_id,order_id,owner_id,
                  shipping_cost_reconciled_at,shipping_cost_source
                ) values($1,$2,$3,clock_timestamp(),$4)
                on conflict(order_item_id) do update
                set shipping_cost_reconciled_at=clock_timestamp(),
                    shipping_cost_source=$4,
                    updated_at=clock_timestamp(),
                    version=tcg.order_item_reconciliations.version+1
                """,
                row["order_item_id"], order_id, owner["id"],
                reconciliation_source,
            )

        return jsonable_encoder({
            "order_id": order_id,
            "order_number": rows[0]["order_number"],
            "shipping_cost_minor": payload.amount_minor,
            "fulfilment_material_cost_minor": material_total,
            "replayed": False,
        })


@router.post("/finance/manual-sales", status_code=201, dependencies=[Depends(require_platform_admin_request)])
async def create_manual_sale(
    payload: ManualSaleCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    placed_at = payload.placed_at or datetime.now(timezone.utc)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            "select id from tcg.orders where source = 'MANUAL' and source_reference = $1",
            payload.reference,
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="A manual sale already exists with this reference")

        inventory_ids = [item.inventory_id for item in payload.items]
        rows = await connection.fetch(
            """
            select id, inventory_code, owner_id, acquisition_cost_minor, status, version
            from tcg.inventory_items
            where owner_id = $1 and id = any($2::uuid[])
            order by id
            for update
            """,
            owner["id"], inventory_ids,
        )
        if len(rows) != len(inventory_ids):
            raise HTTPException(status_code=404, detail="One or more inventory items were not found")
        by_id = {row["id"]: row for row in rows}
        not_approved = [
            by_id[item.inventory_id]["inventory_code"]
            for item in payload.items
            if by_id[item.inventory_id]["status"] != "APPROVED"
        ]
        if not_approved:
            raise HTTPException(status_code=422, detail={
                "message": "Only APPROVED physical inventory can be sold",
                "inventory_codes": not_approved,
            })
        missing_cost = [
            by_id[item.inventory_id]["inventory_code"]
            for item in payload.items
            if by_id[item.inventory_id]["acquisition_cost_minor"] is None
        ]
        if missing_cost:
            raise HTTPException(status_code=422, detail={
                "message": "Sale requires a known acquisition cost snapshot",
                "inventory_codes": missing_cost,
            })

        order_id = uuid4()
        await connection.execute(
            """
            insert into tcg.orders(id, source, source_reference, order_number, currency, status, placed_at)
            values ($1, 'MANUAL', $2, $3, 'GBP', 'PAID', $4)
            """,
            order_id, payload.reference, payload.order_number, placed_at,
        )

        weights = [item.sale_price_minor - item.discount_minor for item in payload.items]
        shipping_revenue = allocate_minor(payload.shipping_revenue_minor, weights)
        shipping_cost = allocate_minor(payload.shipping_cost_minor, weights)
        platform_fees = allocate_minor(payload.platform_fee_minor, weights)
        payment_fees = allocate_minor(payload.payment_fee_minor, weights)

        created_items = []
        for index, sale_item in enumerate(payload.items):
            inventory = by_id[sale_item.inventory_id]
            order_item_id = uuid4()
            net_sale = sale_item.sale_price_minor - sale_item.discount_minor
            await connection.execute(
                """
                insert into tcg.order_items(
                    id, order_id, inventory_id, owner_id,
                    sale_price_minor, discount_minor, cost_basis_minor, sold_at
                ) values ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                order_item_id, order_id, sale_item.inventory_id, owner["id"],
                sale_item.sale_price_minor, sale_item.discount_minor,
                inventory["acquisition_cost_minor"], placed_at,
            )

            components = [
                ("SALE_REVENUE", net_sale),
                ("SHIPPING_REVENUE", shipping_revenue[index]),
                ("PLATFORM_FEE", -platform_fees[index]),
                ("PAYMENT_FEE", -payment_fees[index]),
                ("SHIPPING_COST", -shipping_cost[index]),
            ]
            for entry_type, amount in components:
                if amount == 0:
                    continue
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                        owner_id, order_id, order_item_id, entry_type,
                        amount_minor, currency, funds_status, source_key,
                        occurred_at, available_at
                    ) values ($1, $2, $3, $4, $5, 'GBP', $6, $7, $8,
                        case when $6 = 'AVAILABLE' then $8 else null end)
                    """,
                    owner["id"], order_id, order_item_id, entry_type, amount,
                    payload.funds_status,
                    f"manual:{order_id}:{order_item_id}:{entry_type}",
                    placed_at,
                )

            sold = await connection.fetchrow(
                """
                update tcg.inventory_items
                set status = 'SOLD', version = version + 1, updated_at = now()
                where id = $1 and owner_id = $2 and status = 'APPROVED'
                returning id, inventory_code, status, version
                """,
                sale_item.inventory_id, owner["id"],
            )
            if sold is None:
                raise HTTPException(status_code=409, detail="Inventory changed while recording the sale")
            created_items.append({
                "order_item_id": order_item_id,
                "inventory": dict(sold),
                "net_sale_minor": net_sale,
                "cost_basis_minor": inventory["acquisition_cost_minor"],
            })

        return jsonable_encoder({
            "order_id": order_id,
            "source": "MANUAL",
            "source_reference": payload.reference,
            "order_number": payload.order_number,
            "status": "PAID",
            "placed_at": placed_at,
            "items": created_items,
        })


@router.get("/finance/payouts")
async def list_payouts(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select id, payout_code, amount_minor, currency, status,
                   request_origin, schedule_cycle_key, scheduled_for,
                   requested_at, resolved_at, notes, version, created_at, updated_at
            from tcg.payout_requests
            where owner_id = $1
            order by requested_at desc
            """,
            owner["id"],
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/finance/payouts", status_code=201)
async def request_payout(
    payload: PayoutRequestCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        await connection.fetchrow("select id from tcg.owners where id = $1 for update", owner["id"])
        balances = await _balance_components(connection, owner["id"])
        available = balances["available_to_withdraw_minor"]
        if payload.amount_minor > available:
            raise HTTPException(status_code=422, detail={
                "message": "Payout request exceeds available balance",
                "available_to_withdraw_minor": available,
            })
        payout_id = uuid4()
        payout_code = f"PAY-{datetime.now(timezone.utc).year}-{payout_id.hex[:8].upper()}"
        row = await connection.fetchrow(
            """
            insert into tcg.payout_requests(
                id, owner_id, payout_code, amount_minor, currency, status, notes
            ) values ($1, $2, $3, $4, 'GBP', 'REQUESTED', $5)
            returning *
            """,
            payout_id, owner["id"], payout_code, payload.amount_minor, payload.notes,
        )
        return jsonable_encoder({"payout": dict(row), "balance": await _balance_components(connection, owner["id"])})


@router.post("/finance/payouts/{payout_id}/cancel")
async def cancel_payout(
    payout_id: UUID,
    payload: PayoutCancel,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            """
            update tcg.payout_requests
            set status = 'CANCELLED', resolved_at = now(),
                version = version + 1, updated_at = now()
            where id = $1 and owner_id = $2 and version = $3 and status = 'REQUESTED'
            returning *
            """,
            payout_id, owner["id"], payload.version,
        )
        if row is None:
            current = await connection.fetchrow(
                "select status, version from tcg.payout_requests where id = $1 and owner_id = $2",
                payout_id, owner["id"],
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Payout request not found")
            raise HTTPException(status_code=409, detail={
                "message": "Payout request cannot be cancelled in its current state",
                "status": current["status"],
                "current_version": current["version"],
            })
        return jsonable_encoder({"payout": dict(row), "balance": await _balance_components(connection, owner["id"])})
