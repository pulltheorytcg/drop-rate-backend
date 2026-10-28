"""Mock-only coverage for explicit delivery context, not a live postage quote."""
from __future__ import annotations

import pytest

from app.ebay_official_client import EbayOfficialClient


class MockHttp:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers, data):
        self.calls.append({"method": "POST", "headers": headers, "url": url})
        return MockResponse({"access_token": "mock-token", "expires_in": 7200})

    async def get(self, url, *, headers, params):
        self.calls.append({"method": "GET", "headers": headers, "url": url, "params": params})
        return MockResponse({"itemSummaries": [], "total": 0})


class MockResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def mock_http(monkeypatch):
    MockHttp.calls = []
    monkeypatch.setattr("app.ebay_official_client.httpx.AsyncClient", MockHttp)


@pytest.mark.asyncio
async def test_existing_callers_keep_their_headers_and_never_get_an_invented_postcode():
    client = EbayOfficialClient(client_id="id", client_secret="secret")
    await client.search_items(query="Charizard")
    assert len(MockHttp.calls) == 2
    assert all("X-EBAY-C-ENDUSERCTX" not in call["headers"] for call in MockHttp.calls)
    assert MockHttp.calls[1]["headers"] == {
        "Authorization": "Bearer mock-token", "X-EBAY-C-MARKETPLACE-ID": "EBAY_GB",
        "Accept": "application/json",
    }


@pytest.mark.asyncio
async def test_explicit_gb_postcode_is_encoded_on_search_and_details_but_not_oauth():
    # Public example for mocked requests only; no production default is supplied.
    client = EbayOfficialClient(client_id="id", client_secret="secret", buyer_country="gb", buyer_postal_code="sw1a1aa")
    await client.search_items(query="Charizard", fixed_price_only=True)
    await client.get_item("v1|123456789012|0")
    assert len(MockHttp.calls) == 3
    assert "X-EBAY-C-ENDUSERCTX" not in MockHttp.calls[0]["headers"]
    for call in MockHttp.calls[1:]:
        assert call["headers"]["X-EBAY-C-ENDUSERCTX"] == "contextualLocation=country%3DGB%2Czip%3DSW1A%201AA"
        assert call["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_GB"
    assert MockHttp.calls[1]["params"]["filter"] == "itemLocationCountry:GB,buyingOptions:{FIXED_PRICE}"


@pytest.mark.asyncio
async def test_instances_cannot_leak_context_to_each_other():
    configured = EbayOfficialClient(client_id="id", client_secret="secret", buyer_country="GB", buyer_postal_code="SW1A 1AA")
    unconfigured = EbayOfficialClient(client_id="id", client_secret="secret")
    await configured.search_items(query="Charizard")
    await unconfigured.search_items(query="Pikachu")
    gets = [call for call in MockHttp.calls if call["method"] == "GET"]
    assert "X-EBAY-C-ENDUSERCTX" in gets[0]["headers"]
    assert "X-EBAY-C-ENDUSERCTX" not in gets[1]["headers"]


@pytest.mark.parametrize("country,postcode", [
    ("GB", None), (None, "SW1A 1AA"), ("GB", ""), ("GB", " "),
    ("GB", "SW1A"), ("GB", "12345"), ("GB", "ZZ99 9ZZ"),
    ("GB", "SW1A 1AA\n"), ("GB", "SW1A 1AA,zip=other"),
    ("GB", "SW1A%201AA"), ("GB", "SW1A\r\n1AA"),
    ("GB", True), ("GB", 12345), ("G", "SW1A 1AA"),
    ("GB\n", "SW1A 1AA"), (True, "SW1A 1AA"),
])
def test_invalid_or_partial_delivery_context_rejected_before_any_request(country, postcode):
    with pytest.raises(ValueError) as caught:
        EbayOfficialClient(client_id="id", client_secret="secret", buyer_country=country, buyer_postal_code=postcode)
    assert MockHttp.calls == []
    assert "SW1A" not in str(caught.value)


@pytest.mark.asyncio
async def test_explicit_non_gb_pair_uses_same_documented_encoding():
    client = EbayOfficialClient(client_id="id", client_secret="secret", marketplace_id="EBAY_US", buyer_country="US", buyer_postal_code="19406")
    await client.search_items(query="Charizard", item_location_country="US")
    get = MockHttp.calls[1]
    assert get["headers"]["X-EBAY-C-ENDUSERCTX"] == "contextualLocation=country%3DUS%2Czip%3D19406"
    assert get["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
