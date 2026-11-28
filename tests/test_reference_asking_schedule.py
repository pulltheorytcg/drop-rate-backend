import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import reference_asking_schedule as schedule
from app.reference_asking_backfill import BackfillStop, MAX_DAILY, normalize_reference_keys

NOW = datetime(2026, 11, 28, 9, 20, tzinfo=timezone.utc)
ACTOR = UUID("00000000-0000-0000-0000-0000000000aa")


def settings(**changes):
    value = dict(ebay_asking_schedule_enabled=True, ebay_client_id="id", ebay_client_secret="secret",
                 ebay_marketplace_id="EBAY_GB", ebay_origin_postcode="AB1 2CD",
                 catalogue_maintenance_actor_user_id=str(ACTOR))
    value.update(changes)
    return SimpleNamespace(**value)


def key(number, *, system="POKEMON_TCG", provider="TCGdex", language="English", guide=0):
    return {"provider": provider, "system_code": system, "language": language,
            "provider_id": f"card-{number:03d}", "guide_minor": guide}


@pytest.mark.parametrize("change", [
    {"ebay_asking_schedule_enabled": False}, {"ebay_client_id": None}, {"ebay_client_secret": ""},
    {"ebay_marketplace_id": "EBAY_US"}, {"ebay_origin_postcode": None},
    {"catalogue_maintenance_actor_user_id": None}])
def test_schedule_needs_the_uk_application_postcode_and_actor(change):
    assert schedule.schedule_enabled(settings()) is True
    assert schedule.schedule_enabled(settings(**change)) is False


def test_one_run_per_utc_hour_and_none_once_todays_allowance_is_spent():
    hour = NOW.replace(minute=0)
    assert schedule.schedule_due(None, NOW, 0) is True
    assert schedule.schedule_due(hour - timedelta(seconds=1), NOW, 0) is True
    assert schedule.schedule_due(hour, NOW, 0) is False
    assert schedule.schedule_due(NOW - timedelta(minutes=5), NOW, 0) is False
    assert schedule.schedule_due(None, NOW, MAX_DAILY - schedule.DAILY_HEADROOM) is False
    assert schedule.schedule_due(None, NOW, MAX_DAILY - schedule.DAILY_HEADROOM - 1) is True


def test_stock_comes_first_then_highest_guide_and_busy_cards_are_left_out():
    stock = [key(3), key(1), key(2)]
    guide = [key(10, guide=500), key(11, guide=9000), key(1, guide=7000), key(12, guide=9000)]
    busy = [key(2), key(11)]
    keys, held = schedule.candidate_keys(stock, guide, busy)
    assert held == {schedule._key(key(1)), schedule._key(key(3))}
    assert keys == [schedule._key(key(n)) for n in (1, 3, 12, 10)]


def test_stock_is_never_crowded_out_by_the_validation_limit():
    stock = [key(n) for n in range(300)]
    guide = [key(n, guide=n) for n in range(300, 900)]
    keys, held = schedule.candidate_keys(stock, guide, [], limit=200)
    assert len(held) == 300 and len(keys) == 300
    assert set(keys) == held
    keys, _ = schedule.candidate_keys(stock[:50], guide, [], limit=200)
    assert len(keys) == 200 and keys[:50] == sorted(schedule._key(row) for row in stock[:50])


def test_targets_are_stock_by_value_then_catalogue_and_fit_the_collector():
    held = {schedule._key(key(1)), schedule._key(key(2))}
    valid = [key(5, guide=90_000), key(1, guide=100), key(2, guide=4_000), key(6, guide=95_000)]
    targets = schedule.target_keys(valid, held)
    assert [target[3] for target in targets] == ["card-002", "card-001", "card-006", "card-005"]
    many = [key(n, guide=n) for n in range(100)]
    bounded = schedule.target_keys(many, set())
    assert len(bounded) == schedule.TARGETS_PER_RUN
    # Whatever is chosen must be accepted by the collector's own validation.
    assert normalize_reference_keys(bounded) == sorted(bounded)
    long = [dict(key(n, guide=n), provider_id="x" * 400 + str(n)) for n in range(25)]
    assert len(json.dumps(schedule.target_keys(long, set())).encode()) <= 4000


class Connection:
    def __init__(self, *, last_started=None, used_today=0, stock=(), guide=(), busy=(), valid=None):
        self.state = {"last_started": last_started, "used_today": used_today}
        self.stock, self.guide, self.busy, self.valid = list(stock), list(guide), list(busy), valid
        self.queries = []

    async def fetchrow(self, sql, *args):
        self.queries.append("state")
        assert sql is schedule.STATE_SQL and args == (ACTOR,)
        return self.state

    async def fetch(self, sql, *args):
        if sql is schedule.STOCK_SQL:
            self.queries.append("stock"); return self.stock
        if sql is schedule.TOP_GUIDE_SQL:
            self.queries.append("guide")
            assert args == (schedule.SYSTEMS, schedule.LANGUAGES, schedule.CATALOGUE_POOL)
            return self.guide
        if sql is schedule.BUSY_SQL:
            self.queries.append("busy")
            assert args == (NOW - schedule.ATTEMPT_MEMORY,)
            return self.busy
        assert sql is schedule.VALID_SQL
        self.queries.append("valid")
        wanted = [tuple(item[name] for name in schedule.KEYS) for item in json.loads(args[0])]
        rows = self.valid if self.valid is not None else self.stock + self.guide
        return [row for row in rows if schedule._key(row) in wanted]


