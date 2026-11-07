"""Budget, resume and transaction failure tests with no sockets or credentials."""
from bisect import bisect_right
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import reference_asking_backfill as worker
from app.ebay_official_client import EbayApiError
from scripts.backfill_reference_asking import arguments

NOW = datetime(2026, 10, 28, 22, tzinfo=timezone.utc)
ACTOR = UUID("00000000-0000-0000-0000-000000000001")


def run_now(coro):
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coro.close()
    raise AssertionError("Offline test yielded real asynchronous I/O")


def reference(identifier="1"):
    return {"provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "English",
            "provider_id": identifier, "name": "Bulbasaur", "card_number": "44",
            "set_id": "base1", "set_name": "Base Set", "finish": "Normal", "rarity": "Common",
            "evidence": {}, "reference_group_count": 1, "needs_price": True}


def report(limit=25, apply=False):
    return {"version": 1, "run_id": str(uuid4()), "status": "RUNNING", "apply": apply,
            "scope": {"system_code": None, "language": None}, "max_queries": limit,
            "requests": 0, "session_requests": 0, "cursor": None, "pending": None,
            "budget_day": NOW.date().isoformat(), "benchmark_digest": "a" * 64,
            "stats": {"scanned": 0, "collected": 0, "matched": 0, "written": 0, "summaries_seen": 0},
            "rejections": {}, "database_price_writes": 0}


def quota(remaining=4999):
    return {"rateLimits": [{"apiContext": "buy", "apiName": "Browse", "apiVersion": "v1", "resources": [
        {"name": "buy.browse", "rates": [{"limit": 5000, "remaining": remaining, "count": 5000-remaining,
            "timeWindow": 86400, "reset": "2026-10-29T07:00:00Z"}]},
        {"name": "buy.browse.item.bulk", "rates": [{"limit": 1, "remaining": 0, "count": 1,
            "timeWindow": 86400, "reset": "2026-10-29T07:00:00Z"}]}]}]}


async def quota_reader(client):
    return quota()


async def no_sleep(seconds):
    pass


class MemoryStore:
    def __init__(self, references):
        self.references, self.events = references, []
        self.receipts = {}
    def save_receipt(self, state):
        self.receipts[state["run_id"]] = {"requests": state["requests"], "report": deepcopy(state)}
    async def quota_budget(self, windows):
        return {"total_requests": sum(row["requests"] for row in self.receipts.values()),
                "receipts": list(self.receipts.values())}
    async def checkpoint(self, state):
        self.save_receipt(state)
        self.events.append("checkpoint_commit")
    async def candidates(self, cursor, scope, limit):
        after = worker.validated_cursor(cursor)
        return [r for r in self.references if worker.cursor_for(r) > after][:limit]
    async def reserve(self, state, ref):
        state = deepcopy(state)
        state.update(cursor=worker.cursor_for(ref), pending=worker.cursor_for(ref),
                     requests=state["requests"] + 1, session_requests=state["session_requests"] + 1)
        self.save_receipt(state)
        self.events.append("reservation_commit")
        return state
    async def result(self, state, ref, estimate):
        state = deepcopy(state)
        state["pending"] = None
        self.save_receipt(state)
        self.events.append("result_commit")
        return state
    async def finish(self, state):
        self.save_receipt(state)
        self.events.append("finish_commit")


class Client:
    def __init__(self, store, error=None):
        self.store, self.error, self.queries = store, error, []
    async def search_items(self, **kwargs):
        assert self.store.events[-1] == "reservation_commit"
        assert kwargs["limit"] == 100 and kwargs["fixed_price_only"]
        self.store.events.append("http")
        self.queries.append(kwargs["query"])
        if self.error:
            raise self.error
        return {"itemSummaries": []}



