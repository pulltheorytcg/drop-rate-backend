"""Synthetic facts only. Neither provider permission nor live valuation proof."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from app.reference_asking_funnel import begin_funnel, record_estimate, receipt_funnel
from app.reference_asking_estimator import estimate_reference_asking_price
from app import reference_asking_backfill as worker
from test_reference_asking_estimator import reference, row, NOW
from test_reference_asking_backfill import (
    MemoryStore, report, quota_reader, run_now, no_sleep, Connection, ACTOR, ready, sql_dependencies, NOW as WORKER_NOW,
    reference as worker_reference,
)


def result(rows, **kwargs):
    return estimate_reference_asking_price(reference(), rows, observed_at=NOW,
                                           now=kwargs.get("now", NOW))


def test_identity_acceptance_is_not_shipping_or_independent_seller_acceptance():
    rows = [row(1), row(2, seller={"username": "seller1"}),
            row(3, shippingOptions=[]), row(4, title="Pokemon Charizard PSA 10")]
    value = result(rows)
    assert value["status"] == "INSUFFICIENT_COMPARABLES"
    assert value["funnel"] == {"evaluated": True, "rows_seen": 4,
        "identity_and_condition_accepted": 3, "comparable_rows_accepted": 2,
        "missing_language_evidence": 0, "conflicting_language_evidence": 0}
    state = report(); begin_funnel(state); record_estimate(state, value)
    assert state["funnel"]["detail_first_rejections"] == {
        "GRADED_OR_SLAB": 1, "UNKNOWN_OR_INVALID_SHIPPING": 1}
    assert state["funnel"]["dedup_and_sample_rejections"] == {"DUPLICATE_SELLER": 1}
    assert state["funnel"]["reference_outcomes"] == {"INSUFFICIENT_COMPARABLES": 1}
    assert "seller1" not in json.dumps(state["funnel"])


@pytest.mark.parametrize("change,reason", [
    ({"title": "Pokemon Charizard 4/102 Base Set Japanese Holo Near Mint"}, "LANGUAGE_MISMATCH_OR_UNKNOWN"),
    ({"title": "Pokemon Charizard 5/102 Base Set English Holo Near Mint"}, "CARD_NUMBER_MISMATCH"),
    ({"title": "Pokemon Charizard 4/102 Base Set 2 English Holo Near Mint"}, "SET_MISMATCH"),
    ({"title": "Pokemon Charizard 4/102 Base Set English Reverse Holo Near Mint"}, "FINISH_MISMATCH_OR_UNKNOWN"),
    ({"condition": "Damaged"}, "CONDITION_OUTSIDE_NM_MINT"),
    ({"conditionId": "2750"}, "GRADED_OR_SLAB"),
])
def test_mismatches_still_reject_with_counted_reason(change, reason):
    value = result([row(1, **change)])
    assert value["rejection_counts"][reason] == 1
    assert value["funnel"]["identity_and_condition_accepted"] == 0
    assert value["estimate_minor"] is None


def test_stale_inputs_do_not_claim_identity_evaluation():
    value = result([row(1), row(2), row(3)], now=NOW+timedelta(days=3))
    state = report(); begin_funnel(state); record_estimate(state, value)
    assert value["funnel"]["evaluated"] is False
    assert state["funnel"]["reference_outcomes"] == {"STALE_EVIDENCE": 1}
    assert state["funnel"]["details_evaluated"] == 0


def test_legacy_receipts_remain_unknown_not_fabricated_zero():
    original = {"stats": {"collected": 12, "summaries_seen": 40, "matched": 0, "written": 0}}
    before = deepcopy(original)
    value = receipt_funnel(original)
    assert value["references_searched"] == 12
    assert value["full_details_retrieved"] is None
    assert value["exact_identity_and_condition_accepted"] is None
    assert value["market_value_display_eligible"] is None
    assert original == before


def test_empty_discovery_distinct_from_match_failure_and_resume_keeps_totals():
    ref = reference()
    state = report(); state["requests"] = 9
    store = MemoryStore([ref])
    class Client:
        async def search_items(self, **kwargs): return {"itemSummaries": []}
    outcome = run_now(worker.execute_backfill(store, Client(), state,
        quota_reader=quota_reader, clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    funnel = outcome["funnel"]
    assert funnel["prior_requests_not_instrumented"] == 9
    assert funnel["references_searched"] == 1
    assert funnel["searches_returning_listings"] == 0
    assert funnel["candidates_discovered"] == 0
    before = deepcopy(funnel); begin_funnel(outcome)
    assert outcome["funnel"] == before


def test_sufficient_synthetic_evidence_is_not_persisted_or_displayed_by_diagnosis():
    state = report(); begin_funnel(state)
    value = result([row(1), row(2), row(3)])
    record_estimate(state, value)
    assert state["funnel"]["estimates_generated"] == 1
    assert state["funnel"]["estimates_persisted"] == 0
    assert state["funnel"]["market_value_display_eligible"] == 0
    assert state["funnel"]["valuation_permission"] == "NOT_VERIFIED"


def test_persistence_count_commits_atomically_and_does_not_survive_failure(sql_dependencies):
    ref = worker_reference()
    for fail in (False, True):
        connection = Connection(ref, fail_cache=fail)
        state = report(apply=True); begin_funnel(state)
        store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: WORKER_NOW)
        if fail:
            with pytest.raises(Exception): run_now(store.result(state, ref, ready(ref)))
            assert state["funnel"]["estimates_persisted"] == 0
            assert not connection.committed
        else:
            updated = run_now(store.result(state, ref, ready(ref)))
            assert updated["funnel"]["estimates_persisted"] == 1


def test_missing_language_and_conflicting_language_are_distinct_without_inference():
    unknown = row(1); unknown['title'] = unknown['title'].replace('English ', '')
    conflicting = row(2); conflicting['title'] = conflicting['title'].replace('English', 'Japanese')
    value = result([unknown, conflicting])
    assert value['funnel']['missing_language_evidence'] == 1
    assert value['funnel']['conflicting_language_evidence'] == 1
    assert value['funnel']['identity_and_condition_accepted'] == 0


def test_controlled_exact_reference_worker_funnel_preserves_no_write_mode():
    refs = [reference(provider_id=f'fixture-{i}') for i in range(3)]
    store = MemoryStore(refs)
    class Client:
        calls = 0
        async def search_items(self, **kwargs):
            self.calls += 1
            return {'itemSummaries': [] if self.calls == 1 else
                    [row(i + 10*self.calls) for i in range(1, 4)]}
        async def get_item(self, item_id):
            i = int(item_id.split('|')[1]) - 100000000000
            return row(i, shippingOptions=[] if i >= 30 else
                       [{'shippingCost': {'currency': 'GBP', 'value': '0.00'}}])
    state = run_now(worker.execute_backfill(store, Client(), report(),
        quota_reader=quota_reader, clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    f = state['funnel']
    assert f['references_searched'] == 3
    assert f['searches_returning_listings'] == 2
    assert f['candidates_discovered'] == f['full_details_retrieved'] == 6
    assert f['exact_identity_and_condition_accepted'] == 6
    assert f['comparable_rows_accepted'] == 3
    assert f['estimates_generated'] == 1
    assert f['estimates_persisted'] == f['market_value_display_eligible'] == 0
    assert f['detail_first_rejections'] == {'UNKNOWN_OR_INVALID_SHIPPING': 3}
    assert state['requests'] == 9
