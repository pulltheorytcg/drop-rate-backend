from __future__ import annotations

import asyncio
import json
import os
from typing import Any

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

    connection = await asyncpg.connect(
        dsn=settings.database_url,
        command_timeout=15,
        server_settings={
            "application_name": "drop-rate-stripe-financial-sandbox-selftest",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "15000",
        },
    )
    try:
        row = await connection.fetchrow(
            """
            select
              current_user::text as database_role,
              tcg.calculate_commission_minor(10000::bigint,1000::integer)::bigint
                as commission_minor,
              (10000::bigint - tcg.calculate_commission_minor(
                 10000::bigint,1000::integer
              ))::bigint as owner_proceeds_minor,
              tcg.calculate_commission_minor(5000::bigint,1000::integer)::bigint
                as half_refund_retained_commission_minor,
              has_table_privilege(current_user,'tcg.owners','select') as owners_select,
              has_table_privilege(current_user,'tcg.owners','insert') as owners_insert,
              has_table_privilege(current_user,'tcg.owners','update') as owners_update,
              has_table_privilege(
                current_user,'tcg.financial_ledger_entries','insert'
              ) as ledger_insert,
              has_table_privilege(current_user,'tcg.order_items','insert') as order_items_insert,
              has_table_privilege(current_user,'tcg.orders','insert') as orders_insert
            """
        )
        if row is None:
            raise RuntimeError("Stripe financial sandbox self-test returned no privilege row")

        _expect(str(row["database_role"]), "tcg_api", "runtime database role")
        _expect(int(row["commission_minor"]), 1000, "£100 at 10% commission")
        _expect(int(row["owner_proceeds_minor"]), 9000, "£100 sale net owner proceeds")
        _expect(
            int(row["half_refund_retained_commission_minor"]),
            500,
            "50% retained commission",
        )
        _expect(bool(row["owners_select"]), True, "owners SELECT privilege")
        _expect(bool(row["owners_insert"]), False, "owners INSERT remains denied")
        _expect(bool(row["owners_update"]), False, "owners UPDATE remains denied")
        _expect(bool(row["ledger_insert"]), True, "ledger INSERT privilege")
        _expect(bool(row["order_items_insert"]), True, "order_items INSERT privilege")
        _expect(bool(row["orders_insert"]), True, "orders INSERT privilege")

        structure = await connection.fetchrow(
            """
            select
              exists(
                select 1
                from pg_catalog.pg_trigger t
                join pg_catalog.pg_class c on c.oid=t.tgrelid
                join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg'
                  and c.relname='order_items'
                  and t.tgname='order_items_commission_snapshot'
                  and not t.tgisinternal
              ) as commission_snapshot_trigger,
              exists(
                select 1
                from pg_catalog.pg_trigger t
                join pg_catalog.pg_class c on c.oid=t.tgrelid
                join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg'
                  and c.relname='financial_ledger_entries'
                  and t.tgname='financial_ledger_commission'
                  and not t.tgisinternal
              ) as commission_ledger_trigger,
              exists(
                select 1
                from pg_catalog.pg_indexes
                where schemaname='tcg'
                  and tablename='financial_ledger_entries'
                  and indexdef ilike '%unique%'
                  and indexdef ilike '%source_key%'
              ) as ledger_source_key_unique,
              (
                select relrowsecurity
                from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg' and c.relname='owners'
              ) as owners_rls,
              (
                select relrowsecurity
                from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg' and c.relname='order_items'
              ) as order_items_rls,
              (
                select relrowsecurity
                from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg' and c.relname='financial_ledger_entries'
              ) as ledger_rls
            """
        )
        if structure is None:
            raise RuntimeError("Stripe financial sandbox self-test returned no structure row")

        for key in (
            "commission_snapshot_trigger",
            "commission_ledger_trigger",
            "ledger_source_key_unique",
            "owners_rls",
            "order_items_rls",
            "ledger_rls",
        ):
            _expect(bool(structure[key]), True, key)

        print(
            json.dumps(
                {
                    "stripe_financial_sandbox_selftest": "PASS",
                    "database_role": str(row["database_role"]),
                    "consignor_commission_bps": 1000,
                    "consignor_commission_minor": int(row["commission_minor"]),
                    "consignor_owner_proceeds_minor": int(row["owner_proceeds_minor"]),
                    "half_refund_retained_commission_minor": int(
                        row["half_refund_retained_commission_minor"]
                    ),
                    "owners_mutation_denied": True,
                    "runtime_finance_write_privileges_present": True,
                    "commission_triggers_present": True,
                    "ledger_idempotency_index_present": True,
                    "rls_present": True,
                    "read_only_probe": True,
                },
                sort_keys=True,
            )
        )
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
