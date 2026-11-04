"""Provider failures remain actionable without logging account data or tokens."""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.ebay_sell_client import EbaySellApiError, EbaySellClient, _failure_context, _failure_hints, _failure_action


def test_request_failure_records_resource_and_codes_without_sensitive_data(monkeypatch, caplog):
    client = EbaySellClient(
        client_id="private-client", client_secret="private-secret",
        refresh_token="private-refresh", marketplace_id="EBAY_GB",
    )

    async def token():
        return "private-access-token"

    class Transport:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return httpx.Response(500, json={"errors": [{
                "errorId": 2003,
                "message": "private-provider-message",
                "longMessage": "private-customer-address",
                "parameters": [{"name": "token", "value": "private-token"}],
            }]})

    monkeypatch.setattr(client, "user_access_token", token)
    monkeypatch.setattr("app.ebay_sell_client.httpx.AsyncClient", Transport)
    with caplog.at_level(logging.WARNING, logger="app.ebay_sell_client"):
        with pytest.raises(EbaySellApiError) as caught:
            asyncio.run(client._request(
                "PUT", "/sell/inventory/v1/inventory_item/private-sku",
                json_body={"address": "private-body"},
                params={"email": "private-email"},
            ))
    assert caught.value.status_code == 500
    assert caught.value.retryable is True
    assert "method=PUT resource=/sell/inventory/v1/inventory_item status=500 error_ids=[2003]" in caplog.text
    assert "private-" not in caplog.text + str(caught.value)


@pytest.mark.parametrize("body", [
    None, [], "private-response", {"errors": "private-error"},
    {"errors": [None, [], {"errorId": "private-code"}, {"errorId": True},
                {"errorId": -1}, {"errorId": 1234567890}]},
])
def test_malformed_error_bodies_fail_closed(body):
    response = httpx.Response(400, json=body)
    assert _failure_context("/private-path/private-value", response) == ("seller-api", [])


def test_non_json_errors_and_duplicate_codes_are_safe():
    assert _failure_context(
        "/sell/account/v1/payment_policy/private-policy", httpx.Response(502, text="private-html")
    ) == ("/sell/account/v1/payment_policy", [])
    assert _failure_context(
        "/sell/inventory/v1/offer/private-offer/publish",
        httpx.Response(400, json={"errors": [{"errorId": 25002}, {"errorId": 25002}]}),
    ) == ("/sell/inventory/v1/offer", [25002])


def test_validation_hints_never_return_provider_prose_or_field_values():
    response = httpx.Response(400, json={"errors": [{
        "message": "The item specific Graded is missing. private-name private-email@example.test",
        "longMessage": "private-secret private-street-number",
        "parameters": [{"name": "fieldName", "value": "shippingServiceCost is invalid"}],
    }]})
    assert _failure_hints(response) == ["missing", "invalid", "item_specific", "graded", "shipping"]
    assert _failure_action("/sell/inventory/v1/offer/private-offer/publish") == "publish"
    assert _failure_action("/sell/inventory/v1/offer/private-offer") == "detail"
    assert _failure_action("/sell/inventory/v1/offer") == "collection"


@pytest.mark.parametrize("body", [None, [], {"errors": "secret"}, {"errors": [None, []]}])
def test_validation_hints_handle_malformed_errors(body):
    assert _failure_hints(httpx.Response(400, json=body)) == []
    assert _failure_hints(httpx.Response(500, content=b"private-html")) == []
