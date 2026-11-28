"""Stock shows the UK asking average, checked against Cardmarket (28 Nov 2026).

Read-only: no inventory, snapshot, Store Price or Shopify write. The asking
average is used only through the exact reference card that the copy's current
Cardmarket estimate already identified, and only for the same finish.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import inventory_reference_values as values

NOW = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
CATALOGUE = uuid4()
REFERENCE = {"provider": "Bandai Official", "system_code": "ONE_PIECE_CARD_GAME",
             "reference_language": "English", "provider_id": "OP15-024", "set_id": "569115",
             "reference_name": "Usopp", "reference_set_name": "Adventure", "reference_number": "OP15-024"}
KEY = "r:" + hashlib.md5("\x1f".join(("Bandai Official", "ONE_PIECE_CARD_GAME", "English", "OP15-024")).encode()).hexdigest()


def item(**changes):
    value = {"id": uuid4(), "catalogue_id": CATALOGUE, "product_type": "CARD", "language": "English",
             "catalogue_language": "English", "condition": "Near Mint", "variant": "Foil",
             "grading_company": None, "grade": None, "seal_status": None}
    value.update(changes)
    return value


def guide(**changes):
    row = {"snapshot_id": uuid4(), "catalogue_id": CATALOGUE, "basis_language": "English", "method": values.GUIDE,
           "market_value_minor": 120, "evidence_checked_at": NOW - timedelta(hours=3),
           "calculated_at": NOW - timedelta(hours=3), "algorithm_version": "drop-rate-market-v4",
           "reference_current": True, "guide_reference": dict(REFERENCE), "grading_company": None,
           "grade": None, "seal_status": None, "basis_condition": None}
    row.update(changes)
    return row


def view(**changes):
    value = {"status": "ASKING_PRICE_ESTIMATE", "estimate_minor": 160, "estimate_high_minor": 180,
             "seller_count": 6, "listing_count": 6, "observed_at": NOW - timedelta(hours=1),
             "expires_at": NOW + timedelta(days=2), "finish": "Foil", "condition": "Near Mint"}
    value.update(changes)
    return value


class Connection:
    def __init__(self, record):
        self.record, self.calls = record, []

    async def fetch(self, sql, keys, now):
        self.calls.append(keys)
        return [self.record] if self.record else []


@pytest.fixture
def asking(monkeypatch):
    from app import reference_asking_display as display
    state = {"view": view()}
    monkeypatch.setattr(display, "asking_estimate_view", lambda record, now: state["view"])
    return state


async def run(items, snapshots, record={"key": KEY}):
    connection = Connection(record)
    await values.add_asking_values(connection, items, {str(CATALOGUE): snapshots}, now=NOW)
    return connection


@pytest.mark.asyncio
async def test_an_agreeing_asking_average_is_the_stock_value(asking):
    copy = item()
    connection = await run([copy], [guide()])
    assert '"OP15-024"' in connection.calls[0]
    reference = copy["reference_value"]
    assert reference["status"] == "REFERENCE_ESTIMATE" and reference["method"] == values.ASKING
    assert reference["market_value_minor"] == copy["market_value_minor"] == 160
    assert reference["label"] == "UK asking average" and reference["seller_count"] == 6
    assert reference["recommended_retail_minor"] is None and copy["recommended_retail_minor"] is None
    assert copy["pricing_method"] == values.ASKING
    assert reference["cardmarket_check"] == {"status": "AGREES", "cardmarket_minor": 120}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"condition": "Lightly Played"}, {"grading_company": "PSA", "grade": "10"}, {"seal_status": "SEALED"},
    {"product_type": "SEALED"}, {"variant": ""}, {"variant": "Alt Art"}, {"language": "Japanese"}])
async def test_copies_the_guide_may_not_value_never_take_an_asking_average(asking, changes):
    copy = item(**changes)
    connection = await run([copy], [guide()])
    assert "reference_value" not in copy and connection.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"reference_current": False}, {"method": values.SOLD}, {"basis_language": "Japanese"},
    {"evidence_checked_at": NOW - timedelta(days=8)}, {"guide_reference": None},
    {"guide_reference": {**REFERENCE, "provider_id": ""}}, {"catalogue_id": uuid4()}])
async def test_only_a_current_exact_guide_reference_is_used(asking, changes):
    copy = item()
    connection = await run([copy], [guide(**changes)])
    assert "reference_value" not in copy and connection.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"finish": "Normal"}, {"estimate_minor": 1000}, {"estimate_minor": 0},
    {"expires_at": NOW - timedelta(seconds=1)}])
async def test_another_finish_a_disagreement_or_an_expired_ask_keeps_the_value(asking, changes):
    asking["view"] = view(**changes)
    copy = item(reference_value={"status": "REFERENCE_ESTIMATE", "method": values.GUIDE}, market_value_minor=120)
    await run([copy], [guide()])
    assert copy["reference_value"]["method"] == values.GUIDE and copy["market_value_minor"] == 120


@pytest.mark.asyncio
async def test_no_asking_evidence_keeps_the_value(asking):
    copy = item(reference_value={"status": "REFERENCE_ESTIMATE", "method": values.GUIDE}, market_value_minor=120)
    await run([copy], [guide()], record=None)
    assert copy["reference_value"]["method"] == values.GUIDE


@pytest.mark.parametrize("asking_minor,guide_minor,agrees", [
    (160, 120, True), (200, 4, True), (299, 100, True), (401, 100, False), (8000, 4000, True), (8001, 4000, False)])
def test_cardmarket_check_uses_the_catalogue_rule(asking_minor, guide_minor, agrees):
    result = values.asking_reference_value(item(), {"finish": "Foil", "guide_minor": guide_minor},
                                           view(estimate_minor=asking_minor), now=NOW)
    assert (result is not None) is agrees


def test_totals_count_the_asking_average_as_a_labelled_estimate():
    copies = [{"market_value_minor": 160, "reference_value": {"status": "REFERENCE_ESTIMATE", "method": values.ASKING}},
              {"market_value_minor": 900, "reference_value": {"status": "AVAILABLE"}},
              {"market_value_minor": None, "reference_value": {"status": "UNAVAILABLE"}}]
    totals = values.reference_totals(copies)
    assert totals["total_minor"] == 1060 and totals["valued_count"] == 2
    assert totals["estimate_count"] == 1 and totals["estimate_total_minor"] == 160
