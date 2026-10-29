"""Realistic summary/detail separation with the actual bounded worker."""
from copy import deepcopy
from datetime import timedelta

import pytest

from app import reference_asking_backfill as worker
from app.ebay_official_client import EbayApiError
from test_reference_asking_backfill import (
    NOW, Client, Clock, MemoryStore, no_sleep, quota, quota_reader,
    reference, report, run_now,
)


def summary(index=1, **changes):
    row = {"itemId": f"v1|{100000000000 + index}|0",
           "seller": {"username": f"seller{index}"},
           "title": "Pokemon Bulbasaur 44 Base Set", "condition": "Ungraded",
           "conditionId": "4000"}
    row.update(changes)
    return row


def detail(index=1, **changes):
    row = summary(index)
    row.update(price={"currency": "GBP", "value": "5.00"},
        buyingOptions=["FIXED_PRICE"],
        shippingOptions=[{"shippingCost": {"currency": "GBP", "value": "1.00"}}],
        itemLocation={"country": "GB"}, condition="Near Mint or Better",
        localizedAspects=[{"name": "Language", "value": "English"},
                          {"name": "Finish", "value": "Normal"}])
    row.update(changes)
    return row


class RecordingStore(MemoryStore):
    def __init__(self, references):
        super().__init__(references)
        self.estimates = []
    async def result(self, state, ref, estimate):
        self.estimates.append(deepcopy(estimate))
        return await super().result(state, ref, estimate)


class DetailClient(Client):
    def __init__(self, store, rows=None, details=None, error=None):
        super().__init__(store)
        self.rows = rows if rows is not None else [summary(i) for i in range(1, 4)]
        self.details = details if details is not None else {detail(i)["itemId"]: detail(i) for i in range(1, 4)}
        self.detail_calls, self.detail_error = [], error
    async def search_items(self, **kwargs):
        await super().search_items(**kwargs)
        return {"itemSummaries": deepcopy(self.rows)}
    async def get_item(self, item_id):
        assert self.store.events[-1] == "reservation_commit"
        self.store.events.append("detail_http")
        self.detail_calls.append(item_id)
        if self.detail_error:
            raise self.detail_error
        return deepcopy(self.details[item_id])


def execute(store, client, *, limit=25, clock=None, reader=quota_reader):
    timer = clock or Clock()
    state = run_now(worker.execute_backfill(store, client, report(limit),
        quota_reader=reader, clock=lambda: NOW + timedelta(seconds=timer.elapsed),
        sleep=timer.sleep, monotonic=timer.monotonic))
    return state, timer


def test_item_details_supply_explicit_language_and_finish_without_search_keyword():
    store = RecordingStore([reference()])
    client = DetailClient(store)
    state, timer = execute(store, client)
    assert client.queries == ["Pokemon Bulbasaur 44"]
    assert len(client.detail_calls) == 3
    assert state["requests"] == 4 and state["stats"]["collected"] == 1
    assert state["stats"]["search_requests"] == 1 and state["stats"]["detail_requests"] == 3
    assert state["stats"]["matched"] == 1
    assert store.estimates[0]["status"] == "READY"
    assert store.estimates[0]["estimate_minor"] == 600
    evidence = worker.compact_evidence(store.estimates[0], reference(), "a" * 64)
    proofs = [item["listing_evidence"] for item in evidence["comparables"]]
    assert all(proof["acquisition"] == "GET_ITEM" for proof in proofs)
    assert all(proof["aspects"]["language"] == "english" for proof in proofs)
    assert all(proof["aspects"]["finish"] == "normal" for proof in proofs)
    assert "seller1" not in str(evidence)
    assert timer.elapsed == 3  # Search and each detail share the one/second limiter.
    assert state["pending"] is None and state["status"] == "COMPLETE"


@pytest.mark.parametrize("bad", [
    {"itemId": "v1|999999999999|0"},
    {"title": "Pokemon Bulbasaur 44 Base Set Japanese"},
    {"shippingOptions": []}, {"seller": {}},
    {"localizedAspects": [{"name": "Language", "value": "English"}]},
])
def test_complete_summary_cannot_replace_missing_or_conflicting_detail_evidence(bad):
    store = RecordingStore([reference()])
    rows = [detail(i) for i in range(1, 4)]  # Summaries alone would have passed.
    client = DetailClient(store, rows=rows)
    client.details[rows[0]["itemId"]].update(bad)
    state, _ = execute(store, client)
    assert state["stats"]["matched"] == 0
    assert store.estimates[0]["status"] == "INSUFFICIENT_COMPARABLES"
    assert store.estimates[0]["estimate_minor"] is None


def test_details_are_bounded_deduplicated_and_prefer_independent_sellers():
    rows = [summary(i) for i in range(1, 12)]
    rows.insert(1, deepcopy(rows[0]))
    rows[2]["seller"] = deepcopy(rows[0]["seller"])
    rows.insert(0, summary(99, title="Pokemon Bulbasaur 44 Base Set PSA 10"))
    rows.insert(0, summary(98, title="Pokemon Bulbasaur 44 Base Set lot of 2"))
    selected = worker.item_detail_candidates(reference(), rows)
    assert len(selected) == worker.MAX_ITEM_DETAILS_PER_CARD == 6
    assert len(set(selected)) == 6
    assert summary(1)["itemId"] in selected and summary(2)["itemId"] not in selected
    assert summary(98)["itemId"] not in selected and summary(99)["itemId"] not in selected


