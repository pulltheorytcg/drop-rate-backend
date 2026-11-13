"""Offline multi-query pilot: broaden retrieval, never broaden valuation authority."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import reference_asking_backfill as backfill
from app.reference_multi_query_search import (
    EARLY_STOP_PLAUSIBLE, MAX_CANDIDATE_SUMMARIES,
    MAX_DETAILS_PER_REFERENCE, build_reference_search_plan,
)
from scripts.backfill_reference_asking import arguments


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def reference(**changes):
    ref = {
        "provider": "TCGdex", "system_code": "POKEMON_TCG",
        "language": "English", "provider_id": "base1-4", "set_id": "base1",
        "name": "Charizard", "card_number": "4/102", "set_name": "Base Set",
        "rarity": "Rare", "finish": "Holo", "evidence": {},
        "reference_group_count": 1, "needs_price": True,
    }
    ref.update(changes)
    return ref


def listing(i, price="100.00", *, title=None):
    return {
        "itemId": f"v1|{900000000000+i}|0",
        "title": title or "Pokemon Charizard 4/102 Base Set English Holo Near Mint Ungraded",
        "seller": {"username": f"seller{i}"},
        "price": {"currency": "GBP", "value": price},
        "buyingOptions": ["FIXED_PRICE"],
        "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "GBP"}}],
        "itemLocation": {"country": "GB"},
        "condition": "Near Mint or Better",
    }


async def quota(_client):
    return {
        "rateLimits": [{
            "apiContext": "buy", "apiName": "browse", "resources": [{
                "name": "buy.browse", "rates": [{
                    "limit": 5000, "remaining": 4999, "count": 1,
                    "timeWindow": 86400, "reset": "2026-10-29T07:00:00Z",
                }]
            }]
        }]
    }


class Store:
    def __init__(self, ref):
        self.ref, self.reservations, self.results, self.events = ref, [], [], []
        self.done = False

    async def quota_budget(self, windows):
        return {"total_requests": 0, "receipts": []}

    async def checkpoint(self, state):
        self.events.append(("checkpoint", state["requests"]))

    async def candidates(self, cursor, scope, limit):
        return [] if self.done or cursor else [self.ref]

    async def reserve(self, state, ref):
        state = deepcopy(state)
        state.update(
            cursor=backfill.cursor_for(ref), pending=backfill.cursor_for(ref),
            requests=state["requests"] + 1,
            session_requests=state["session_requests"] + 1,
        )
        self.reservations.append(deepcopy(state))
        self.events.append(("reserve", state["requests"]))
        return state

    async def result(self, state, ref, estimate):
        state = deepcopy(state)
        state["pending"] = None
        self.results.append(estimate)
        self.events.append(("result", state["requests"]))
        self.done = True
        return state

    async def finish(self, state):
        self.events.append(("finish", state["requests"]))


class Client:
    def __init__(self, store, second_rows, first_rows=None):
        self.store = store
        self.second_rows = second_rows
        self.first_rows = first_rows
        self.queries = []
        self.details = []

    async def search_items(self, **kwargs):
        assert self.store.events[-1][0] == "reserve"
        self.queries.append(kwargs["query"])
        assert kwargs["limit"] == 40
        assert kwargs["fixed_price_only"] is True
        assert kwargs["item_location_country"] == "GB"
        self.store.events.append(("search", len(self.queries)))
        if len(self.queries) == 1 and self.first_rows is not None:
            return {"itemSummaries": self.first_rows}
        if len(self.queries) in (2, 3):
            return {"itemSummaries": self.second_rows}
        return {"itemSummaries": []}

    async def get_item(self, item_id):
        assert self.store.events[-1][0] == "reserve"
        self.details.append(item_id)
        self.store.events.append(("detail", item_id))
        return next(row for row in (self.first_rows or []) + self.second_rows
                    if row["itemId"] == item_id)


def report(limit=25):
    return {
        "version": 1, "run_id": str(uuid4()), "status": "RUNNING",
        "apply": False, "scope": {"system_code": "POKEMON_TCG", "language": "English"},
        "max_queries": limit, "requests": 0, "session_requests": 0,
        "cursor": None, "pending": None, "budget_day": NOW.date().isoformat(),
        "benchmark_digest": "a"*64, "stats": {
            "scanned": 0, "collected": 0, "matched": 0,
            "written": 0, "summaries_seen": 0,
        }, "rejections": {}, "database_price_writes": 0,
    }


async def no_sleep(_seconds):
    return None


def run(ref, rows, *, max_queries=25, first_rows=None):
    store = Store(ref)
    client = Client(store, rows, first_rows=first_rows)
    state = asyncio.run(backfill.execute_backfill(
        store, client, report(max_queries),
        quota_reader=quota, clock=lambda: NOW,
        monotonic=lambda: 0.0, sleep=no_sleep, multi_query=True,
    ))
    return state, store, client


def test_lovable_plan_searches_alternate_anchors_and_alt_printing():
    plan = build_reference_search_plan(reference(
        system_code="ONE_PIECE_CARD_GAME",
        name="Monkey D. Luffy", card_number="OP05-119",
        set_name="Awakening of the New Era", finish="Alt Art",
        language="Japanese",
    ))
    assert 2 <= len(plan) <= 4
    assert any("OP05-119" in q for q in plan)
    assert any("Awakening of the New Era" in q for q in plan)
    assert any("Alt Art" in q for q in plan)
    assert all(len(q) <= 100 for q in plan)
    assert len({q.lower() for q in plan}) == len(plan)
    assert all("Luffy" not in q for q in plan[1:2])  # identifier-first discovery


def test_invalid_or_unknown_reference_never_creates_broad_unbounded_query():
    assert build_reference_search_plan({}) == ()
    assert build_reference_search_plan(reference(system_code="UNSUPPORTED")) == ()
    assert build_reference_search_plan(reference(card_number="")) == ()
    assert 1 <= MAX_DETAILS_PER_REFERENCE <= 24
    assert MAX_CANDIDATE_SUMMARIES <= 160
    assert EARLY_STOP_PLAUSIBLE <= MAX_DETAILS_PER_REFERENCE


def test_opt_in_cli_is_disabled_by_default_and_is_explicit():
    assert arguments(["--from-settings"]).multi_query is False
    assert arguments(["--from-settings", "--run", "--multi-query"]).multi_query is True


def test_second_query_finds_three_verified_sellers_but_cannot_value_inventory():
    rows = [listing(1, "100"), listing(2, "110"), listing(3, "120")]
    state, store, client = run(reference(), rows)
    assert len(client.queries) >= 2
    assert client.queries[0] == "Pokemon Charizard 4/102"
    assert client.queries[1] == "4/102 Base Set Pokemon"
    assert state["requests"] == state["stats"]["search_requests"] + state["stats"]["detail_requests"]
    assert len(client.details) == 3   # repeated across searches, fetched once
    assert state["funnel"]["references_searched"] == 1
    assert state["stats"]["collected"] == 1
    assert state["stats"]["distinct_summaries"] == 3
    assert state["stats"]["matched"] == 1
    assert state["database_price_writes"] == state["stats"]["written"] == 0
    estimate = store.results[0]
    assert estimate["status"] == "READY"
    assert estimate["basis"] == "ASKING_PRICE_ESTIMATE"
    assert estimate["physical_valuation_eligible"] is False
    assert estimate["seller_count"] == 3
    assert estimate["estimate_minor"] == 11000
    assert all(event[0] == "reserve" for event in (
        store.events[i-1] for i, event in enumerate(store.events) if event[0] in ("search","detail")
    ))


def test_wrong_variant_grade_language_and_rogue_listing_are_not_accepted():
    good = listing(1, "50")
    incompatible = [
        listing(2, "60", title="Pokemon Charizard 4/102 Base Set Japanese Holo Near Mint"),
        listing(3, "700", title="Pokemon Charizard 4/102 Base Set English PSA 10"),
        listing(4, "65", title="Pokemon Charizard 4/102 Base Set English Reverse Holo Near Mint"),
    ]
    state, store, client = run(reference(), [good, *incompatible])
    assert state["stats"]["written"] == 0
    assert store.results
    assert store.results[0]["status"] != "READY"
    assert state["database_price_writes"] == 0


def test_low_global_budget_preserves_request_reservation_and_does_not_fake_match():
    state, store, client = run(reference(), [listing(1), listing(2), listing(3)], max_queries=2)
    assert state["requests"] == len(store.reservations) == 2
    assert state["status"] == "INCOMPLETE"
    assert state["stop_reason"] == "REQUEST_LIMIT"
    assert state["stats"]["written"] == 0
    assert state["stats"]["detail_requests"] == 0


def test_ambiguous_first_query_cannot_suppress_next_three_searches():
    wrong_set = [
        listing(i, "105", title="Pokemon Charizard 4/102 Some Other Set English Holo Near Mint Ungraded")
        for i in range(10, 22)
    ]
    valid = [listing(101, "100"), listing(102, "110"), listing(103, "120")]
    state, store, client = run(reference(), valid, first_rows=wrong_set)
    assert len(client.queries) >= 2
    assert state["funnel"]["references_searched"] == 1
    assert state["stats"]["search_variants_used"] >= 2
    assert state["stats"]["distinct_summaries"] == 15
    assert state["stats"]["matched"] == 1
    assert store.results[0]["status"] == "READY"
    assert store.results[0]["physical_valuation_eligible"] is False


def test_five_exact_distinct_summary_sellers_allow_early_stop_without_valuing_summaries():
    exact = [listing(i, "100") for i in range(201, 206)]
    state, store, client = run(reference(), [], first_rows=exact)
    assert len(client.queries) == 1
    assert len(client.details) == 5
    assert store.results[0]["status"] == "READY"
    assert store.results[0]["basis"] == "ASKING_PRICE_ESTIMATE"
    assert store.results[0]["physical_valuation_eligible"] is False
