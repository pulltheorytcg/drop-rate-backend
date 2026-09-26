from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import asyncpg

from app.settings import get_settings


def _enabled() -> bool:
    return os.getenv("TCG_STRIPE_SANDBOX_SELFTEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise RuntimeError(
            f"Stripe financial sandbox self-test failed: {label} "
            f"expected={expected!r} actual={actual!r}"
        )


async def _ledger_snapshot(
    connection: asyncpg.Connection,
    *,
    owner_id: object,
    order_item_id: object,
) -> dict[str, int]:
    row = await connection.fetchrow(
        """
        select
            coalesce(sum(amount_minor), 0)::bigint as balance_minor,
            coalesce(sum(amount_minor) filter (where entry_type='SALE_REVENUE'), 0)::bigint
                as sale_revenue_minor,
            coalesce(sum(amount_minor) filter (where entry_type='COMMISSION'), 0)::bigint
                as commission_minor,
            coalesce(sum(amount_minor) filter (where entry_type='REFUND'), 0)::bigint
                as refund_minor,
            coalesce(sum(amount_minor) filter (where entry_type='COMMISSION_REVERSAL'), 0)::bigint
                as commission_reversal_minor,
            count(*) filter (where entry_type='SALE_REVENUE')::bigint as sale_revenue_count,
            count(*) filter (where entry_type='COMMISSION')::bigint as commission_count,
            count(*) filter (where entry_type='REFUND')::bigint as refund_count,
            count(*) filter (where entry_type='COMMISSION_REVERSAL')::bigint
                as commission_reversal_count
        from tcg.financial_ledger_entries
        where owner_id=$1 and order_item_id=$2
        """,
        owner_id,
        order_item_id,
    )
    if row is None:
        raise RuntimeError("Stripe financial sandbox self-test could not read ledger")
    return {key: int(value or 0) for key, value in dict(row).items()}