@pytest.mark.parametrize("limit,matched", [(1, 0), (3, 0), (4, 1)])
def test_request_limit_charges_search_and_details_and_finishes_partial_evidence(limit, matched):
    store = RecordingStore([reference("1"), reference("2")])
    client = DetailClient(store)
    state, _ = execute(store, client, limit=limit)
    assert state["requests"] == limit == len(client.queries) + len(client.detail_calls)
    assert state["stats"]["matched"] == matched
    assert state["status"] == "INCOMPLETE" and state["stop_reason"] == "REQUEST_LIMIT"
    assert state["cursor"] == worker.cursor_for(reference("1")) and state["pending"] is None
    assert len(store.estimates) == 1


def test_detail_provider_failure_is_charged_and_stops_without_summary_fallback():
    store = RecordingStore([reference("1"), reference("2")])
    client = DetailClient(store, error=EbayApiError("do not log", status_code=429, retryable=True))
    state, _ = execute(store, client)
    assert state["requests"] == 2 and state["stats"]["detail_requests"] == 1
    assert state["status"] == "STOPPED" and state["stop_reason"] == "EBAY_PROVIDER_ERROR"
    assert state["pending"] == worker.cursor_for(reference("1"))
    assert not store.estimates and "do not log" not in str(state)


def test_detail_calls_obey_provider_headroom():
    store = RecordingStore([reference()])
    client = DetailClient(store)
    async def low_quota(client):
        return quota(503)
    state, _ = execute(store, client, reader=low_quota)
    assert state["requests"] == 3 and len(client.detail_calls) == 2
    assert state["status"] == "STOPPED" and state["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    assert not store.estimates


def test_deadline_stops_detail_hydration_before_another_get(monkeypatch):
    monkeypatch.setattr(worker, "MAX_RUN_SECONDS", 2.5)
    store = RecordingStore([reference()])
    client = DetailClient(store)
    state, _ = execute(store, client)
    assert state["requests"] == 3 and len(client.detail_calls) == 2
    assert state["status"] == "INCOMPLETE" and state["stop_reason"] == "TIME_LIMIT"
    assert state["pending"] is None and state["stats"]["matched"] == 0


def test_in_memory_detail_reuse_does_not_repeat_get_or_renew_observation():
    store = RecordingStore([reference("1"), reference("2")])
    client = DetailClient(store)
    state, timer = execute(store, client)
    assert len(client.queries) == 2 and len(client.detail_calls) == 3
    assert state["requests"] == 5 and state["stats"]["detail_cache_hits"] == 3
    assert state["stats"]["matched"] == 2
    observed = store.estimates[1]["observed_at"]
    assert observed == (NOW + timedelta(seconds=1)).isoformat()
    assert observed != (NOW + timedelta(seconds=timer.elapsed)).isoformat()


def test_detail_cache_does_not_retain_description_or_unrelated_seller_data():
    payload = detail(1, description="unbounded public description")
    payload["seller"]["legalInfo"] = {"address": "not needed"}
    selected = worker.bounded_item_detail(payload, payload["itemId"])
    assert selected["seller"] == {"username": "seller1"}
    assert "description" not in selected and "not needed" not in str(selected)
    assert worker.bounded_item_detail(payload, summary(2)["itemId"]) is None


def test_retrieval_without_language_keeps_final_language_requirement():
    store = RecordingStore([reference()])
    details = {summary(i)["itemId"]: detail(i, localizedAspects=[{"name": "Finish", "value": "Normal"}])
               for i in range(1, 4)}
    client = DetailClient(store, details=details)
    state, _ = execute(store, client)
    assert state["stats"]["matched"] == 0
    assert store.estimates[0]["rejection_counts"]["LANGUAGE_MISMATCH_OR_UNKNOWN"] == 3


def test_sold_out_item_detail_is_preserved_for_final_rejection():
    store = RecordingStore([reference()])
    client = DetailClient(store)
    client.details[summary(1)["itemId"]]["estimatedAvailabilities"] = [
        {"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]
    state, _ = execute(store, client)
    assert state["stats"]["matched"] == 0
    assert store.estimates[0]["status"] == "INSUFFICIENT_COMPARABLES"
    assert store.estimates[0]["estimate_minor"] is None


def test_masters_query_uses_official_legacy_name_without_marketing_suffix():
    ref = reference()
    ref.update(system_code="DRAGON_BALL_SUPER_MASTERS", name="Son Goku",
               card_number="BT1-001", set_name="Galactic Battle")
    assert worker.search_query(ref) == "Dragon Ball Super Son Goku BT1-001"


def test_quota_refresh_counts_detail_gets_in_the_same_hundred_request_window():
    store = RecordingStore([reference(f"{i:03d}") for i in range(30)])
    class UniqueDetailClient(DetailClient):
        async def search_items(self, **kwargs):
            await Client.search_items(self, **kwargs)
            base = len(self.queries) * 3
            self.rows = [summary(i) for i in range(base, base + 3)]
            self.details = {detail(i)["itemId"]: detail(i) for i in range(base, base + 3)}
            return {"itemSummaries": deepcopy(self.rows)}
    client = UniqueDetailClient(store)
    quota_at = []
    async def counted_quota(client):
        used = len(client.queries) + len(client.detail_calls)
        quota_at.append(used)
        return quota(4999 - used)
    state, timer = execute(store, client, limit=101, reader=counted_quota)
    assert quota_at == [0, 100]
    assert state["requests"] == 101
    assert len(client.queries) == 26 and len(client.detail_calls) == 75
    assert state["stats"]["matched"] == 25
    assert timer.elapsed == 100
    assert state["stop_reason"] == "REQUEST_LIMIT" and state["pending"] is None
