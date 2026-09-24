from __future__ import annotations

import base64

import pytest

from app.ebay_official_client import EbayOfficialClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers, data):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "data": data})
        return FakeResponse(
            200,
            {
                "access_token": "application-token",
                "expires_in": 7200,
                "token_type": "Application Access Token",
            },
        )

    async def get(self, url, *, params, headers):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers})
        return FakeResponse(
            200,
            {
                "itemSummaries": [],
                "total": 0,
            },
        )


@pytest.mark.asyncio
async def test_official_client_mints_application_token_and_uses_gb_marketplace(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", FakeAsyncClient)

    client = EbayOfficialClient(
        client_id="client-id",
        client_secret="client-secret",
        marketplace_id="EBAY_GB",
    )

    result = await client.search_items(
        query="Absol 063/094",
        limit=25,
        item_location_country="GB",
    )

    assert result["total"] == 0
    assert len(FakeAsyncClient.calls) == 2

    token_call = FakeAsyncClient.calls[0]
    expected_basic = base64.b64encode(b"client-id:client-secret").decode("ascii")
    assert token_call["url"] == "https://api.ebay.com/identity/v1/oauth2/token"
    assert token_call["headers"]["Authorization"] == f"Basic {expected_basic}"
    assert token_call["data"]["grant_type"] == "client_credentials"
    assert token_call["data"]["scope"] == "https://api.ebay.com/oauth/api_scope"

    browse_call = FakeAsyncClient.calls[1]
    assert browse_call["url"] == "https://api.ebay.com/buy/browse/v1/item_summary/search"
    assert browse_call["headers"]["Authorization"] == "Bearer application-token"
    assert browse_call["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_GB"
    assert browse_call["params"]["q"] == "Absol 063/094"
    assert browse_call["params"]["filter"] == "itemLocationCountry:GB"


@pytest.mark.asyncio
async def test_application_token_is_cached(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", FakeAsyncClient)

    client = EbayOfficialClient(
        client_id="client-id",
        client_secret="client-secret",
        marketplace_id="EBAY_GB",
    )

    await client.search_items(query="Charizard")
    await client.search_items(query="Pikachu")

    post_calls = [call for call in FakeAsyncClient.calls if call["method"] == "POST"]
    get_calls = [call for call in FakeAsyncClient.calls if call["method"] == "GET"]
    assert len(post_calls) == 1
    assert len(get_calls) == 2
