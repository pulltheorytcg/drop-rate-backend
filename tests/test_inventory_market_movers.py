"""Current holdings only: missing or incompatible evidence is never a return."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.inventory_market_movers import HISTORY_SQL, shared_weekly_movers, weekly_change_pct
from app.inventory_reference_values import GUIDE, SOLD

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
CURRENT = NOW-timedelta(days=1)
SNAPSHOT = UUID(int=101)
CATALOGUE = UUID(int=201)


def item(number=1, **changes):
    row = dict(id=UUID(int=number), catalogue_id=CATALOGUE, owner_id=UUID(int=901),
               status="DRAFT", name="Physical copy", product_type="CARD", language="English",
               catalogue_language="English", condition="Near Mint", grading_company=None,
               grade=None, seal_status=None, market_value_minor=1200,
               reference_value=dict(status="REFERENCE_ESTIMATE", method=GUIDE,
                   snapshot_id=str(SNAPSHOT), market_value_minor=1200, checked_at=CURRENT))
    row.update(changes)
    return row


def comparison(**changes):
    row = dict(current_snapshot_id=SNAPSHOT, catalogue_id=CATALOGUE, current_value_minor=1200,
               current_at=CURRENT, current_recorded_at=CURRENT+timedelta(minutes=10), method=GUIDE,
               baseline_snapshot_id=UUID(int=102), baseline_value_minor=1000,
               baseline_at=CURRENT-timedelta(days=7),
               baseline_recorded_at=CURRENT-timedelta(days=7)+timedelta(minutes=10))
    row.update(changes)
    return row


class Connection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    async def fetch(self, sql, ids, window, now):
        assert sql == HISTORY_SQL
        self.calls.append((ids, window, now))
        return [row for row in self.rows if row["current_snapshot_id"] in ids]


@pytest.mark.asyncio
async def test_same_owned_profile_counts_copies_once_without_private_fields_or_mutation():
    copies = [item(1), item(2, status="RESERVED"), item(3, status="SOLD"), item(4, status="WITHDRAWN")]
    copies.append(deepcopy(copies[0]))
    before = deepcopy(copies)
    conn = Connection([comparison()])
    result = await shared_weekly_movers(conn, copies, now=NOW)
    assert copies == before
    assert len(conn.calls) == 1 and conn.calls[0][0] == [SNAPSHOT]
    assert result["summary"]["owned_item_count"] == 2
    assert result["summary"]["current_value_product_count"] == 1
    assert result["summary"]["comparable_item_count"] == 2
    assert result["summary"]["status"] == "READY"
    row, = result["movers"]
    assert row["quantity"] == 2 and row["change_minor"] == 200 and row["change_pct"] == 20
    assert row["comparison_kind"] == "GUIDE_ESTIMATE" and row["comparison_days"] == 7
    assert row["baseline_at"] == CURRENT-timedelta(days=7)
    assert "owner_id" not in row


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"catalogue_id": UUID(int=999)}, {"method": SOLD}, {"current_value_minor": 999},
    {"current_at": CURRENT-timedelta(hours=1)}, {"baseline_value_minor": 0},
    {"baseline_value_minor": -1}, {"baseline_value_minor": None},
    {"baseline_at": CURRENT-timedelta(days=5)}, {"baseline_at": CURRENT-timedelta(days=9)},
    {"baseline_recorded_at": NOW}, {"current_recorded_at": NOW+timedelta(hours=1)},
    {"baseline_recorded_at": CURRENT-timedelta(days=9)},
])
async def test_wrong_or_backfilled_comparison_fails_closed(changes):
    result = await shared_weekly_movers(Connection([comparison(**changes)]), [item()], now=NOW)
    assert result["summary"]["status"] == "WAITING_FOR_HISTORY"
    assert result["movers"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["STALE", "NEEDS_DETAILS", "UNAVAILABLE", "CONDITION_REFERENCE"])
async def test_stale_and_catalogue_only_comparisons_are_not_current_values(status):
    copy = item()
    copy["reference_value"]["status"] = status
    copy["catalogue_reference"] = dict(status="CATALOGUE_GUIDE", market_value_minor=9999)
    conn = Connection([comparison()])
    result = await shared_weekly_movers(conn, [copy], now=NOW)
    assert result["summary"]["status"] == "NO_CURRENT_VALUES" and not conn.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("checked", [NOW-timedelta(days=8), NOW+timedelta(seconds=1)])
async def test_current_evidence_date_cannot_be_old_or_future(checked):
    copy = item()
    copy["reference_value"]["checked_at"] = checked
    result = await shared_weekly_movers(Connection(), [copy], now=NOW)
    assert result["summary"]["status"] == "NO_CURRENT_VALUES"


@pytest.mark.asyncio
async def test_no_change_has_real_comparisons_and_does_not_show_flat_movers():
    result = await shared_weekly_movers(Connection([comparison(baseline_value_minor=1200)]), [item()], now=NOW)
    assert result["movers"] == []
    assert result["summary"]["status"] == "NO_CHANGE"
    assert result["summary"]["comparable_product_count"] == 1
    assert result["summary"]["unchanged_product_count"] == 1
    assert result["summary"]["history_ready"] is True


@pytest.mark.asyncio
async def test_empty_collection_does_not_query_or_adopt_unowned_history():
    conn = Connection([comparison()])
    result = await shared_weekly_movers(conn, [], now=NOW)
    assert result["summary"]["status"] == "EMPTY_COLLECTION" and not conn.calls


@pytest.mark.asyncio
async def test_selected_snapshot_requests_are_bounded_to_one_hundred():
    copies = []
    for number in range(1, 202):
        copy = item(number)
        copy['reference_value']['snapshot_id'] = str(UUID(int=1000+number))
        copies.append(copy)
    conn = Connection()
    result = await shared_weekly_movers(conn, copies, now=NOW)
    assert [len(call[0]) for call in conn.calls] == [100, 100, 1]
    assert result['summary']['waiting_for_history_product_count'] == 201


@pytest.mark.parametrize("current,prior", [(float("nan"), 1), (1, float("inf")), (True, 1),
    (1, False), ("100", 1), (2**63, 1), (1, 2**63), (-1, 100)])
def test_nonmoney_or_nonfinite_inputs_cannot_escape_as_percentages(current, prior):
    assert weekly_change_pct(current, prior) is None


def test_percentage_rounding_is_deterministic_and_bounds_bigint_money():
    assert weekly_change_pct(1001, 1000) == 0.1
    assert weekly_change_pct(2**63-1, 1) < float("inf")
    assert weekly_change_pct(0, 1000) == -100


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [0, 91, True, 7.1])
async def test_invalid_window_is_rejected(window):
    with pytest.raises(ValueError):
        await shared_weekly_movers(Connection(), [], window_days=window, now=NOW)
