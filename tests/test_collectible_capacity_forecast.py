"""Forecast is a planning receipt; no forecast can authorize a bulk import."""
from argparse import Namespace

import pytest

from app.collectible_capacity_forecast import (
    CardReferenceFootprint,
    forecast_card_reference_growth,
)
from scripts.forecast_collectible_capacity import report


LIVE_SNAPSHOT = CardReferenceFootprint(
    database_bytes=419_220_627,
    reference_card_rows=69_697,
    reference_card_table_bytes=77_152_256,
)


def test_live_size_blocks_even_one_new_reference():
    result = forecast_card_reference_growth(LIVE_SNAPSHOT, proposed_reference_cards=1)
    assert result["status"] == "BLOCKED_BY_CURRENT_IMPORT_GUARD"
    assert result["authorizes_import"] is False
    assert result["remaining_free_database_bytes_now"] == 80_779_373
    assert result["observed_bytes_per_card"] == 1107


def test_estimates_have_cushion_but_never_claim_approval():
    current = CardReferenceFootprint(300_000_000, 50_000, 40_000_000)
    possible = forecast_card_reference_growth(current, proposed_reference_cards=10)
    assert possible["baseline_growth_bytes"] == 8000
    assert possible["planning_growth_bytes"] == 12000
    assert possible["status"] == "REVIEW_ONLY_NOT_IMPORT_AUTHORIZATION"
    assert possible["authorizes_import"] is False
    blocked = forecast_card_reference_growth(current, proposed_reference_cards=100_000)
    assert blocked["status"] == "BLOCKED_BY_PROJECTED_IMPORT_GUARD"


@pytest.mark.parametrize("field, value", [
    ("database_bytes", -1),
    ("database_bytes", True),
    ("reference_card_rows", 999),
    ("reference_card_table_bytes", 0),
    ("reference_card_table_bytes", 600_000_000),
])
def test_invalid_or_unrepresentative_metrics_fail_closed(field, value):
    data = dict(database_bytes=419_220_627, reference_card_rows=69_697,
                reference_card_table_bytes=77_152_256)
    data[field] = value
    with pytest.raises(ValueError):
        forecast_card_reference_growth(
            CardReferenceFootprint(**data), proposed_reference_cards=100,
        )


def test_non_integer_and_negative_candidate_counts_fail_closed():
    for count in (-1, 1.2, True):
        with pytest.raises(ValueError):
            forecast_card_reference_growth(LIVE_SNAPSHOT, proposed_reference_cards=count)


@pytest.mark.asyncio
async def test_offline_receipt_explicitly_not_live_and_partial_snapshot_refused(monkeypatch):
    monkeypatch.delenv("TCG_DATABASE_URL", raising=False)
    args = Namespace(cards=1179, database_bytes=419_220_627,
                     reference_rows=69_697, reference_table_bytes=77_152_256)
    result = await report(args)
    assert result["evidence_mode"] == "OFFLINE_SNAPSHOT_RECHECK_BEFORE_IMPORT"
    assert result["status"] == "BLOCKED_BY_CURRENT_IMPORT_GUARD"
    args.reference_table_bytes = None
    with pytest.raises(ValueError, match="together"):
        await report(args)
    args.database_bytes = args.reference_rows = None
    with pytest.raises(ValueError, match="TCG_DATABASE_URL"):
        await report(args)
