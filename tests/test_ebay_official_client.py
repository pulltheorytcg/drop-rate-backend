from __future__ import annotations

import base64

import pytest

from app.ebay_official_client import EbayApiError, EbayOfficialClient, _retry_after


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


@pytest.mark.asyncio
async def test_exact_gtin_search_and_encoded_item_details_share_cached_token_and_budget_hook(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", FakeAsyncClient)
    counted = []
    async def count():
        counted.append(True)
    client = EbayOfficialClient(client_id="client", client_secret="secret", before_browse_request=count)
    await client.search_items(gtin="9781427800022", limit=10, fixed_price_only=True)
    await client.get_item("v1|123456789012|0")
    gets = [call for call in FakeAsyncClient.calls if call["method"] == "GET"]
    assert len(counted) == len(gets) == 2
    assert len([call for call in FakeAsyncClient.calls if call["method"] == "POST"]) == 1
    assert gets[0]["params"] == {"gtin": "9781427800022", "limit": 10,
                                 "filter": "itemLocationCountry:GB,buyingOptions:{FIXED_PRICE}"}
    assert gets[1]["url"] == "https://api.ebay.com/buy/browse/v1/item/v1%7C123456789012%7C0"
    assert gets[1]["params"] == {"fieldgroups": "PRODUCT"}


@pytest.mark.asyncio
@pytest.mark.parametrize("item_id", ["https://evil.test/item", "v1|123/../456|0", "v1|123|0?url=evil", "v1%7C123%7C0", "v1|123|0#secret", "v1|123|", "v1|123|0\n", None, True])
async def test_get_item_rejects_arbitrary_urls_and_encoded_path_tricks_before_oauth(monkeypatch, item_id):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", FakeAsyncClient)
    client = EbayOfficialClient(client_id="client", client_secret="secret")
    with pytest.raises(ValueError):
        await client.get_item(item_id)
    assert FakeAsyncClient.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("gtin", [True, 9781427800022, "9781427800022&filter=anything", "9781427800022\n", "../../9781427800022", "9781427"])
async def test_gtin_query_parameters_are_validated_before_oauth(monkeypatch, gtin):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", FakeAsyncClient)
    client = EbayOfficialClient(client_id="client", client_secret="secret")
    with pytest.raises(ValueError):
        await client.search_items(gtin=gtin)
    assert FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_oauth_refusal_is_not_counted_as_a_browse_request_or_leaked(monkeypatch):
    class OAuthRefused(FakeAsyncClient):
        async def post(self, url, *, headers, data):
            return FakeResponse(401, {"access_token": "must-not-leak", "error": "private-provider-body"})
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", OAuthRefused)
    counted = []
    async def count():
        counted.append(True)
    client = EbayOfficialClient(client_id="client", client_secret="secret", before_browse_request=count)
    with pytest.raises(EbayApiError) as error:
        await client.search_items(gtin="9781427800022")
    assert error.value.status_code == 401
    assert counted == []
    assert "private-provider-body" not in str(error.value)
    assert "must-not-leak" not in str(error.value)


@pytest.mark.asyncio
async def test_browse_refusal_preserves_sanitized_status_and_retry_after_without_following_redirects(monkeypatch):
    options = []
    class BrowseRefused(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            options.append(kwargs)
            super().__init__(*args, **kwargs)
        async def get(self, url, *, params, headers):
            response = FakeResponse(429, {"message": "must-not-leak"})
            response.headers = {"Retry-After": "1200"}
            return response
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", BrowseRefused)
    client = EbayOfficialClient(client_id="client", client_secret="secret")
    with pytest.raises(EbayApiError) as error:
        await client.search_items(gtin="9781427800022")
    assert error.value.status_code == 429
    assert error.value.retry_after_seconds == 1200
    assert options[-1]["follow_redirects"] is False
    assert "must-not-leak" not in str(error.value)


def test_retry_after_date_is_bounded_and_invalid_values_do_not_escape():
    response = FakeResponse(429, {})
    response.headers = {"Retry-After": "Wed, 31 Dec 2099 00:00:00 GMT"}
    assert _retry_after(response) == 86400
    response.headers = {"Retry-After": "not-a-date"}
    assert _retry_after(response) is None
