"""Finite transient probes respect quota, identity scope and read-only storage."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "probe_uk_eu_market", Path(__file__).parents[1] / "backend/scripts/probe_uk_eu_market.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 11, 4, 20, tzinfo=timezone.utc)
KEY = ["TCGdex", "POKEMON_TCG", "English", "swsh4-25"]


def complete(coroutine):
    """Every dependency is an immediate fake, so no OS event loop is needed."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("A mocked probe unexpectedly performed real async I/O")


def reference():
    return dict(zip(probe.KEYS, KEY)) | {"name": "Charizard", "card_number": "25/185"}


def quota(remaining=1000):
    return {"rateLimits": [{"apiContext": "buy", "apiName": "browse", "resources": [
        {"name": "buy.browse", "rates": [{"limit": 5000, "remaining": remaining,
        "count": 5000-remaining, "timeWindow": 86400,
        "reset": (NOW+timedelta(hours=1)).isoformat()}]}]}]}


class Client:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def search_items(self, **kwargs):
        self.calls.append(("search", kwargs))
        if self.fail:
            raise probe.EbayApiError("private credential must never be printed", status_code=429,
                                     retry_after_seconds=60)
        return {"itemSummaries": [{"itemId": "v1|123|0"}]}

    async def get_item(self, item_id):
        self.calls.append(("detail", item_id))
        return {"itemId": item_id, "title": "Charizard", "seller": {"username": "private-seller"},
                "description": "private-data"}


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(probe, "reference_asking_eligibility", lambda ref: None)
    monkeypatch.setattr(probe, "search_query", lambda ref: "Charizard 25/185")
    monkeypatch.setattr(probe, "item_detail_candidates", lambda ref, summaries: ["v1|123|0", "v1|124|0", "v1|125|0"])
    async def quota_reader(client):
        return quota()
    tick = [0.0]
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
        tick[0] += seconds
    def estimator(ref, rows, **kwargs):
        return {"status": "READY", "observed_at": NOW.isoformat(), "sample_count": 3,
                "seller_count": 3, "selected_finish": "Normal", "estimate_minor": 550,
                "rejection_counts": {}, "comparables": rows}
    def model(ref, report, **kwargs):
        return {"status": "READY", "method": "DROP_RATE_UK_EU_MARKET_V1",
                "estimate_minor": 425, "shipping_basis": "ITEM_ONLY",
                "physical_valuation_eligible": False, "private": "must-not-leak"}
    return dict(quota_reader=quota_reader, clock=lambda: NOW,
                monotonic=lambda: tick[0], sleep=sleep, estimator=estimator, model=model), delays


def test_probe_counts_and_paces_search_and_details_without_private_output(harness):
    options, delays = harness
    client = Client()
    report = complete(probe.probe_references([reference()], client, **options))
    assert report["status"] == "COMPLETE"
    assert (report["requests"], report["search_requests"], report["detail_requests"]) == (4, 1, 3)
    assert delays == [1.0, 1.0, 1.0]
    assert report["results"][0]["model"]["estimate_minor"] == 425
    assert "private" not in json.dumps(report)
    assert all(report[k] == 0 for k in ("database_writes", "price_writes", "inventory_writes", "store_price_writes"))
    assert client.calls[0][1]["fixed_price_only"] is True
    assert client.calls[0][1]["item_location_country"] == "GB"


def test_budget_is_global_and_failed_attempts_are_counted(harness):
    options, _ = harness
    client = Client()
    report = complete(probe.probe_references([reference()], client, max_requests=2, **options))
    assert report["status"] == "STOPPED" and report["stop_reason"] == "REQUEST_LIMIT"
    assert report["requests"] == len(client.calls) == 2
    assert "model" not in report["results"][0]
    failed = Client(fail=True)
    report = complete(probe.probe_references([reference()], failed, **options))
    assert report["requests"] == len(failed.calls) == 1
    assert report["provider_status"] == 429 and report["retry_after_seconds"] == 60
    assert "private" not in json.dumps(report)


