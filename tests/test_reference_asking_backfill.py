"""Budget, resume and transaction failure tests with no sockets or credentials."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import reference_asking_backfill as worker
from app.ebay_official_client import EbayApiError

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
    async def checkpoint(self, state):
        self.events.append("checkpoint_commit")
    async def candidates(self, cursor, scope, limit):
        after = worker.validated_cursor(cursor)
        return [r for r in self.references if worker.cursor_for(r) > after][:limit]
    async def reserve(self, state, ref):
        state = deepcopy(state)
        state.update(cursor=worker.cursor_for(ref), pending=worker.cursor_for(ref),
                     requests=state["requests"] + 1, session_requests=state["session_requests"] + 1)
        self.events.append("reservation_commit")
        return state
    async def result(self, state, ref, estimate):
        state = deepcopy(state)
        state["pending"] = None
        self.events.append("result_commit")
        return state
    async def finish(self, state):
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
    connection = Connection(daily=500)
    store = worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW)
    with pytest.raises(worker.BackfillStop, match="DAILY_BROWSE_BUDGET"):
        run_now(store.reserve(report(), reference()))
    assert "budget_reservation" not in connection.events
    state = report()
    state["budget_day"] = "2026-10-27"
    with pytest.raises(worker.BackfillStop, match="UTC_DAY_CHANGED"):
        run_now(store.reserve(state, reference()))


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


@pytest.mark.parametrize("limit", [0, 501, True])
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
