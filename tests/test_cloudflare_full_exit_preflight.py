"""Offline gates for the complete, non-destructive Supabase exit inventory."""
import copy
import json
from pathlib import Path

import pytest

from tools.cloudflare_full_exit_preflight import (
    MigrationGuard,
    assert_current_matches,
    validate_register,
)

REGISTER_PATH = Path("docs/CLOUDFLARE_FULL_EXIT_TABLE_REGISTER_20261106.json")


@pytest.fixture()
def register():
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def test_all_supabase_relations_have_explicit_destinations(register):
    result = validate_register(register)
    assert result["source_relation_count"] == 148
    assert result["tables_by_schema"] == {
        "tcg": 107, "tcg_private": 6, "auth": 27, "storage": 8,
    }
    assert result["r2_data_export_completed_by_this_tool"] is False
    assert result["d1_data_import_completed_by_this_tool"] is False
    assert result["production_cutover_authorized"] is False


def test_finance_and_ownership_must_share_one_operational_d1(register):
    target = { (r["schema"], r["table"]): r for r in register["tables"] }
    for name in ("inventory_items", "owners", "owner_memberships", "orders",
                 "order_items", "financial_ledger_entries", "refund_events",
                 "shopify_webhook_events"):
        record = target[("tcg", name)]
        assert record["target"] == "D1_SINGLE_OPERATIONAL_DATABASE_R2_BACKUP"


def test_price_evidence_and_retained_history_are_not_equivalent(register):
    table = {r["table"]: r for r in register["tables"] if r["schema"] == "tcg"}
    assert table["reference_asking_prices"]["category"] == "market_asking"
    assert table["reference_asking_prices"]["target"] == (
        "R2_ASKING_ONLY_AND_D1_NON_MARKET_EVIDENCE"
    )
    assert table["reference_market_history"]["category"] == "market_history"
    assert table["pricing_policies"]["category"] == "market_policy"
    assert table["reference_market_prices"]["category"] == "market_current"


def test_auth_sessions_are_not_bulk_copied_as_d1_credentials(register):
    rows = [x for x in register["tables"] if x["schema"] == "auth"]
    assert len(rows) == 27
    assert all(x["target"] ==
               "EXTERNAL_IDENTITY_MIGRATION_NO_SESSION_TOKEN_COPY" for x in rows)


def test_missing_source_table_fails_closed(register):
    changed = copy.deepcopy(register)
    changed["tables"] = [r for r in changed["tables"]
                         if r["table"] != "financial_ledger_entries"]
    with pytest.raises(MigrationGuard):
        validate_register(changed)


def test_duplicate_source_table_fails_closed(register):
    changed = copy.deepcopy(register)
    changed["tables"].append(copy.deepcopy(changed["tables"][0]))
    with pytest.raises(MigrationGuard, match="Duplicate"):
        validate_register(changed)


def test_asking_price_promoted_to_current_market_fails_closed(register):
    changed = copy.deepcopy(register)
    for record in changed["tables"]:
        if record["schema"] == "tcg" and record["table"] == "reference_asking_prices":
            record["category"] = "market_current"
            record["target"] = "R2_EVIDENCE_AND_D1_ELIGIBLE_PRICE"
    with pytest.raises(MigrationGuard, match="Critical"):
        validate_register(changed)


def test_user_auth_row_cannot_be_routed_as_operational_bulk_copy(register):
    changed = copy.deepcopy(register)
    for record in changed["tables"]:
        if record["schema"] == "auth" and record["table"] == "users":
            record["category"] = "owners_inventory"
            record["target"] = "D1_SINGLE_OPERATIONAL_DATABASE_R2_BACKUP"
    with pytest.raises(MigrationGuard, match="boundary"):
        validate_register(changed)


def test_schema_drift_catches_new_pg_tables(register):
    current = [{"schema_name":r["schema"], "table_name":r["table"],
                "bytes":r["bytes"], "estimated_rows":r["estimated_rows"]}
               for r in register["tables"]]
    assert_current_matches(current, register)
    current.append({"schema_name": "tcg", "table_name": "new_unmapped_ledger",
                    "bytes": 0, "estimated_rows": 0})
    with pytest.raises(MigrationGuard, match="1 new"):
        assert_current_matches(current, register)


def test_missing_live_relation_fails_closed(register):
    current = [{"schema_name":r["schema"], "table_name":r["table"],
                "bytes":r["bytes"], "estimated_rows":r["estimated_rows"]}
               for r in register["tables"][1:]]
    with pytest.raises(MigrationGuard, match="absent"):
        assert_current_matches(current, register)


def test_invalid_live_metadata_and_negative_size_fail_closed(register):
    current = [{"schema_name":r["schema"], "table_name":r["table"],
                "bytes":r["bytes"], "estimated_rows":r["estimated_rows"]}
               for r in register["tables"]]
    current[0]["bytes"] = -1
    with pytest.raises(MigrationGuard, match="metadata"):
        assert_current_matches(current, register)