def test_budget_is_not_reset_for_the_next_reference(harness):
    options, _ = harness
    second = reference() | {"provider_id": "swsh7-49"}
    client = Client()
    report = complete(probe.probe_references([reference(), second], client, max_requests=5, **options))
    assert report["stop_reason"] == "REQUEST_LIMIT"
    assert report["requests"] == len(client.calls) == 5
    assert report["search_requests"] == 2 and report["detail_requests"] == 3
    assert report["results"][0]["status"] == "READY"
    assert "model" not in report["results"][1]


def test_insufficient_provider_headroom_stops_before_browse(harness):
    options, _ = harness
    async def exhausted(client):
        return quota(500)
    client = Client()
    report = complete(probe.probe_references([reference()], client, **(options | {"quota_reader": exhausted})))
    assert report["stop_reason"] == "BROWSE_QUOTA_HEADROOM"
    assert report["requests"] == 0 and client.calls == []


def test_invalid_quota_and_unexpected_provider_failure_are_bounded(harness):
    options, _ = harness
    async def invalid(client):
        return {}
    report = complete(probe.probe_references([reference()], Client(), **(options | {"quota_reader": invalid})))
    assert report["stop_reason"] == "INVALID_ANALYTICS_QUOTA" and report["requests"] == 0
    class Broken(Client):
        async def search_items(self, **kwargs):
            raise RuntimeError("secret")
    report = complete(probe.probe_references([reference()], Broken(), **options))
    assert report["status"] == "FAILED" and report["error_class"] == "RuntimeError"
    assert report["requests"] == 1 and "secret" not in json.dumps(report)


@pytest.mark.parametrize("keys", [[], [KEY]*2, [KEY]*4, [["", *KEY[1:]]], [[" TCGdex", *KEY[1:]]], [KEY[:3]], [[True, *KEY[1:]]]])
def test_invalid_or_duplicate_reference_scopes_are_rejected(keys):
    with pytest.raises(ValueError):
        probe.reference_keys(keys)


@pytest.mark.parametrize("budget", [0, 26, True, 1.5])
def test_invalid_budgets_rejected(budget):
    with pytest.raises(ValueError):
        probe.report_base([KEY], budget, run=False)


def test_default_cli_plan_does_not_load_credentials_or_database(monkeypatch, capsys):
    monkeypatch.setattr(probe.Settings, "from_env", lambda: pytest.fail("Plan loaded settings"))
    assert probe.main(["--reference-key", json.dumps(KEY)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PLAN_ONLY" and report["requests"] == 0


def test_run_probe_uses_authorized_readonly_snapshot_and_always_unlocks(monkeypatch):
    events = []
    class Context:
        def __init__(self, value): self.value = value
        async def __aenter__(self): return self.value
        async def __aexit__(self, *args): return False
    class Connection:
        async def fetch(self, sql, keys):
            assert sql.lstrip().lower().startswith("select")
            assert json.loads(keys) == [dict(zip(probe.KEYS, KEY))]
            return [reference()]
        async def fetchval(self, sql, lock):
            events.append((sql, lock))
            return True
    connection = Connection()
    class Pool:
        def acquire(self): return Context(connection)
        async def close(self): events.append("closed")
    pool = Pool()
    async def create(settings): return pool
    def user_connection(p, actor, request, **kwargs):
        assert p is pool and kwargs == {"readonly_snapshot": True}
        events.append("readonly")
        return Context(connection)
    async def admin(conn): events.append("authorized")
    async def broken(*args, **kwargs): raise RuntimeError("probe failure")
    monkeypatch.setattr(probe, "create_pool", create)
    monkeypatch.setattr(probe, "user_connection", user_connection)
    monkeypatch.setattr(probe, "require_platform_admin", admin)
    monkeypatch.setattr(probe, "EbayOfficialClient", lambda **kwargs: object())
    monkeypatch.setattr(probe, "probe_references", broken)
    settings = SimpleNamespace(catalogue_maintenance_actor_user_id="00000000-0000-0000-0000-000000000001",
        ebay_marketplace_id="EBAY_GB", ebay_client_id="private", ebay_client_secret="private",
        ebay_origin_postcode="SW1A 1AA")
    with pytest.raises(RuntimeError):
        complete(probe.run_probe(settings, [KEY], max_requests=25))
    assert events[:2] == ["readonly", "authorized"]
    assert "pg_try_advisory_lock" in events[2][0]
    assert "pg_advisory_unlock" in events[3][0]
    assert events[-1] == "closed"
