"""Static checks for the read-only coverage audit and undeployed SQL proposal.

Does NOT connect to Supabase, R2, Railway, Shopify or any provider.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "docs/evidence/catalogue_coverage_per_set_20261110.csv"
SQL = ROOT / "database/proposals/catalogue_coverage_monitoring_views_20261110.sql"


def test_per_set_read_only_capture_reconciles_original_catalogue():
    with CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 674
    assert len({(r["system_code"], r["language"], r["set_id"]) for r in rows}) == 674
    expected = {
        "reference_cards": 69867,
        "eligible_fresh": 21091,
        "eligible_stale": 5,
        "no_eligible_quote": 48771,
        "remote_image_url": 66251,
        "mirror_metadata_verified": 66247,
        "db_mirror_gap": 3620,
    }
    for key, total in expected.items():
        assert sum(int(r[key]) for r in rows) == total
    for row in rows:
        assert int(row["eligible_fresh"]) + int(row["eligible_stale"]) + int(row["no_eligible_quote"]) == int(row["reference_cards"])
        assert int(row["mirror_metadata_verified"]) + int(row["db_mirror_gap"]) == int(row["reference_cards"])


def test_proposed_monitor_does_not_change_source_or_claim_r2_parity():
    sql = SQL.read_text(encoding="utf-8")
    sql_lower = sql.lower()
    assert "review only" in sql_lower
    assert "not an applied migration" in sql_lower
    assert "create or replace view tcg_private.catalogue_coverage_audit_v1" in sql_lower
    assert "security_invoker = true" in sql_lower
    assert "revoke all on tcg_private.catalogue_coverage_audit_v1" in sql_lower
    assert "not_verified" in sql_lower
    assert "r2_physical_head_status" in sql_lower
    assert "tcg_private.r2_first_catalogue_publications" in sql_lower
    assert "i.grading_company is not null and a.inventory_id = i.id" in sql_lower
    assert "coalesce(sum(total) filter(where price_evidence_state like 'fresh%'),0)" in sql_lower
    assert "join tcg.reference_market_prices" in sql_lower
    assert "from tcg.media_assets" in sql_lower
    for unsafe_sql in (
        "create table", "alter table", "create policy", "alter policy",
        "drop table", "drop view", "truncate", "insert into",
        "update tcg.", "delete from", "create trigger",
    ):
        assert unsafe_sql not in sql_lower
