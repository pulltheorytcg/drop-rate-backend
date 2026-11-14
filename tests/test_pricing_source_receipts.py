"""CardTrader provider preflight audit receipts never write prices or leak secrets."""
from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app import pricing_source_receipts as receipts

ACTOR = UUID("00000000-0000-0000-0000-000000000001")
RECEIPT = UUID("00000000-0000-0000-0000-000000000012")


def example(**kwargs):
    return {
        "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
        "status": "COMPLETE",
        "source": "CARDTRADER_EXPANSION_ASKING",
        "mode": "DRY_RUN", "evidence_kind": "ACTIVE_ASKING_NOT_SOLD",
        "requests": 5, "expansions": 1,
        "requested_expansions": 1,
        "canonical_references_examined": 144,
        "exact_printings": 35, "eligible_quotes": 3,
        "provider_failures": 0,
        "bulk_writer_hold_preserved": True,
        "inventory_writes": 0, "store_price_writes": 0,
        "catalogue_price_writes": 0,
        "by_release": [{
            "release": "POKEMON_TCG:dp5", "references": 144,
            "exact_printings": 35, "three_seller_candidates": 3,
            "qualified_quotes": 3, "provider_failed": False,
            "seller_name": "PRIVATE",
            "raw_api": {"authorization": "Bearer PRIVATE"},
        }],
        "api_key": "PRIVATE",
        **kwargs,
    }


def test_receipt_only_keeps_aggregates_and_drops_seller_metadata():
    receipt = receipts.safe_receipt(example())
    assert receipt["requests"] == 5
    assert receipt["eligible_quotes"] == 3
    assert receipt["by_release"][0]["release"] == "POKEMON_TCG:dp5"
    assert "PRIVATE" not in str(receipt)
    assert "token" not in str(receipt).lower()
    assert "api_key" not in str(receipt)


@pytest.mark.parametrize("changes", [
    {"catalogue_price_writes": 1},
    {"store_price_writes": 1},
    {"inventory_writes": 1},
    {"status": "WRITING"},
    {"requests": -1},
    {"requests": 8},
    {"requests": "5"},
    {"expansions": 3},
    {"by_release": [{}, {}, {}]},
])
def test_receipt_rejects_unsafe_or_unbounded_evidence(changes):
    with pytest.raises(ValueError):
        receipts.safe_receipt(example(**changes))


@pytest.mark.asyncio
async def test_audit_creates_new_job_and_updates_only_its_run(monkeypatch):
    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))
            return "INSERT 0 1"

        async def fetchval(self, sql, *args):
            calls.append(("fetchval", sql, args))
            return RECEIPT

    @asynccontextmanager
    async def user_connection(pool, actor, request_id):
        assert pool is not None and actor == ACTOR
        assert request_id.startswith("cardtrader-preflight-")
        yield Connection()

    async def admin(connection):
        calls.append(("admin", "", ()))

    monkeypatch.setattr(receipts, "user_connection", user_connection)
    monkeypatch.setattr(receipts, "require_platform_admin", admin)

    assert await receipts.begin_preflight_receipt(object(), ACTOR, RECEIPT,
                                                 expansion_limit=1) == RECEIPT
    assert await receipts.complete_preflight_receipt(object(), ACTOR, RECEIPT,
                                                     example()) == RECEIPT

    statements = [entry for entry in calls if entry[0] != "admin"]
    assert len(statements) == 2
    assert "insert into tcg.catalogue_job_runs" in statements[0][1]
    assert "update tcg.catalogue_job_runs" in statements[1][1]
    assert statements[0][2][1] == statements[1][2][1] == receipts.JOB
    assert statements[0][2][1] != "CARDTRADER_EXPANSION_GUIDES"
    assert statements[1][2][2] == "COMPLETE"
    assert "reference_market_prices" not in str(statements)
    assert "reference_catalogue_prices" not in str(statements)
    assert "tcg.inventory" not in " ".join(statement[1] for statement in statements).lower()


@pytest.mark.asyncio
async def test_failure_receipt_is_terminal_and_does_not_invent_provider_calls(monkeypatch):
    calls = []

    class Connection:
        async def fetchval(self, sql, *args):
            calls.append(args)
            return RECEIPT

    @asynccontextmanager
    async def user_connection(*args):
        yield Connection()

    async def admin(connection):
        pass

    monkeypatch.setattr(receipts, "user_connection", user_connection)
    monkeypatch.setattr(receipts, "require_platform_admin", admin)
    failure = {
        "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
        "status": "FAILED", "error_class": "CardTraderApiError",
        "catalogue_price_writes": 0, "inventory_writes": 0,
        "store_price_writes": 0,
    }
    await receipts.complete_preflight_receipt(object(), ACTOR, RECEIPT, failure)
    assert calls[0][2] == "FAILED"
    assert '"requests"' not in calls[0][3]  # unknown calls are not reported as zero


@pytest.mark.asyncio
async def test_completed_job_cannot_be_written_without_matching_receipt(monkeypatch):
    class Connection:
        async def fetchval(self, sql, *args):
            return None
    @asynccontextmanager
    async def user_connection(*args):
        yield Connection()
    async def admin(_connection):
        pass

    monkeypatch.setattr(receipts, "user_connection", user_connection)
    monkeypatch.setattr(receipts, "require_platform_admin", admin)
    with pytest.raises(RuntimeError, match="already terminal"):
        await receipts.complete_preflight_receipt(object(), ACTOR, RECEIPT, example())
