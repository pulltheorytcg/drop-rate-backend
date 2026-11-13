from __future__ import annotations

import httpx
import pytest

from app.base44_market_client import (
    Base44MarketClient,
    Base44MarketError,
    response_shape_preview,
)


ENDPOINT = "https://example.base44.app/api/market/lookup"
SECRET = "test_only_" + "z" * 40
LOOKUP = {"game": "Pokemon", "name": "Charizard", "set_name": "Base Set", "card_number": "4/102"}


@pytest.mark.asyncio
async def test_authenticated_request_only_returns_unverified_candidates():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["x-api-key"] == SECRET
        assert request.headers["accept"] == "application/json"
        assert request.content == b'{"lookup":{"game":"Pokemon","name":"Charizard","set_name":"Base Set","card_number":"4/102"}}'
        return httpx.Response(200, json={"observations": [{"kind": "SOLD", "price": 1}]})

    result = await Base44MarketClient(ENDPOINT, SECRET).lookup(
        LOOKUP, transport=httpx.MockTransport(handler)
    )
    assert result["verification_status"] == "UNVERIFIED_PROVIDER_RESPONSE"
    assert result["persisted"] is False
    assert result["market_value_updated"] is False
    assert result["shopify_updated"] is False
    assert response_shape_preview(result)["array_lengths"] == {"observations": 1}


@pytest.mark.parametrize("url", [
    "http://example.com/api",
    "https://localhost/api",
    "https://127.0.0.1/api",
    "https://example.local/api",
    "https://example.com/",
    "https://someone:password@example.com/api",
    "https://example.com:8080/api",
    "https://example.com/api?key=secret",
    "https://example.com/api#fragment",
])
def test_refuses_unsafe_endpoints(url):
    with pytest.raises(Base44MarketError) as exc:
        Base44MarketClient(url, SECRET)
    assert exc.value.code == "INVALID_ENDPOINT"


@pytest.mark.parametrize("fields", [
    {},
    {"game": "Pokemon"},
    {"game": "Pokemon", "name": "Charizard", "user_id": "private"},
    {"game": "Pokemon", "name": ""},
    {"game": "Pokemon", "name": 7},
])
@pytest.mark.asyncio
async def test_refuses_bad_lookup_before_network(fields):
    async def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Network should not be attempted")
    with pytest.raises(Base44MarketError) as exc:
        await Base44MarketClient(ENDPOINT, SECRET).lookup(
            fields, transport=httpx.MockTransport(no_network)
        )
    assert exc.value.code == "INVALID_LOOKUP"


@pytest.mark.parametrize(("status", "code"), [
    (302, "PROVIDER_REDIRECT_REJECTED"),
    (401, "PROVIDER_AUTH_REJECTED"),
    (403, "PROVIDER_AUTH_REJECTED"),
    (429, "PROVIDER_RATE_LIMITED"),
    (500, "PROVIDER_UNAVAILABLE"),
    (404, "PROVIDER_REJECTED_REQUEST"),
])
@pytest.mark.asyncio
async def test_provider_errors_fail_closed(status, code):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, headers={"location": "https://elsewhere.example/api"})
    )
    with pytest.raises(Base44MarketError) as exc:
        await Base44MarketClient(ENDPOINT, SECRET).lookup(LOOKUP, transport=transport)
    assert exc.value.code == code
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_response_requires_json_object():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(Base44MarketError) as exc:
        await Base44MarketClient(ENDPOINT, SECRET).lookup(LOOKUP, transport=transport)
    assert exc.value.code == "PROVIDER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_response_size_is_bounded():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"blob": "x" * 525_000})
    )
    with pytest.raises(Base44MarketError) as exc:
        await Base44MarketClient(ENDPOINT, SECRET).lookup(LOOKUP, transport=transport)
    assert exc.value.code == "PROVIDER_RESPONSE_TOO_LARGE"


def test_environment_opt_in_default_off(monkeypatch):
    monkeypatch.delenv("BASE44_MARKET_READ_ONLY_ENABLED", raising=False)
    monkeypatch.setenv("BASE44_MARKET_API_URL", ENDPOINT)
    monkeypatch.setenv("BASE44_MARKET_API_KEY", SECRET)
    with pytest.raises(Base44MarketError) as exc:
        Base44MarketClient.from_environment()
    assert exc.value.code == "INTEGRATION_DISABLED"


def test_environment_opt_in_reads_credentials(monkeypatch):
    monkeypatch.setenv("BASE44_MARKET_READ_ONLY_ENABLED", "true")
    monkeypatch.setenv("BASE44_MARKET_API_URL", ENDPOINT)
    monkeypatch.setenv("BASE44_MARKET_API_KEY", SECRET)
    client = Base44MarketClient.from_environment()
    assert client.endpoint == ENDPOINT