class PagedStore(MemoryStore):
    def __init__(self, references):
        super().__init__(references)
        self.cursors = [worker.cursor_for(ref) for ref in references]
        self.page_limits, self.reserved_ids = [], []
    async def candidates(self, cursor, scope, limit):
        self.page_limits.append(limit)
        start = bisect_right(self.cursors, worker.validated_cursor(cursor))
        return self.references[start:start+limit]
    async def reserve(self, state, ref):
        result = await super().reserve(state, ref)
        self.reserved_ids.append(ref["provider_id"])
        return result


class Clock:
    def __init__(self):
        self.elapsed = 0.0
    def monotonic(self):
        return self.elapsed
    async def sleep(self, seconds):
        self.elapsed += seconds


@pytest.mark.parametrize("limit", [1000, 2000])
def test_large_batches_stream_with_pacing_and_resume_without_duplicates(limit):
    refs = [reference(f"{i:05d}") for i in range(limit+1)]
    store = PagedStore(refs)
    clock = Clock()
    client = Client(store)
    quota_calls, request_times = [], []
    async def current_quota(client):
        quota_calls.append(len(client.queries))
        return quota(4999-len(client.queries))
    original_search = client.search_items
    async def timed_search(**kwargs):
        request_times.append(clock.elapsed)
        return await original_search(**kwargs)
    client.search_items = timed_search
    state = run_now(worker.execute_backfill(store, client, report(limit), quota_reader=current_quota,
                    clock=lambda: NOW, sleep=clock.sleep, monotonic=clock.monotonic))
    assert state["requests"] == state["session_requests"] == len(client.queries) == limit
    assert state["stop_reason"] == "REQUEST_LIMIT" and state["pending"] is None
    assert store.reserved_ids == [ref["provider_id"] for ref in refs[:-1]]
    assert quota_calls == list(range(0, limit, 100))
    assert all(later-earlier >= 1 for earlier, later in zip(request_times, request_times[1:]))
    assert set(store.page_limits) == {100}
    state.update(status="RUNNING", session_requests=0)
    resumed = run_now(worker.execute_backfill(store, client, state, quota_reader=current_quota,
                      clock=lambda: NOW, sleep=clock.sleep, monotonic=clock.monotonic))
    assert resumed["status"] == "COMPLETE" and resumed["requests"] == limit+1
    assert store.reserved_ids == [ref["provider_id"] for ref in refs]


