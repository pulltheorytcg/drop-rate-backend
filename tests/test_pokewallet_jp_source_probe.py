from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest


PATH = Path(__file__).resolve().parents[1] / "backend/scripts/pokewallet_jp_source_probe.py"
spec = importlib.util.spec_from_file_location("pokewallet_jp_source_probe_tests", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
KEY = "pk_live_never_print_this_key"
QUOTA = {"X-RateLimit-Remaining-Hour": "60", "X-RateLimit-Remaining-Day": "600"}


def source_set(code="ADV2", set_id="-4", count=2):
    return {"set_code": code, "set_id": set_id, "name": "Miracle of the Desert",
            "language": "jap", "card_count": count, "release_date": "18th April, 2003"}


def card(index=1, code="ADV2", set_id="-4"):
    return {"id": f"{index:064x}", "card_info": {"name": "Fixture card", "set_code": code,
            "set_id": set_id, "card_number": f"{index}/053", "product_type": "card"},
            "cardmarket": {"product_url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/Miracle-of-the-Desert/Fixture-Card",
                           "prices": [{"variant_type": "normal", "trend": 1.23, "avg30": 0,
                                       "updated_at": "2026-10-28T09:00:00Z"}]}}


def search(rows, code="ADV2", total=None):
    total = len(rows) if total is None else total
    return {"query": code, "results": rows,
            "pagination": {"page": 1, "limit": 100, "total": total, "total_pages": (total + 99) // 100}}


async def run(sets=None, responses=None, *, headers=None, **kwargs):
    sets = [source_set()] if sets is None else sets
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.pokewallet.io"
        assert request.headers["X-API-Key"] == KEY
        if request.url.path == "/sets":
            body = {"success": True, "data": sets, "total": len(sets)}
        else:
            assert request.url.path == "/search"
            assert dict(request.url.params) == {"q": request.url.params["q"], "page": "1", "limit": "100"}
            body = responses.get(request.url.params["q"]) if responses is not None else search([card(), card(2)])
        return httpx.Response(200, json=body, headers=QUOTA if headers is None else headers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await probe.run_probe(execute=True, api_key=KEY, http_client=client, **kwargs)
    return result, calls


@pytest.mark.asyncio
async def test_no_opt_in_does_not_load_credentials_or_make_requests(monkeypatch):
    monkeypatch.setattr(probe.os, "getenv", lambda *_: (_ for _ in ()).throw(AssertionError("no secret read")))
    result = await probe.run_probe()
    assert result["status"] == "SKIPPED" and result["requests"] == 0
    assert result["database_writes"] == 0 and result["persisted"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("codes", [["ADV2", "ADV2"], ["ADV2", "adv2"], ["ADV2", "DP1", "DP2"],
                                  ["../prices"], ["-4"], ["ADV2?api_key=secret"], [123]])
async def test_invalid_targets_stop_before_credentials_or_network(codes, monkeypatch):
    monkeypatch.setattr(probe.os, "getenv", lambda *_: (_ for _ in ()).throw(AssertionError("no secret read")))
    result = await probe.run_probe(execute=True, set_codes=codes)
    assert result["reason"] == "INVALID_SET_CODES" and result["requests"] == 0


@pytest.mark.asyncio
async def test_two_negative_japanese_sets_use_at_most_three_calls_and_no_price_values():
    sets = [source_set(), source_set("DP1", "-5", 1), source_set("DP2", "-6", 1)]
    responses = {"ADV2": search([card(), card(2)]), "DP1": search([card(3, "DP1", "-5")], "DP1")}
    result, calls = await run(sets, responses)
    assert len(calls) == result["requests"] == 3
    assert result["status"] == "COMPLETE" and len(result["targets"]) == 2
    assert all(target["complete_source_set"] for target in result["targets"])
    first = result["targets"][0]
    assert first["page_shape"]["cards_with_positive_trend"] == 2
    assert first["page_shape"]["full_collector_fractions"] == 2
    assert first["preview"][0]["prices"][0]["positive"]["trend"] is True
    assert first["printing_matches_claimed"] == 0
    output = json.dumps(result)
    assert KEY not in output and "1.23" not in output and "price_gbp" not in output


@pytest.mark.asyncio
async def test_selected_targets_are_checked_against_full_japanese_set_list():
    sets = [source_set(), source_set("DP1", "-5", 1)]
    result, calls = await run(sets, {"DP1": search([card(3, "DP1", "-5")], "DP1")}, set_codes=["dp1"])
    assert result["requests"] == 2 and calls[-1].url.params["q"] == "DP1"
    result, calls = await run(sets, set_codes=["SV1"])
    assert result["reason"] == "TARGET_NOT_IN_NEGATIVE_JAPANESE_SETS" and len(calls) == 1


@pytest.mark.asyncio
async def test_colliding_codes_ids_and_positive_ids_are_not_probed():
    rows = [source_set(), source_set("adv2", "-8"), source_set("DP1", "100"),
            source_set("DP2", "-9"), source_set("DP3", "-9")]
    result, calls = await run(rows)
    assert result["reason"] == "NO_NEGATIVE_ID_JAPANESE_TARGETS"
    assert result["set_summary"]["unique_code_candidates"] == 0 and len(calls) == 1


@pytest.mark.asyncio
async def test_page_statistics_cover_all_rows_but_preview_is_bounded_and_redacted():
    rows = [card(index) for index in range(1, 9)]
    rows[0]["card_info"]["name"] = KEY
    rows[0]["cardmarket"]["prices"][0][KEY] = KEY
    rows[5]["card_info"]["card_number"] = "6"
    rows[6]["cardmarket"]["prices"][0].update(trend=0, avg30=3)
    rows[7]["cardmarket"] = None
    result, _ = await run([source_set(count=8)], {"ADV2": search(rows)})
    report = result["targets"][0]
    assert len(report["preview"]) == 5 and report["preview"][0]["name"] is None
    assert report["page_shape"]["numeric_only_numbers"] == 1
    assert report["page_shape"]["cards_with_positive_trend"] == 6
    assert report["page_shape"]["cards_with_positive_avg30"] == 1
    assert report["page_shape"]["cardmarket_missing"] == 1
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["more_pages", "wrong_count", "duplicate_id", "wrong_code"])
async def test_incomplete_or_conflicting_source_set_cannot_emit_printing_preview(reason):
    rows = [card(index) for index in range(1, 101)] if reason == "more_pages" else [card(), card(2)]
    total = 101 if reason == "more_pages" else len(rows)
    expected = 3 if reason == "wrong_count" else total
    if reason == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    if reason == "wrong_code":
        rows[1]["card_info"]["set_code"] = "DP1"
    result, calls = await run([source_set(count=expected)], {"ADV2": search(rows, total=total)})
    report = result["targets"][0]
    assert report["complete_source_set"] is False and report["scope"] == "PAGE_ONLY"
    assert report["preview"] == [] and report["printing_matches_claimed"] == 0
    assert len(calls) == 2  # No pagination requests beyond the reviewed first page.


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,reason", [({}, "QUOTA_HEADERS_UNAVAILABLE"),
    ({**QUOTA, "X-RateLimit-Remaining-Hour": "invalid"}, "QUOTA_HEADERS_UNAVAILABLE"),
    ({**QUOTA, "X-RateLimit-Remaining-Hour": "5"}, "PROVIDER_BUDGET_LOW"),
    ({**QUOTA, "X-RateLimit-Remaining-Day": "4"}, "PROVIDER_BUDGET_LOW")])
async def test_missing_or_low_quota_stops_without_retry(headers, reason):
    result, calls = await run(headers=headers)
    assert result["status"] == "INCOMPLETE" and result["reason"] == reason and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(429, "RATE_LIMITED"), (302, "UPSTREAM_HTTP_302"), (500, "UPSTREAM_HTTP_500")])
