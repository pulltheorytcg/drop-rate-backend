"""Pricing provider preflight must be bounded, read-only and source-aware."""
import pytest

from app.pricing_source_preflight import (
    compact_preflight_report, preview_cardtrader_expansions,
)
from scripts.probe_cardtrader_price_source import arguments


def report(**overrides):
    return {
        "source": "CARDTRADER_EXPANSION_ASKING",
        "dry_run": True,
        "provider_calls": 5,
        "sets_checked": 1,
        "references_examined": 80,
        "exact_printings": 24,
        "eligible_quotes": 2,
        "writes_attempted": 0,
        "writes_applied": 0,
        "inventory_writes": 0,
        "store_price_writes": 0,
        "provider_failures": 0,
        "cursor": "POKEMON_TCG:dp5",
        "by_release": {
            "POKEMON_TCG:dp5": {
                "references": 80, "matched": 24,
                "quotes": 2, "with_three_matching_sellers": 2,
                "writes": 0, "seller_username": "PRIVATE_SHOULD_NOT_LEAK",
            }
        },
        **overrides,
    }


@pytest.mark.asyncio
async def test_source_preflight_invokes_existing_engine_in_dry_run_only():
    calls = []

    async def fake_refresh(pool, actor, fx, client, **kwargs):
        calls.append(kwargs)
        return report()

    result = await preview_cardtrader_expansions(
        object(), object(), object(), object(),
        expansion_limit=1, previous_cursor="POKEMON_TCG:dp4",
        refresh=fake_refresh,
    )
    assert calls == [{
        "dry_run": True, "expansion_limit": 1,
        "previous_cursor": "POKEMON_TCG:dp4", "pricing_only": True,
    }]
    assert result["next_cursor"] == "POKEMON_TCG:dp5"
    assert result["selection"] == "MISSING_PRICES_ONLY"
    assert result["mode"] == "DRY_RUN"
    assert result["requests"] == 5
    assert result["eligible_quotes"] == 2
    assert result["cursor_moved"] is True
    assert result["catalogue_price_writes"] == 0
    assert result["inventory_writes"] == 0
    assert result["store_price_writes"] == 0
    assert result["evidence_kind"] == "ACTIVE_ASKING_NOT_SOLD"
    assert "PRIVATE_SHOULD_NOT_LEAK" not in str(result)
    assert "token" not in str(result).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 3, -1, True, "1"])
async def test_probe_rejects_unbounded_or_invalid_batch_before_api(limit):
    async def must_not_call(*args, **kwargs):
        raise AssertionError("must not call provider")
    with pytest.raises(ValueError):
        await preview_cardtrader_expansions(
            None, None, None, None, expansion_limit=limit,
            refresh=must_not_call,
        )


@pytest.mark.parametrize("changes", [
    {"dry_run": False},
    {"writes_attempted": 1},
    {"writes_applied": 1},
    {"inventory_writes": 1},
    {"store_price_writes": 1},
    {"by_release": {"a": {}, "b": {}, "c": {}}},
])
def test_probe_refuses_mutating_or_unbounded_provider_result(changes):
    with pytest.raises(ValueError):
        compact_preflight_report(report(**changes))


def test_cli_has_no_apply_option():
    assert arguments([]).max_expansions == 1
    assert arguments(["--max-expansions", "2"]).max_expansions == 2
    with pytest.raises(SystemExit):
        arguments(["--apply"])
    with pytest.raises(SystemExit):
        arguments(["--max-expansions", "10"])



def test_source_preflight_exposes_safe_provider_failure_and_offer_scarcity():
    incomplete = report(
        provider_failures=1, reason="CardTraderApiError",
        by_release={
            "POKEMON_TCG:dp5": {
                "references": 80, "missing_before": 42,
                "matched": 24, "blueprints_with_offers": 2,
                "candidate_source_offers": 6,
                "with_three_matching_sellers": 0, "quotes": 0,
                "error_type": "CardTraderApiError", "http_status": 403,
                "error_detail": "PRIVATE_RAW_UPSTREAM_TOKEN",
                "seller_username": "PRIVATE_SELLER",
            }
        },
    )
    safe = compact_preflight_report(incomplete)
    assert safe["failure_class"] == "CardTraderApiError"
    first = safe["by_release"][0]
    assert first["references"] == 80
    assert first["missing_before"] == 42
    assert first["blueprints_with_offers"] == 2
    assert first["candidate_source_offers"] == 6
    assert first["http_status"] == 403
    assert first["failure_class"] == "CardTraderApiError"
    assert "PRIVATE" not in str(safe)