@pytest.mark.parametrize("limit", [1000, 2000])
def test_large_readonly_plan_streams_candidates(monkeypatch, limit):
    store = PagedStore([reference(f"{i:05d}") for i in range(limit+1)])
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield object()
    monkeypatch.setattr(worker, "SqlBackfillStore", lambda *args, **kwargs: store)
    state = run_now(worker.backfill_reference_asking(Pool(), ACTOR, max_queries=limit))
    assert state["status"] == "PLAN_ONLY" and len(state["candidates"]) == limit
    assert state["requests"] == state["database_writes"] == 0
    assert store.events == [] and store.page_limits == [100] * (limit//100)


@pytest.mark.parametrize("limit", [1000, 2000])
def test_cli_accepts_larger_explicit_batches(limit):
    assert arguments(["--from-settings", "--run", "--max-queries", str(limit)]).max_queries == limit


def test_cli_retains_small_default_and_rejects_out_of_range():
    assert arguments(["--from-settings"]).max_queries == 25
    for limit in (0, 2001):
        with pytest.raises(SystemExit) as error:
            arguments(["--from-settings", "--max-queries", str(limit)])
        assert error.value.code == 2


def test_quota_refresh_stops_before_attempt_101_when_other_usage_consumes_headroom():
    store = PagedStore([reference(f"{i:05d}") for i in range(2000)])
    client = Client(store)
    async def shrinking_quota(client):
        return quota(4999 if not client.queries else 500)
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=shrinking_quota,
                    clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert state["status"] == "STOPPED" and state["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    assert state["requests"] == len(client.queries) == len(store.reserved_ids) == 100
    assert state["cursor"] == worker.cursor_for(store.references[99])


def test_stale_quota_refresh_cannot_restore_locally_consumed_requests():
    store = PagedStore([reference(f"{i:05d}") for i in range(2000)])
    client = Client(store)
    async def stale_quota(client):
        return quota(650)
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=stale_quota,
                    clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert state["status"] == "STOPPED" and state["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    assert state["requests"] == len(client.queries) == 150
    assert state["quota"]["windows"][0]["provider_remaining"] == 650
    assert state["quota"]["windows"][0]["remaining"] == 550


def test_failed_analytics_refresh_stops_without_reserving_attempt_101():
    store = PagedStore([reference(f"{i:05d}") for i in range(2000)])
    client = Client(store)
    async def failed_quota(client):
        if client.queries:
            raise worker.BackfillStop("ANALYTICS_UNAVAILABLE")
        return quota()
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=failed_quota,
                    clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert state["status"] == "STOPPED" and state["stop_reason"] == "ANALYTICS_UNAVAILABLE"
    assert state["requests"] == len(client.queries) == len(store.reserved_ids) == 100
    assert state["pending"] is None


def test_twenty_thousand_candidate_scan_is_bounded_and_resumable():
    refs = [dict(reference(f"{i:05d}"), reference_group_count=2) for i in range(20000)]
    refs.append(reference("20000"))
    store, state = PagedStore(refs), report(1000)
    client = Client(store)
    state = run_now(worker.execute_backfill(store, client, state, quota_reader=quota_reader,
                    clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert state["status"] == "INCOMPLETE" and state["stop_reason"] == "SCAN_LIMIT"
    assert state["stats"]["scanned"] == 20000 and state["requests"] == 0
    assert state["cursor"][-1] == "19999" and store.page_limits == [100] * 200
    state.update(status="RUNNING")
    resumed = run_now(worker.execute_backfill(store, client, state, quota_reader=quota_reader,
                      clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert resumed["status"] == "COMPLETE" and store.reserved_ids == ["20000"]


def test_time_limit_keeps_last_reserved_cursor_and_can_resume():
    store = PagedStore([reference("1"), reference("2")])
    clock, client = Clock(), Client(store)
    async def slow_sleep(seconds):
        clock.elapsed += 45 * 60
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=quota_reader,
                    clock=lambda: NOW, sleep=slow_sleep, monotonic=clock.monotonic))
    assert state["status"] == "INCOMPLETE" and state["stop_reason"] == "TIME_LIMIT"
    assert state["requests"] == 1 and state["cursor"][-1] == "1"
    state.update(status="RUNNING", session_requests=0)
    resumed = run_now(worker.execute_backfill(store, client, state, quota_reader=quota_reader,
                      clock=lambda: NOW, sleep=clock.sleep, monotonic=clock.monotonic))
    assert resumed["status"] == "COMPLETE" and store.reserved_ids == ["1", "2"]


@pytest.mark.parametrize("new_run", [False, True])
def test_stale_quota_cannot_restore_allowance_after_restart_or_new_run(new_run):
    store = PagedStore([reference(f"{i:05d}") for i in range(2000)])
    client = Client(store)
    async def stale_quota(client):
        return quota(650)
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=stale_quota,
                    clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert state["requests"] == 150 and state["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    if new_run:
        next_state = report(2000)
        next_state["cursor"] = state["cursor"]
    else:
        next_state = deepcopy(state)
        next_state.update(status="RUNNING", session_requests=0)
    restarted = run_now(worker.execute_backfill(store, client, next_state, quota_reader=stale_quota,
                        clock=lambda: NOW+timedelta(hours=3), sleep=no_sleep, monotonic=lambda: 0))
    assert restarted["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    assert len(client.queries) == len(store.reserved_ids) == 150


def test_durable_quota_counts_committed_reservations_even_if_report_lags():
    windows = worker.quota_windows(quota(650), now=NOW)
    saved = report()
    saved.update(requests=10, session_requests=10)
    saved["quota"] = {"windows": deepcopy(windows), "global_requests_at_refresh": 0}
    budget = {"total_requests": 150, "receipts": [{"requests": 150, "report": saved}]}
    clipped = worker.conservative_quota_windows(windows, budget)
    assert clipped[0]["remaining"] == 500
    with pytest.raises(worker.BackfillStop, match="HEADROOM"):
        worker.allow_quota_request(clipped, 0, NOW)


def test_legacy_quota_bootstrap_counts_all_runs_and_does_not_restore_at_utc_midnight():
    windows = worker.quota_windows(quota(650), now=NOW)
    legacy = report()
    legacy.update(requests=150, session_requests=150)
    legacy["quota"] = {"windows": deepcopy(windows)}
    later = report()
    later.update(requests=100, session_requests=100)
    later["quota"] = {"windows": deepcopy(windows)}
    budget = {"total_requests": 250, "receipts": [{"report": legacy}, {"report": later}]}
    clipped = worker.conservative_quota_windows(windows, budget)
    assert clipped[0]["remaining"] == 400
    with pytest.raises(worker.BackfillStop, match="HEADROOM"):
        worker.allow_quota_request(clipped, 0, NOW+timedelta(hours=3))


def test_provider_window_reset_does_not_inherit_previous_window_consumption():
    old = worker.quota_windows(quota(650), now=NOW)
    saved = report()
    saved["quota"] = {"windows": old, "global_requests_at_refresh": 0}
    next_payload = quota(4999)
    next_payload["rateLimits"][0]["resources"][0]["rates"][0]["reset"] = "2026-10-30T07:00:00Z"
    fresh = worker.quota_windows(next_payload, now=NOW+timedelta(days=1))
    result = worker.conservative_quota_windows(fresh, {"total_requests": 2000, "receipts": [{"report": saved}]})
    assert result[0]["remaining"] == 4999
    worker.allow_quota_request(result, 0, NOW+timedelta(days=1))


@pytest.mark.parametrize("marker", [-1, 151, True])
def test_invalid_or_decreased_durable_quota_counter_stops(marker):
    windows = worker.quota_windows(quota(650), now=NOW)
    saved = report()
    saved["quota"] = {"windows": windows, "global_requests_at_refresh": marker}
    with pytest.raises(worker.BackfillStop, match="INVALID_DURABLE_QUOTA"):
        worker.conservative_quota_windows(windows, {"total_requests": 150, "receipts": [{"report": saved}]})


def test_deadline_reached_during_quota_refresh_prevents_next_reservation():
    store = PagedStore([reference(f"{i:05d}") for i in range(2000)])
    clock, client = Clock(), Client(store)
    async def slow_quota(client):
        if client.queries:
            clock.elapsed = 45 * 60
        return quota()
    state = run_now(worker.execute_backfill(store, client, report(2000), quota_reader=slow_quota,
                    clock=lambda: NOW, sleep=clock.sleep, monotonic=clock.monotonic))
    assert state["status"] == "INCOMPLETE" and state["stop_reason"] == "TIME_LIMIT"
    assert len(client.queries) == len(store.reserved_ids) == state["requests"] == 100
    assert state["pending"] is None


def test_cap_and_resume_never_repeat_reserved_reference():
    store = MemoryStore([reference("1"), reference("2"), reference("3")])
    client = Client(store)
    result = run_now(worker.execute_backfill(store, client, report(limit=2), quota_reader=quota_reader,
                     clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert len(client.queries) == 2 and result["cursor"][-1] == "2"
    assert result["status"] == "INCOMPLETE" and result["stop_reason"] == "REQUEST_LIMIT"
    result.update(status="RUNNING", session_requests=0)
    resumed = run_now(worker.execute_backfill(store, client, result, quota_reader=quota_reader,
                      clock=lambda: NOW, sleep=no_sleep, monotonic=lambda: 0))
    assert len(client.queries) == 3 and resumed["cursor"][-1] == "3"
    assert resumed["requests"] == 3 and resumed["status"] == "COMPLETE"


def test_provider_error_stops_once_and_keeps_reserved_cursor():
    store = MemoryStore([reference("1"), reference("2")])
    client = Client(store, EbayApiError("secret provider body", status_code=429, retryable=True))
    result = run_now(worker.execute_backfill(store, client, report(), quota_reader=quota_reader, clock=lambda: NOW))
    assert len(client.queries) == 1
    assert result["status"] == "STOPPED" and result["provider_status"] == 429
    assert result["cursor"][-1] == "1" and result["requests"] == 1
    assert "secret provider body" not in str(result)


def test_unsupported_parallel_skips_before_http():
    ref = reference()
    ref["reference_group_count"] = 2
    store = MemoryStore([ref])
    client = Client(store)
    result = run_now(worker.execute_backfill(store, client, report(), quota_reader=quota_reader, clock=lambda: NOW))
    assert client.queries == [] and result["requests"] == 0
    assert result["rejections"]["UNRESOLVED_PARALLEL_IDENTITY"] == 1


def test_every_relevant_quota_window_validated_and_headroom_retained():
    windows = worker.quota_windows(quota(), now=NOW)
    assert len(windows) == 1  # The unrelated bulk resource is not the search quota.
    worker.allow_quota_request(windows, 4498, NOW)
    with pytest.raises(worker.BackfillStop, match="HEADROOM"):
        worker.allow_quota_request(windows, 4499, NOW)
    invalid = quota()
    invalid["rateLimits"][0]["resources"][0]["rates"].append({"limit": 100, "remaining": 50})
    with pytest.raises(worker.BackfillStop, match="INVALID_ANALYTICS"):
        worker.quota_windows(invalid, now=NOW)
    with pytest.raises(worker.BackfillStop, match="EXPIRED"):
        worker.allow_quota_request(windows, 0, NOW + timedelta(days=1))


class Connection:
    def __init__(self, current=None, daily=0, fail_cache=False):
        self.current, self.daily, self.fail_cache = current, daily, fail_cache
        self.events, self.committed, self.pending = [], [], []
    @asynccontextmanager
    async def transaction(self, **kwargs):
        self.events.append("begin")
        self.pending = []
        try:
            yield
        except Exception:
            self.events.append("rollback")
            self.pending = []
            raise
        else:
            self.committed.extend(self.pending)
            self.events.append("commit")
            self.pending = []
    async def execute(self, sql, *params):
        self.events.append("execute")
    async def fetchrow(self, sql, *params):
        self.events.append("identity_recheck")
        return self.current
    async def fetchval(self, sql, *params):
        if "sum(requests)" in sql:
            return self.daily
        if "reserve_reference" in sql:
            self.events.append("budget_reservation")
            return self.daily + 1
        if sql.startswith("/*asking:history*/"):
            self.events.append("history")
            self.pending.append("history")
            return params[4]
        if sql.startswith("/*asking:cache*/"):
            self.events.append("cache")
            if self.fail_cache:
                raise RuntimeError("simulated cache failure")
            self.pending.append("cache")
            return params[0]
        self.events.append("receipt")
        return params[0]


@pytest.fixture
def sql_dependencies(monkeypatch):
    async def admin(connection):
        connection.events.append("admin")
    async def capacity(connection):
        connection.events.append("capacity")
        return SimpleNamespace(refresh_allowed=True)
    monkeypatch.setattr(worker, "require_platform_admin", admin)
    monkeypatch.setattr(worker, "check_database_capacity", capacity)


def ready(ref):
    rows = [{"item_id": str(123456789000+i), "seller_hash": str(i)*64,
             "title": "Public title", "price_gbp_minor": 1000+i, "shipping_gbp_minor": 200,
             "match_proof": {"card_number": "44"}} for i in range(3)]
    return {"status": "READY", "observed_at": NOW.isoformat(), "expires_at": (NOW+timedelta(days=3)).isoformat(),
            "estimate_minor": 1201, "estimate_low_minor": 1200, "estimate_high_minor": 1202,
            "sample_count": 3, "seller_count": 3, "selected_finish": "Normal", "confidence": "LOW",
            "method_version": "EBAY_UK_RAW_ASK_V1", "identity": {k: ref.get(k) for k in worker.IDENTITY},
            "comparables": rows}


def test_global_ledger_and_day_boundary_block_before_reservation(sql_dependencies):
    connection = Connection(daily=2000)
    store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
    with pytest.raises(worker.BackfillStop, match="DAILY_BROWSE_BUDGET"):
        run_now(store.reserve(report(), reference()))
    assert "budget_reservation" not in connection.events
    state = report()
    state["budget_day"] = "2026-10-27"
    with pytest.raises(worker.BackfillStop, match="UTC_DAY_CHANGED"):
        run_now(store.reserve(state, reference()))


def test_global_ledger_allows_last_request_of_two_thousand(sql_dependencies):
    connection = Connection(daily=1999)
    store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
    prior = report(2000)
    prior.update(requests=1999, session_requests=1999)
    state = run_now(store.reserve(prior, reference()))
    assert state["requests"] == state["session_requests"] == 2000
    assert connection.events.index("budget_reservation") < connection.events.index("receipt") < connection.events.index("commit")


def test_identity_or_current_evidence_race_never_writes_history(sql_dependencies):
    ref = reference()
    changed = dict(ref, name="Different Card")
    for current, reason in ((changed, "REFERENCE_IDENTITY_CHANGED"), (dict(ref, needs_price=False), "CURRENT_EVIDENCE_ALREADY_AVAILABLE")):
        connection = Connection(current)
        store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
        result = run_now(store.result(report(apply=True), ref, ready(ref)))
        assert not connection.committed
        assert result["stats"]["written"] == 0 and result["rejections"][reason] == 1


def test_history_cache_and_receipt_atomic_and_ordered(sql_dependencies):
    ref = reference()
    connection = Connection(ref)
    store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
    result = run_now(store.result(report(apply=True), ref, ready(ref)))
    assert connection.committed == ["history", "cache"]
    assert connection.events.index("identity_recheck") < connection.events.index("history") < connection.events.index("cache") < connection.events.index("receipt") < connection.events.index("commit")
    assert result["stats"]["written"] == 1
    failed = Connection(ref, fail_cache=True)
    original = report(apply=True)
    with pytest.raises(RuntimeError):
        run_now(worker.SqlBackfillStore(failed, ACTOR, clock=lambda: NOW).result(original, ref, ready(ref)))
    assert failed.committed == [] and failed.events[-1] == "rollback"
    assert original["stats"]["written"] == 0


@pytest.mark.parametrize("limit", [0, 2001, True])
def test_invalid_request_cap_rejected_before_database(limit):
    with pytest.raises(ValueError):
        run_now(worker.backfill_reference_asking(None, ACTOR, max_queries=limit))


def test_plan_cannot_silently_apply():
    with pytest.raises(ValueError):
        run_now(worker.backfill_reference_asking(None, ACTOR, apply=True))


def test_compact_evidence_keeps_every_median_member_without_seller_name():
    ref = reference()
    estimate = ready(ref)
    for row in estimate["comparables"]:
        row["seller_username"] = "PRIVATE_SELLER"
    evidence = worker.compact_evidence(estimate, ref, "a"*64)
    assert len(evidence["comparables"]) == estimate["sample_count"]
    assert evidence["shipping_context"] == worker.CONTEXT
    assert "PRIVATE_SELLER" not in str(evidence)
    assert "seller_username" not in str(evidence)


def test_sql_uses_current_coverage_guards_and_unfiltered_variant_group():
    assert "CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID" in worker.CANDIDATES_SQL
    assert "CARDMARKET_BULK_SINGLES" in worker.CANDIDATES_SQL
    assert "b.pricing_updated_at>=now()-interval '7 days'" in worker.CANDIDATES_SQL
    assert "from tcg.reference_cards other" in worker.GROUP_COUNT
    assert "needs_price" not in worker.GROUP_COUNT
    assert "_p[0-9]+$" in worker.GROUP_COUNT


def test_durable_resume_skips_pending_attempt_and_preserves_counter(sql_dependencies):
    prior = report()
    prior.update(cursor=worker.cursor_for(reference()), pending=worker.cursor_for(reference()))
    run_id = UUID(prior["run_id"])
    connection = Connection({"id": run_id, "actor_user_id": ACTOR, "report": prior,
                             "status": "RUNNING", "budget_day": NOW.date(), "requests": 3})
    resumed = run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).open_run(
        uuid4(), run_id, apply=False, scope=prior["scope"], digest=prior["benchmark_digest"], limit=25))
    assert resumed["run_id"] == str(run_id) and resumed["requests"] == 3
    assert resumed["cursor"] == prior["cursor"] and resumed["pending"] is None
    assert resumed["rejections"]["PRIOR_AMBIGUOUS_ATTEMPT_SKIPPED"] == 1


def test_closed_resume_starts_new_run_after_prior_cursor(sql_dependencies):
    prior = report()
    prior["cursor"] = worker.cursor_for(reference("9"))
    prior_id, new_id = UUID(prior["run_id"]), uuid4()
    connection = Connection({"id": prior_id, "actor_user_id": ACTOR, "report": prior,
                             "status": "INCOMPLETE", "budget_day": NOW.date(), "requests": 25})
    resumed = run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).open_run(
        new_id, prior_id, apply=False, scope=prior["scope"], digest=prior["benchmark_digest"], limit=25))
    assert resumed["run_id"] == str(new_id) and resumed["previous_run_id"] == str(prior_id)
    assert resumed["cursor"] == prior["cursor"] and resumed["requests"] == 0


def test_capacity_pause_prevents_reservation_and_price_writes(sql_dependencies, monkeypatch):
    async def full(connection):
        return SimpleNamespace(refresh_allowed=False, reason="BULK_REFRESH_DEFERRED_CAPACITY")
    monkeypatch.setattr(worker, "check_database_capacity", full)
    connection = Connection(reference())
    store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
    with pytest.raises(worker.BackfillStop, match="CAPACITY"):
        run_now(store.reserve(report(), reference()))
    with pytest.raises(worker.BackfillStop, match="CAPACITY"):
        run_now(store.result(report(apply=True), reference(), ready(reference())))
    assert "budget_reservation" not in connection.events and "history" not in connection.events
    assert connection.committed == []


def test_long_provider_deck_name_does_not_overconstrain_retrieval():
    ref = reference()
    ref.update(provider="Punk Records", system_code="ONE_PIECE_CARD_GAME",
               provider_id="OP02-054_r1", name="Gecko Moria", card_number="OP02-054",
               set_name="STARTER DECK -Blue Donquixote Doflamingo- [ST-17]", set_id="569017")
    before = deepcopy(ref)
    assert worker.search_query(ref) == "One Piece Gecko Moria OP02-054"
    assert ref == before


def test_short_retrieval_keeps_wrong_set_rejection():
    ref = reference()
    rows = [{"itemId": f"v1|{100000000000+i}|0", "seller": {"username": f"seller{i}"},
             "title": "Pokemon Bulbasaur 44 Base Set 2 English Normal Near Mint",
             "price": {"currency": "GBP", "value": "5.00"}, "buyingOptions": ["FIXED_PRICE"],
             "shippingOptions": [{"shippingCost": {"currency": "GBP", "value": "0.00"}}],
             "itemLocation": {"country": "GB"}, "condition": "Near Mint or Better"}
            for i in range(3)]
    assert worker.search_query(ref) == "Pokemon Bulbasaur 44"
    result = worker.estimate_reference_asking_price(ref, rows, observed_at=NOW, now=NOW)
    assert result["status"] == "INSUFFICIENT_COMPARABLES"
    assert result["estimate_minor"] is None

