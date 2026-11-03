from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.inventory_intelligence import rank_weekly_movers, weekly_change_pct


ROOT = Path(__file__).parents[1]


def mover(
    key: str,
    current: int | None,
    prior: int | None,
    *,
    name: str = "Card",
    updated_at: datetime | None = None,
):
    return {
        "pricing_key": key,
        "name": name,
        "set_name": "Set",
        "card_number": "001/100",
        "language": "English",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "quantity": 1,
        "current_market_value_minor": current,
        "prior_market_value_minor": prior,
        "current_pricing_updated_at": updated_at,
    }


def test_weekly_change_math_handles_rises_and_falls() -> None:
    assert weekly_change_pct(1250, 1000) == 25.0
    assert weekly_change_pct(750, 1000) == -25.0
    assert weekly_change_pct(1000, 1000) == 0.0


def test_weekly_change_fails_closed_without_valid_prior_value() -> None:
    assert weekly_change_pct(1000, None) is None
    assert weekly_change_pct(1000, 0) is None
    assert weekly_change_pct(None, 1000) is None


def test_weekly_movers_rank_increases_and_decreases_separately() -> None:
    rows = [
        mover("a", 1500, 1000, name="A"),
        mover("b", 1200, 1000, name="B"),
        mover("c", 700, 1000, name="C"),
        mover("d", 900, 1000, name="D"),
    ]
    result = rank_weekly_movers(rows, limit=5)

    assert [row["name"] for row in result["gainers"]] == ["A", "B"]
    assert [row["name"] for row in result["decliners"]] == ["C", "D"]
    assert result["gainers"][0]["change_pct"] == 50.0
    assert result["decliners"][0]["change_pct"] == -30.0


@pytest.mark.parametrize("include_delta", [False, True])
def test_penny_changes_keep_their_direction_when_percentages_round_to_zero(include_delta) -> None:
    rows = [
        mover("rise", 1_000_001, 1_000_000),
        mover("fall", 999_999, 1_000_000),
        mover("unchanged", 1_000_000, 1_000_000),
    ]
    if include_delta:
        for row in rows:
            row["change_minor"] = row["current_market_value_minor"] - row["prior_market_value_minor"]

    result = rank_weekly_movers(rows)

    rising, = result["gainers"]
    falling, = result["decliners"]
    assert rising["pricing_key"] == "rise" and rising["change_minor"] == 1
    assert falling["pricing_key"] == "fall" and falling["change_minor"] == -1
    assert rising["change_pct"] == falling["change_pct"] == 0.0
    assert all(row["pricing_key"] != "unchanged" for row in result["gainers"] + result["decliners"])


def test_duplicate_pricing_identity_is_deduped_to_latest_row() -> None:
    older = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 9, 25, 11, 0, tzinfo=timezone.utc)
    rows = [
        mover("same", 1100, 1000, name="Old copy", updated_at=older),
        mover("same", 1400, 1000, name="Latest copy", updated_at=newer),
    ]

    result = rank_weekly_movers(rows, limit=5)

    assert len(result["gainers"]) == 1
    assert result["gainers"][0]["name"] == "Latest copy"
    assert result["gainers"][0]["change_pct"] == 40.0


def test_no_prior_week_history_returns_no_movers() -> None:
    result = rank_weekly_movers([mover("a", 1000, None)], limit=5)
    assert result == {"gainers": [], "decliners": []}


def test_inventory_intelligence_endpoint_is_owner_scoped_and_groups_physical_copies() -> None:
    source = (
        ROOT / "backend" / "app" / "inventory_intelligence.py"
    ).read_text()

    assert 'owner = await _owner(connection)' in source
    assert 'reference_portfolio(connection, [owner_id])' in source
    assert 'shared_weekly_movers(connection, shared, window_days=window_days)' in source
    assert 'reference_top_groups(shared, top_limit)' in source
    assert 'tcg.pricing_snapshots' not in source
    assert '"groups_with_prior_value": summary["comparable_product_count"]' in source



def test_dashboard_shell_loads_portfolio_intelligence_safely() -> None:
    js = (
        ROOT / "backend" / "app" / "static" / "dashboard-shell.js"
    ).read_text()

    assert "/api/v1/inventory/intelligence?top_limit=5&window_days=7" in js
    assert "Inventory market value" in js
    assert "Store price value" in js
    assert "Top 5 products" in js
    assert "Weekly top movers" in js
    assert "renderWeeklyMovers" in js
