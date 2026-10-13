"""Actionable global price coverage without fabricating GBP market values."""

import pytest

from app.catalogue_coverage import (
    COVERAGE_SQL,
    PRICED_REFERENCE_STATUSES,
    UNPRICED_REFERENCE_ACTIONS,
    coverage_summary,
)


def row(kind, game, language, status, products):
    return {"kind": kind, "system_code": game, "language": language,
            "status": status, "products": products}


def test_gap_summary_preserves_every_reference_and_reports_actionable_source_gaps():
    rows = [
        row("CARD", "ONE_PIECE_CARD_GAME", "Japanese", "SOURCE_ACCESS_REQUIRED", 4480),
        row("CARD", "DRAGON_BALL_SUPER_FUSION_WORLD", "Japanese", "SOURCE_ACCESS_REQUIRED", 3227),
        row("CARD", "NARUTO_BANDAI_LEGACY", "Unknown", "SOURCE_ACCESS_REQUIRED", 4487),
        row("CARD", "NARUTO_KAYOU", "Unknown", "SOURCE_ACCESS_REQUIRED", 2679),
        row("CARD", "POKEMON_TCG", "English", "REFERENCE_AVAILABLE", 12127),
        row("CARD", "POKEMON_TCG", "English", "MIXED_LANGUAGE_GUIDE", 4397),
        row("CARD", "POKEMON_TCG", "English", "EXACT_QUOTE_UNAVAILABLE", 7246),
        row("SEALED", "ONE_PIECE_CARD_GAME", "Unknown", "PROVIDER_MAPPING_REQUIRED", 156),
        row("SEALED", "ONE_PIECE_CARD_GAME", "Unknown", "MIXED_LANGUAGE_GUIDE", 270),
    ]
    result = coverage_summary(rows)
    cards = result["by_kind"]["CARD"]
    assert cards["total"] == 38643
    assert cards["priced"] == 16524
    assert cards["missing"] == 22119
    assert result["by_kind"]["SEALED"] == {"total": 426, "priced": 270, "missing": 156}
    assert result["by_status"]["SOURCE_ACCESS_REQUIRED"] == 14873
    assert result["missing_by_reason"][0] == {
        "status": "SOURCE_ACCESS_REQUIRED",
        "count": 14873,
        "next_action": UNPRICED_REFERENCE_ACTIONS["SOURCE_ACCESS_REQUIRED"],
        "needs_external_data_access": True,
    }
    assert result["by_game"][0]["status_counts"]
    assert result["pricing_scope"] == "GLOBAL_REFERENCE_LIBRARY"
    assert result["valuation_currency"] == "GBP"
    assert all(x["count"] > 0 and x["status"] not in PRICED_REFERENCE_STATUSES
               for x in result["missing_by_reason"])


def test_unpriced_does_not_turn_into_free_cards_and_source_mappings_remain_gated():
    assert "p.market_value_minor>0" in COVERAGE_SQL
    assert "b.market_value_minor>0" in COVERAGE_SQL
    assert "p.market_value_minor is not null" not in COVERAGE_SQL
    assert "or (r.language='Japanese'" in COVERAGE_SQL
    assert "'NARUTO_BANDAI_LEGACY','NARUTO_KAYOU'" in COVERAGE_SQL
    assert "'SOURCE_ACCESS_REQUIRED'" in COVERAGE_SQL
    assert "now()-interval '7 days'" in COVERAGE_SQL
    assert "reference_identity'=jsonb_build_object(" in COVERAGE_SQL
    assert "tcg.inventory_items" not in COVERAGE_SQL
    assert "owner_id" not in COVERAGE_SQL


def test_coverage_remains_account_independent_and_is_strict_on_negative_counts():
    rows = [row("CARD", "POKEMON_TCG", "Japanese", "REFERENCE_AVAILABLE", 5),
            row("CARD", "POKEMON_TCG", "Japanese", "US_CONTEXT_ONLY", 3)]
    assert coverage_summary(rows) == coverage_summary([dict(x) for x in rows])
    summary = coverage_summary(rows)
    assert summary["by_kind"]["CARD"] == {"total": 8, "priced": 5, "missing": 3}
    assert summary["missing_by_reason"][0]["status"] == "US_CONTEXT_ONLY"
    assert summary["missing_by_reason"][0]["needs_external_data_access"] is False
    with pytest.raises(ValueError, match="Invalid catalogue"):
        coverage_summary([row("CARD", "POKEMON_TCG", "Japanese", "REFERENCE_AVAILABLE", -1)])


