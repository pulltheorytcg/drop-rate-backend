"""Fail-closed migration coverage gate for the complete Supabase -> R2/D1 exit.

Read-only: inventories table names, estimated row counts and relation sizes.
Never exports customer/card/financial rows, credentials or auth session tokens.
A complete *register* is NOT a successful data migration or cutover.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from uuid import UUID

REGISTER = Path("docs/CLOUDFLARE_FULL_EXIT_TABLE_REGISTER_20261106.json")
FORMAT = "drop-rate-cloudflare-full-exit-table-register-v1"
SCHEMAS = {"tcg": 107, "tcg_private": 6, "auth": 27, "storage": 8}
DESTINATIONS = {
    "catalogue": "R2_SOURCE_AND_D1_INDEX",
    "market_current": "R2_EVIDENCE_AND_D1_ELIGIBLE_PRICE",
    "market_asking": "R2_ASKING_ONLY_AND_D1_NON_MARKET_EVIDENCE",
    "market_policy": "D1_OPERATIONAL_PRICING_RULES_R2_BACKUP",
    "market_history": "R2_APPEND_ONLY_AND_D1_PROVENANCE_INDEX",
    "media": "R2_PRIVATE_MEDIA_AND_D1_RIGHTS_INDEX",
    "owners_inventory": "D1_SINGLE_OPERATIONAL_DATABASE_R2_BACKUP",
    "orders_finance": "D1_SINGLE_OPERATIONAL_DATABASE_R2_BACKUP",
    "audit_controls": "D1_ACTION_STATE_AND_R2_IMMUTABLE_AUDIT",
    "recognition": "R2_EVIDENCE_AND_D1_REVIEW_METADATA",
    "marketing": "D1_AUTOMATION_STATE_AND_R2_ARCHIVE",
    "private_publication": "R2_IMMUTABLE_MANIFEST_AND_D1_PRIVATE_POINTER",
    "identity_provider": "EXTERNAL_IDENTITY_MIGRATION_NO_SESSION_TOKEN_COPY",
    "media_registry": "R2_OBJECTS_AND_D1_RIGHTS_METADATA_ONLY",
}
SCHEMA_CATEGORY = {
    "tcg_private": "private_publication",
    "auth": "identity_provider",
    "storage": "media_registry",
}
CORE_TABLES = {
    ("tcg", "reference_cards"): "catalogue",
    ("tcg", "reference_market_prices"): "market_current",
    ("tcg", "reference_catalogue_prices"): "market_current",
    ("tcg", "reference_market_history"): "market_history",
    ("tcg", "reference_asking_prices"): "market_asking",
    ("tcg", "pricing_policies"): "market_policy",
    ("tcg", "reference_image_mirrors"): "media",
    ("tcg", "inventory_items"): "owners_inventory",
    ("tcg", "owner_memberships"): "owners_inventory",
    ("tcg", "owners"): "owners_inventory",
    ("tcg", "orders"): "orders_finance",
    ("tcg", "order_items"): "orders_finance",
    ("tcg", "financial_ledger_entries"): "orders_finance",
    ("tcg", "refund_events"): "orders_finance",
    ("tcg", "shopify_webhook_events"): "orders_finance",
    ("tcg", "audit_events"): "audit_controls",
    ("tcg", "media_assets"): "media",
    ("auth", "users"): "identity_provider",
    ("auth", "refresh_tokens"): "identity_provider",
    ("storage", "objects"): "media_registry",
}

# Restrict the input to PG metadata; record values are NEVER queried.
LIVE_SQL = """SELECT n.nspname AS schema_name,
 c.relname AS table_name,
 pg_total_relation_size(c.oid) AS bytes,
 greatest(c.reltuples,0)::bigint AS estimated_rows
 FROM pg_class c
 JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('tcg','tcg_private','auth','storage')
   AND c.relkind IN ('r','p')
 ORDER BY n.nspname,c.relname"""


class MigrationGuard(ValueError):
    """Fail-closed state: do not proceed to cutover."""


def _unique_relations(records: list[dict], *, current: bool) -> set[tuple[str, str]]:
    if not isinstance(records, list):
        raise MigrationGuard("Expected an inventory list")
    keys = set()
    for item in records:
        if not isinstance(item, dict):
            raise MigrationGuard("Unexpected inventory item")
        schema = item.get("schema_name" if current else "schema")
        table = item.get("table_name" if current else "table")
        if not all(isinstance(x, str) and re.fullmatch(r"[a-z_][a-z_0-9]*", x)
                   for x in (schema, table)):
            raise MigrationGuard("Unsafe or missing relation name")
        key = (schema, table)
        if key in keys:
            raise MigrationGuard("Duplicate schema/table")
        keys.add(key)
    return keys


def validate_register(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise MigrationGuard("Incorrect exit manifest format")
    if data.get("source_project_ref") != "ozrxenrdladkooixutmm":
        raise MigrationGuard("Wrong Supabase project")
    if data.get("source_table_count") != 148 or data.get("table_count_by_schema") != SCHEMAS:
        raise MigrationGuard("Incomplete full-exit source register")
    rows = data.get("tables")
    keys = _unique_relations(rows, current=False)
    counted = Counter(row["schema"] for row in rows)
    if len(keys) != 148 or dict(counted) != SCHEMAS:
        raise MigrationGuard("Source table coverage changed")
    for row in rows:
        schema, category = row["schema"], row.get("category")
        if category not in DESTINATIONS or row.get("target") != DESTINATIONS[category]:
            raise MigrationGuard("Missing or invalid target mapping")
        if schema in SCHEMA_CATEGORY and category != SCHEMA_CATEGORY[schema]:
            raise MigrationGuard("Auth/private/storage relation crossed a boundary")
        if schema == "tcg" and category in SCHEMA_CATEGORY.values():
            raise MigrationGuard("Application relation incorrectly routed")
        if (type(row.get("bytes")) is not int or row["bytes"] < 0 or
                type(row.get("estimated_rows")) is not int or row["estimated_rows"] < 0):
            raise MigrationGuard("Invalid relation measurement")
    for key, category in CORE_TABLES.items():
        matching = [row for row in rows if (row["schema"], row["table"]) == key]
        if len(matching) != 1 or matching[0]["category"] != category:
            raise MigrationGuard("Critical money, auth, media or catalogue route changed")
    return {
        "state": "FULL_EXIT_SOURCE_INVENTORY_VALIDATED_NOT_MIGRATED",
        "source_relation_count": len(keys),
        "tables_by_schema": dict(counted),
        "tables_by_route": dict(sorted(Counter(row["category"] for row in rows).items())),
        "source_size_bytes_for_included_relations": sum(row["bytes"] for row in rows),
        "production_cutover_authorized": False,
        "r2_data_export_completed_by_this_tool": False,
        "d1_data_import_completed_by_this_tool": False,
        "auth_migration_completed_by_this_tool": False,
        "financial_ledger_migration_completed_by_this_tool": False,
    }


def assert_current_matches(current: list[dict], recorded: dict) -> None:
    """Compare full live catalogues, including newly added tables (no silent omission)."""
    live_keys = _unique_relations(current, current=True)
    recorded_keys = _unique_relations(recorded["tables"], current=False)
    if live_keys != recorded_keys:
        missing = len(recorded_keys - live_keys)
        new = len(live_keys - recorded_keys)
        raise MigrationGuard(f"Supabase schema drift: {new} new, {missing} absent tables")
    for row in current:
        if (type(row.get("bytes")) is not int or row["bytes"] < 0 or
                type(row.get("estimated_rows")) is not int or row["estimated_rows"] < 0):
            raise MigrationGuard("Invalid live relation metadata")


async def _load_live_pg() -> list[dict]:
    """Optional authorized read-only live metadata check; no application rows."""
    from app.access_control import require_platform_admin
    from app.db import create_pool
    from app.settings import get_settings

    settings = get_settings()
    raw_actor = settings.catalogue_maintenance_actor_user_id
    if not raw_actor:
        raise MigrationGuard("Existing configured platform-admin actor is required")
    actor = str(UUID(raw_actor))
    pool = await create_pool(settings)
    try:
        async with pool.acquire(timeout=15) as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                await conn.execute("select set_config('tcg.user_id',$1,true)", actor)
                await conn.execute("select set_config('tcg.request_id',$1,true)",
                                   "cloudflare-full-exit-schema-readonly")
                await require_platform_admin(conn)
                records = await conn.fetch(LIVE_SQL)
                return [dict(row) for row in records]
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, default=REGISTER)
    parser.add_argument("--verify-live-pg", action="store_true",
                        help="Read PostgreSQL system catalogue through admin/RLS; never read app rows")
    args = parser.parse_args()
    register = json.loads(args.register.read_text(encoding="utf-8"))
    report = validate_register(register)
    if args.verify_live_pg:
        assert_current_matches(asyncio.run(_load_live_pg()), register)
        report["live_schema_match"] = True
    else:
        report["live_schema_match"] = None
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
