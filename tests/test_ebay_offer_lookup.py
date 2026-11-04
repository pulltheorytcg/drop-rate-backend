"""Only eBay's explicit absent-offer response permits first-offer creation."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.ebay_sell_client import EbaySellApiError, EbaySellClient


ABSENT = {"errorId": 25713, "domain": "API_INVENTORY", "category": "REQUEST"}


def _client(monkeypatch, status, body):
    calls = []
    client = EbaySellClient(
        client_id="client", client_secret="secret", refresh_token="refresh",
        marketplace_id="EBAY_GB",
    )

    async def token():
        return "access-token"

    class Transport:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if isinstance(body, bytes):
                return httpx.Response(status, content=body)
            return httpx.Response(status, json=body)

    monkeypatch.setattr(client, "user_access_token", token)
    monkeypatch.setattr("app.ebay_sell_client.httpx.AsyncClient", Transport)
    return client, calls


def test_first_sku_offer_lookup_is_empty_when_ebay_explicitly_reports_absence(monkeypatch):
    client, calls = _client(monkeypatch, 404, {"errors": [ABSENT]})
    assert asyncio.run(client.get_offers(sku="INV-TEST-ONE")) == []
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert calls[0][2]["params"] == {"sku": "INV-TEST-ONE", "marketplace_id": "EBAY_GB"}


@pytest.mark.parametrize("status,body", [
    (401, {"errors": [ABSENT]}), (403, {"errors": [ABSENT]}),
    (429, {"errors": [ABSENT]}), (500, {"errors": [ABSENT]}),
    (400, {"errors": [ABSENT]}),
    (404, {"errors": [{**ABSENT, "errorId": 25710}]}),
    (404, {"errors": [{**ABSENT, "domain": "ACCESS"}]}),
    (404, {"errors": [{**ABSENT, "category": "APPLICATION"}]}),
    (404, {"errors": [ABSENT, {"errorId": 25001}]}),
    (404, {"errors": []}), (404, {"errors": [None]}),
    (404, {"errors": ["unknown"]}), (404, {"errors": "unknown"}),
    (404, {}), (404, []), (404, b"not-json"),
])
def test_other_provider_failures_never_become_an_empty_offer_list(monkeypatch, status, body):
    client, _ = _client(monkeypatch, status, body)
    with pytest.raises(EbaySellApiError) as caught:
        asyncio.run(client.get_offers(sku="INV-TEST-ONE"))
    assert caught.value.status_code == status


@pytest.mark.parametrize("operation", ["get_offer", "get_inventory_item", "publish_offer"])
def test_absence_exception_is_scoped_to_offer_collection_lookup(monkeypatch, operation):
    client, _ = _client(monkeypatch, 404, {"errors": [ABSENT]})
    with pytest.raises(EbaySellApiError):
        asyncio.run(getattr(client, operation)("example-id"))


def test_existing_offer_is_returned_unchanged_for_recovery(monkeypatch):
    offer = {"offerId": "same-offer", "sku": "INV-TEST-ONE", "marketplaceId": "EBAY_GB"}
    client, _ = _client(monkeypatch, 200, {"offers": [offer]})
    assert asyncio.run(client.get_offers(sku="INV-TEST-ONE")) == [offer]


def test_blank_sku_never_calls_ebay(monkeypatch):
    client, calls = _client(monkeypatch, 404, {"errors": [ABSENT]})
    with pytest.raises(ValueError, match="requires a SKU"):
        asyncio.run(client.get_offers(sku=" "))
    assert calls == []