@pytest.mark.asyncio
async def test_existing_daily_receipt_contains_actionable_global_coverage_without_new_jobs(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone
    from uuid import uuid4

    from app import catalogue_coverage, catalogue_maintenance

    global_rows = [
        dict(row("CARD", "ONE_PIECE_CARD_GAME", "Japanese", "SOURCE_ACCESS_REQUIRED", 4480),
             oldest_check=None),
        dict(row("CARD", "POKEMON_TCG", "English", "REFERENCE_AVAILABLE", 12127),
             oldest_check=datetime(2026, 10, 12, tzinfo=timezone.utc)),
    ]
    class Conn:
        async def execute(self, query):
            assert query == "select set_config('statement_timeout','45000',true)"
            return "SELECT 1"

        async def fetch(self, query, **kwargs):
            assert "from tcg.reference_cards" in query
            assert "tcg.inventory_items" not in query
            assert kwargs == {"timeout": 50}
            return global_rows

        async def fetchval(self, query):
            assert query.strip() == "select count(*) from tcg.catalogue_products"
            return 464

    @asynccontextmanager
    async def connection(pool, actor, request_id):
        yield Conn()

    stored = []

    async def record(pool, actor, job, status, report):
        stored.append({"job": job, "status": status, "report": report})

    monkeypatch.setattr(catalogue_coverage, "user_connection", connection)
    monkeypatch.setattr(catalogue_maintenance, "receipt", record)
    data = await catalogue_coverage.record_coverage(object(), uuid4())
    assert data["scope"] == "ALL_REFERENCE_CARDS_AND_SEALED_PRODUCTS"
    assert data["total"] == 16607
    assert data["summary"]["by_kind"]["CARD"]["missing"] == 4480
    assert data["summary"]["missing_by_reason"][0]["status"] == "SOURCE_ACCESS_REQUIRED"
    assert data["store_price_updates"] == 0
    assert stored[0]["job"] == "CATALOGUE_COVERAGE"
    assert stored[0]["status"] == "COMPLETE"
    assert stored[0]["report"] is data


def test_coverage_retries_after_completed_price_refresh_without_refetching_sources():
    from datetime import datetime, timedelta, timezone
    from app.catalogue_maintenance import coverage_lags_pricing

    base=datetime(2026,10,13,14,37,tzinfo=timezone.utc)
    complete=lambda t:{"started_at":t,"status":"COMPLETE"}
    coverage=complete(base)
    latest={"CATALOGUE_COVERAGE":coverage,
            "REFERENCE_PRICES":complete(base+timedelta(seconds=2)),
            "CARDMARKET_VALUES":complete(base+timedelta(minutes=4))}
    assert coverage_lags_pricing(latest)
    # Pricing remains COMPLETE. Only the skipped coverage receipt needs retry;
    # the existing due() logic therefore does not re-run expensive providers.
    assert not coverage_lags_pricing({
        **latest,"CATALOGUE_COVERAGE":complete(base+timedelta(minutes=6))
    })
    assert not coverage_lags_pricing({
        "CATALOGUE_COVERAGE":coverage,
        "REFERENCE_PRICES":{"started_at":base+timedelta(minutes=1),"status":"RUNNING"},
    })
    assert coverage_lags_pricing({"CATALOGUE_COVERAGE":coverage,
        "SEALED_REFERENCE_PRICES":complete(base+timedelta(minutes=1))})
    assert coverage_lags_pricing({"CATALOGUE_COVERAGE":coverage,
        "CATALOGUE_VALUES":complete(base+timedelta(minutes=1))})
    assert coverage_lags_pricing({"CATALOGUE_COVERAGE":coverage,
        "CARDMARKET_VALUES":complete(base+timedelta(minutes=1))})
    assert coverage_lags_pricing({})
