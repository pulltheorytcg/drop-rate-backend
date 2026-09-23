from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection


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


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select id, display_name, owner_type, founder_slot
        from tcg.owners
        where active
        order by founder_slot nulls last
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


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
                coalesce(-sum(amount_minor) filter (where entry_type = 'REFUND'), 0)::bigint as refunds_minor,
                count(distinct order_item_id) filter (where entry_type = 'SALE_REVENUE')::int as sold_items
            from tcg.financial_ledger_entries
            where owner_id = $1
            """,
            owner["id"],
        )
        cogs = await connection.fetchval(
            """
            select coalesce(sum(oi.cost_basis_minor), 0)::bigint
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
        sales_revenue = int(ledger["sales_revenue_minor"] or 0)
        shipping_revenue = int(ledger["shipping_revenue_minor"] or 0)
        platform_fees = int(ledger["platform_fees_minor"] or 0)
        payment_fees = int(ledger["payment_fees_minor"] or 0)
        shipping_cost = int(ledger["shipping_cost_minor"] or 0)
        refunds = int(ledger["refunds_minor"] or 0)
        cost_of_goods = int(cogs or 0)
        gross_profit = sales_revenue - refunds - cost_of_goods
        net_profit = (
            sales_revenue
            + shipping_revenue
            - refunds
            - platform_fees
            - payment_fees
            - shipping_cost
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
            "refunds_minor": refunds,
            "cost_of_goods_minor": cost_of_goods,
            "gross_profit_minor": gross_profit,
            "net_profit_minor": net_profit,
            "sold_items": int(ledger["sold_items"] or 0),
            **balances,
        })


@router.get("/finance/sales")
async def finance_sales(
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
            "select count(*) from tcg.order_items where owner_id = $1",
            owner["id"],
        )
        rows = await connection.fetch(
            """
            select
                oi.id, oi.order_id, oi.inventory_id, i.inventory_code,
                p.game, p.name, p.set_name, p.card_number, p.variant,
                o.source, o.source_reference, o.order_number, o.status as order_status,
                oi.sale_price_minor, oi.discount_minor, oi.net_sale_minor,
                oi.cost_basis_minor, oi.sold_at,
                exists(
                    select 1 from tcg.refund_events r
                    where r.order_item_id = oi.id and r.return_to_stock
                ) as returned_to_stock,
                coalesce(sum(le.amount_minor) filter (where le.entry_type = 'SHIPPING_REVENUE'), 0)::bigint as shipping_revenue_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'PLATFORM_FEE'), 0)::bigint as platform_fee_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'PAYMENT_FEE'), 0)::bigint as payment_fee_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'SHIPPING_COST'), 0)::bigint as shipping_cost_minor,
                coalesce(-sum(le.amount_minor) filter (where le.entry_type = 'REFUND'), 0)::bigint as refund_minor
            from tcg.order_items oi
            join tcg.orders o on o.id = oi.order_id
            join tcg.inventory_items i on i.id = oi.inventory_id
            join tcg.catalogue_products p on p.id = i.catalogue_id
            left join tcg.financial_ledger_entries le on le.order_item_id = oi.id
            where oi.owner_id = $1
            group by oi.id, o.id, i.id, p.id
            order by oi.sold_at desc, oi.id
            limit $2 offset $3
            """,
            owner["id"], limit, offset,
        )
        items = []
        for row in rows:
            item = dict(row)
            effective_cost = 0 if item["returned_to_stock"] else int(item["cost_basis_minor"])
            item["effective_cost_basis_minor"] = effective_cost
            item["profit_minor"] = (
                int(item["net_sale_minor"])
                + int(item["shipping_revenue_minor"])
                - int(item["platform_fee_minor"])
                - int(item["payment_fee_minor"])
                - int(item["shipping_cost_minor"])
                - int(item["refund_minor"])
                - effective_cost
            )
            items.append(item)
        return jsonable_encoder({"total": total, "limit": limit, "offset": offset, "items": items})


@router.post("/finance/manual-sales", status_code=201)
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