@pytest.fixture
def wired(monkeypatch):
    def wire(connection):
        @asynccontextmanager
        async def user_connection(pool, actor, request_id):
            assert actor == ACTOR and request_id.startswith("asking-schedule-")
            yield connection

        async def admin(found):
            assert found is connection

        monkeypatch.setattr(schedule, "user_connection", user_connection)
        monkeypatch.setattr(schedule, "require_platform_admin", admin)
    return wire


def run(coroutine):
    return asyncio.run(coroutine)


def collector(calls, report=None, error=None):
    async def collect(pool, actor, client, **options):
        calls.append({"actor": actor, "client": client, **options})
        if error:
            raise error
        return report or {"status": "COMPLETE", "run_id": "run", "session_requests": 9,
                          "stats": {"collected": 3, "matched": 2, "written": 2}, "rejections": {}}
    return collect


def test_pass_asks_about_stock_first_with_the_collectors_write_and_scope_options(wired):
    connection = Connection(stock=[key(1), key(2)], guide=[key(9, guide=5000)])
    wired(connection)
    calls = []
    result = run(schedule.scheduled_asking_pass("pool", ACTOR, settings(), now=NOW, client="client",
                                                collect=collector(calls)))
    assert connection.queries == ["state", "stock", "guide", "busy", "valid"]
    assert len(calls) == 1
    call = calls[0]
    assert call["actor"] == ACTOR and call["client"] == "client"
    assert call["run"] is True and call["apply"] is True and call["include_priced"] is True
    assert call["max_queries"] == schedule.MAX_QUERIES_PER_RUN and call["postcode"] == "AB1 2CD"
    assert [target[3] for target in call["reference_keys"]] == ["card-001", "card-002", "card-009"]
    assert result == {"status": "COMPLETE", "stop_reason": None, "run_id": "run", "targets": 3,
                      "stock_targets": 2, "requests": 9, "searched": 3, "priced": 2, "written": 2,
                      "rejections": {}}


@pytest.mark.parametrize("connection", [
    Connection(last_started=NOW - timedelta(minutes=10), stock=[key(1)]),
    Connection(used_today=MAX_DAILY, stock=[key(1)]),
    Connection(),
    Connection(stock=[key(1)], busy=[key(1)]),
    Connection(stock=[key(1)], valid=[]),
])
def test_pass_makes_no_ebay_call_when_not_due_or_nothing_to_ask(wired, connection):
    wired(connection)
    calls = []
    assert run(schedule.scheduled_asking_pass("pool", ACTOR, settings(), now=NOW, client="client",
                                              collect=collector(calls))) is None
    assert calls == []


def test_disabled_schedule_reads_nothing(wired):
    connection = Connection(stock=[key(1)])
    wired(connection)
    calls = []
    assert run(schedule.scheduled_asking_pass("pool", ACTOR, settings(ebay_origin_postcode=None),
                                              now=NOW, client="client", collect=collector(calls))) is None
    assert connection.queries == [] and calls == []


@pytest.mark.parametrize("error,status,reason", [
    (BackfillStop("BACKFILL_ALREADY_RUNNING"), "STOPPED", "BACKFILL_ALREADY_RUNNING"),
    (ValueError("bad"), "STOPPED", "ValueError"),
])
def test_collector_refusal_is_reported_not_raised(wired, error, status, reason):
    wired(Connection(stock=[key(1)]))
    result = run(schedule.scheduled_asking_pass("pool", ACTOR, settings(), now=NOW, client="client",
                                                collect=collector([], error=error)))
    assert result == {"status": status, "stop_reason": reason, "targets": 1, "stock_targets": 1}


def test_a_slow_collector_is_cut_off(wired, monkeypatch):
    wired(Connection(stock=[key(1)]))
    monkeypatch.setattr(schedule, "RUN_TIMEOUT_SECONDS", 0.01)

    async def slow(*args, **options):
        await asyncio.sleep(1)

    result = run(schedule.scheduled_asking_pass("pool", ACTOR, settings(), now=NOW, client="client",
                                                collect=slow))
    assert result == {"status": "TIMEOUT", "targets": 1, "stock_targets": 1}


def test_selection_sql_reads_only_and_keeps_the_collectors_cursor_order():
    for sql in (schedule.STATE_SQL, schedule.STOCK_SQL, schedule.TOP_GUIDE_SQL,
                schedule.BUSY_SQL, schedule.VALID_SQL):
        lowered = " " + " ".join(sql.lower().split()) + " "
        assert not any(word in lowered for word in (" insert ", " update ", " delete ", " truncate "))
    assert "i.status='APPROVED'" in schedule.STOCK_SQL
    assert "(k->>0,k->>1,k->>2,k->>3)<=" in schedule.BUSY_SQL
    assert "expires_at>now()" in schedule.BUSY_SQL
    assert "release_date<=current_date" in schedule.VALID_SQL