async def _run() -> None:
    if not _enabled():
        print(json.dumps({"stripe_financial_sandbox_selftest": "SKIPPED"}))
        return

    settings = get_settings()
    secret_key = (settings.stripe_secret_key or "").strip()
    if not secret_key.startswith("sk_test_"):
        raise RuntimeError(
            "Stripe financial sandbox self-test refuses to run without a Stripe test secret key"
        )

    marker = uuid4().hex
    owner_name = f"Sandbox Consignor {marker}"
    identity_key = f"sandbox-financial-{marker}"
    inventory_code = f"INV-SANDBOX-{marker[:16].upper()}"
    source_reference = f"SANDBOX-{marker}"
    sale_source_key = f"sandbox-sale:{marker}"
    refund_one_source_key = f"sandbox-refund-1:{marker}"
    refund_two_source_key = f"sandbox-refund-2:{marker}"

    connection = await asyncpg.connect(
        dsn=settings.database_url,
        command_timeout=15,
        server_settings={
            "application_name": "drop-rate-stripe-financial-sandbox-selftest",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "15000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    result: dict[str, Any] = {}
    transaction = connection.transaction()
    await transaction.start()
    try:
        owner = await connection.fetchrow(
            """
            insert into tcg.owners(display_name, owner_type)
            values($1, 'CONSIGNOR')
            returning id, commission_bps
            """,
            owner_name,
        )
        if owner is None:
            raise RuntimeError("Sandbox consignor insert did not return a row")
        _expect(int(owner["commission_bps"]), 1000, "consignor default commission bps")

        catalogue = await connection.fetchrow(
            """
            insert into tcg.catalogue_products(
                identity_key, product_type, game, name, set_name, language
            )
            values($1, 'CARD', 'POKEMON', 'Sandbox Financial Test Card', 'Sandbox', 'EN')
            returning id
            """,
            identity_key,
        )
        if catalogue is None:
            raise RuntimeError("Sandbox catalogue insert did not return a row")

        inventory = await connection.fetchrow(
            """
            insert into tcg.inventory_items(
                inventory_code, catalogue_id, owner_id, acquisition_cost_minor,
                condition, language, status, notes
            )
            values($1, $2, $3, 0, 'Near Mint', 'EN', 'SOLD',
                   'Rollback-only Stripe financial sandbox self-test')
            returning id
            """,
            inventory_code,
            catalogue["id"],
            owner["id"],
        )
        if inventory is None:
            raise RuntimeError("Sandbox inventory insert did not return a row")

        order = await connection.fetchrow(
            """
            insert into tcg.orders(source, source_reference, order_number, status)
            values('MANUAL', $1, $2, 'PAID')
            returning id
            """,
            source_reference,
            f"TEST-{marker[:10].upper()}",
        )
        if order is None:
            raise RuntimeError("Sandbox order insert did not return a row")

        item = await connection.fetchrow(
            """
            insert into tcg.order_items(
                order_id, inventory_id, owner_id, sale_price_minor, discount_minor,
                net_sale_minor, cost_basis_minor, sold_at
            )
            values($1, $2, $3, 10000, 0, 10000, 0, clock_timestamp())
            returning id, commission_bps_snapshot, commission_minor
            """,
            order["id"],
            inventory["id"],
            owner["id"],
        )
        if item is None:
            raise RuntimeError("Sandbox order item insert did not return a row")
        _expect(int(item["commission_bps_snapshot"]), 1000, "sale commission snapshot bps")
        _expect(int(item["commission_minor"]), 1000, "£100 sale commission minor")

        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type, amount_minor,
                funds_status, source_key, available_at, notes
            )
            values($1, $2, $3, 'SALE_REVENUE', 10000, 'AVAILABLE', $4,
                   clock_timestamp(), 'Rollback-only £100 sandbox sale')
            on conflict(source_key) do nothing
            """,
            owner["id"],
            order["id"],
            item["id"],
            sale_source_key,
        )
        sale = await _ledger_snapshot(
            connection, owner_id=owner["id"], order_item_id=item["id"]
        )
        _expect(sale["sale_revenue_minor"], 10000, "sale revenue")
        _expect(sale["commission_minor"], -1000, "commission ledger deduction")
        _expect(sale["balance_minor"], 9000, "post-commission available balance")
        _expect(sale["sale_revenue_count"], 1, "sale revenue row count")
        _expect(sale["commission_count"], 1, "commission row count")

        # Replay the exact sale source key. The immutable ledger must stay unchanged.
        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type, amount_minor,
                funds_status, source_key, available_at, notes
            )
            values($1, $2, $3, 'SALE_REVENUE', 10000, 'AVAILABLE', $4,
                   clock_timestamp(), 'Duplicate sandbox sale replay')
            on conflict(source_key) do nothing
            """,
            owner["id"],
            order["id"],
            item["id"],
            sale_source_key,
        )
        sale_replay = await _ledger_snapshot(
            connection, owner_id=owner["id"], order_item_id=item["id"]
        )
        _expect(sale_replay, sale, "duplicate sale idempotency")

        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type, amount_minor,
                funds_status, source_key, available_at, notes
            )
            values($1, $2, $3, 'REFUND', -5000, 'AVAILABLE', $4,
                   clock_timestamp(), 'Rollback-only 50% sandbox refund')
            on conflict(source_key) do nothing
            """,
            owner["id"],
            order["id"],
            item["id"],
            refund_one_source_key,
        )
        partial_refund = await _ledger_snapshot(
            connection, owner_id=owner["id"], order_item_id=item["id"]
        )
        _expect(partial_refund["refund_minor"], -5000, "partial refund")
        _expect(
            partial_refund["commission_reversal_minor"],
            500,
            "partial commission reversal",
        )
        _expect(partial_refund["balance_minor"], 4500, "partial-refund owner balance")
        _expect(partial_refund["refund_count"], 1, "partial refund row count")
        _expect(
            partial_refund["commission_reversal_count"],
            1,
            "partial commission reversal row count",
        )

        # Replay the same refund. Neither the refund nor commission reversal may duplicate.
        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type, amount_minor,
                funds_status, source_key, available_at, notes
            )
            values($1, $2, $3, 'REFUND', -5000, 'AVAILABLE', $4,
                   clock_timestamp(), 'Duplicate sandbox refund replay')
            on conflict(source_key) do nothing
            """,
            owner["id"],
            order["id"],
            item["id"],
            refund_one_source_key,
        )
        partial_replay = await _ledger_snapshot(
            connection, owner_id=owner["id"], order_item_id=item["id"]
        )
        _expect(partial_replay, partial_refund, "duplicate refund idempotency")

        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type, amount_minor,
                funds_status, source_key, available_at, notes
            )
            values($1, $2, $3, 'REFUND', -5000, 'AVAILABLE', $4,
                   clock_timestamp(), 'Rollback-only final 50% sandbox refund')
            on conflict(source_key) do nothing
            """,
            owner["id"],
            order["id"],
            item["id"],
            refund_two_source_key,
        )
        full_refund = await _ledger_snapshot(
            connection, owner_id=owner["id"], order_item_id=item["id"]
        )
        _expect(full_refund["refund_minor"], -10000, "full refund")
        _expect(
            full_refund["commission_reversal_minor"],
            1000,
            "full commission reversal",
        )
        _expect(full_refund["balance_minor"], 0, "fully refunded owner balance")
        _expect(full_refund["refund_count"], 2, "full refund row count")
        _expect(
            full_refund["commission_reversal_count"],
            2,
            "full commission reversal row count",
        )

        result = {
            "stripe_financial_sandbox_selftest": "PASS",
            "sale_minor": sale["sale_revenue_minor"],
            "commission_bps": int(item["commission_bps_snapshot"]),
            "commission_minor": -sale["commission_minor"],
            "owner_available_after_sale_minor": sale["balance_minor"],
            "partial_refund_owner_balance_minor": partial_refund["balance_minor"],
            "full_refund_owner_balance_minor": full_refund["balance_minor"],
            "duplicate_sale_idempotent": sale_replay == sale,
            "duplicate_refund_idempotent": partial_replay == partial_refund,
        }
    finally:
        # This probe intentionally exercises the real production schema and trigger graph,
        # but no sandbox owner/order/ledger record is ever committed.
        await transaction.rollback()

    residual = await connection.fetchrow(
        """
        select
            (select count(*) from tcg.owners where display_name=$1)::bigint as owners,
            (select count(*) from tcg.catalogue_products where identity_key=$2)::bigint
                as catalogue,
            (select count(*) from tcg.inventory_items where inventory_code=$3)::bigint
                as inventory,
            (select count(*) from tcg.orders where source='MANUAL' and source_reference=$4)::bigint
                as orders,
            (select count(*) from tcg.financial_ledger_entries where source_key in ($5,$6,$7))::bigint
                as ledger
        """,
        owner_name,
        identity_key,
        inventory_code,
        source_reference,
        sale_source_key,
        refund_one_source_key,
        refund_two_source_key,
    )
    if residual is None:
        raise RuntimeError("Sandbox rollback cleanup check returned no row")
    leftovers = {key: int(value or 0) for key, value in dict(residual).items()}
    if any(leftovers.values()):
        raise RuntimeError(
            f"Stripe financial sandbox self-test rollback left persistent data: {leftovers}"
        )

    result["rollback_cleanup"] = True
    print(json.dumps(result, sort_keys=True))
    await connection.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