async def test_provider_errors_or_redirects_never_leak_body_or_forward_key(status, reason):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text=KEY, headers={**QUOTA, "Location": "https://elsewhere.invalid/"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        result = await probe.run_probe(execute=True, api_key=KEY, http_client=client)
    assert len(calls) == 1 and result["reason"] == reason and KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_response_byte_cap_and_network_exception_are_sanitized(monkeypatch):
    monkeypatch.setattr(probe, "MAX_BYTES", 30)
    result, calls = await run()
    assert result["reason"] == "RESPONSE_TOO_LARGE" and len(calls) == 1
    def fail(request):
        raise httpx.ConnectError(KEY, request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        result = await probe.run_probe(execute=True, api_key=KEY, http_client=client)
    assert result["reason"] == "CONFIGURATION_OR_PROVIDER_FAILURE" and KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_client_configuration_error_never_prints_proxy_or_key(monkeypatch):
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda **_: (_ for _ in ()).throw(ValueError(KEY)))
    result = await probe.run_probe(execute=True, api_key=KEY)
    assert result["reason"] == "CONFIGURATION_OR_PROVIDER_FAILURE" and result["requests"] == 0
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_malformed_price_variant_and_boolean_pagination_fail_safely():
    rows = [card(), card(2)]
    rows[0]["cardmarket"]["prices"][0]["variant_type"] = {"untrusted": KEY}
    result, _ = await run(responses={"ADV2": search(rows)})
    assert result["targets"][0]["page_shape"]["unknown_price_variants"] == 1
    assert KEY not in json.dumps(result)
    malformed = search(rows)
    malformed["pagination"]["limit"] = 100.0
    result, _ = await run(responses={"ADV2": malformed})
    assert result["reason"] == "INCOMPLETE_SEARCH_PAGE" and result["targets"] == []


@pytest.mark.parametrize("value", [None, True, False, "NaN", "Infinity", "-Infinity", "-1", 0, "", "secret"])
def test_nonpositive_or_invalid_prices_never_appear_positive(value):
    assert probe.positive(value) is False


@pytest.mark.asyncio
async def test_client_denies_unreviewed_endpoints_and_enforces_total_budget():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={}, headers=QUOTA))) as http:
        client = probe.ProbeClient(http, KEY)
        for path in ("/prices/ADV2", "/cards/id", "https://elsewhere.invalid/sets"):
            with pytest.raises(probe.ProbeError, match="UNREVIEWED_ENDPOINT"):
                await client.get(path)
        assert client.requests == 0
        for _ in range(3):
            await client.get("/sets")
        with pytest.raises(probe.ProbeError, match="REQUEST_BUDGET_EXHAUSTED"):
            await client.get("/sets")
        assert client.requests == 3
