"""Fail-closed, read-only transport for an independently deployed Base44 market API.

Base44 is a transport, not a verified sales source or a second valuation engine.
This module makes no database, pricing, inventory or Shopify writes.
"""
from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx


_ALLOWED_LOOKUP_FIELDS = frozenset({
    "category", "game", "name", "set_name", "set_code", "card_number",
    "variant", "rarity", "language", "edition", "printing", "condition",
    "grading_company", "grade", "cert_number", "product_type",
    "publisher", "series", "issue_number", "volume", "isbn",
    "manufacturer", "franchise", "product_number", "seal_status",
})
_MAX_LOOKUP_BYTES = 16_384
_MAX_RESPONSE_BYTES = 524_288


class Base44MarketError(RuntimeError):
    """Safe errors only: never include an API key, URL query or provider response."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def _validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str):
        raise Base44MarketError("INVALID_ENDPOINT")
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise Base44MarketError("INVALID_ENDPOINT") from exc
    if (parsed.scheme != "https" or not host or "." not in host
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or port not in (None, 443)
            or host in {"localhost", "localhost.localdomain"}
            or host.endswith((".local", ".internal", ".localhost"))):
        raise Base44MarketError("INVALID_ENDPOINT")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise Base44MarketError("INVALID_ENDPOINT")
    if not parsed.path or parsed.path == "/":
        raise Base44MarketError("INVALID_ENDPOINT")
    return endpoint


def _lookup_body(fields: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(fields, Mapping) or not fields:
        raise Base44MarketError("INVALID_LOOKUP")
    if any(key not in _ALLOWED_LOOKUP_FIELDS for key in fields):
        raise Base44MarketError("INVALID_LOOKUP")
    clean: dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise Base44MarketError("INVALID_LOOKUP")
        clean[key] = value.strip()
    if not clean.get("name") or not (clean.get("game") or clean.get("category")):
        raise Base44MarketError("INVALID_LOOKUP")
    if len(json.dumps(clean).encode("utf-8")) > _MAX_LOOKUP_BYTES:
        raise Base44MarketError("INVALID_LOOKUP")
    # This is our proposed request contract. It must be reconciled against the
    # deployed Base44 function's real method and JSON schema before use.
    return {"lookup": clean}


@dataclass(frozen=True, slots=True)
class Base44MarketClient:
    endpoint: str
    api_key: str
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        _validate_endpoint(self.endpoint)
        if not isinstance(self.api_key, str) or len(self.api_key.strip()) < 32:
            raise Base44MarketError("INVALID_CREDENTIAL")
        if not 0 < self.timeout_seconds <= 20:
            raise Base44MarketError("INVALID_TIMEOUT")

    @classmethod
    def from_environment(cls) -> "Base44MarketClient":
        # Remains OFF even if someone has entered credentials in Railway.
        if os.getenv("BASE44_MARKET_READ_ONLY_ENABLED", "").lower() != "true":
            raise Base44MarketError("INTEGRATION_DISABLED")
        url = os.getenv("BASE44_MARKET_API_URL", "")
        key = os.getenv("BASE44_MARKET_API_KEY", "")
        if not url or not key:
            raise Base44MarketError("INTEGRATION_NOT_CONFIGURED")
        return cls(endpoint=url, api_key=key)

    async def lookup(
        self,
        fields: Mapping[str, Any],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> dict[str, Any]:
        """Request candidate data. NEVER promote the returned content to SOLD.

        The caller must verify identity, actual paid price, provenance, country,
        currency, condition, variant and grading before any separate ingestion.
        """
        body = _lookup_body(fields)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                transport=transport,
            ) as client:
                response = await client.post(
                    self.endpoint,
                    json=body,
                    headers={
                        "x-api-key": self.api_key,
                        "accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise Base44MarketError("PROVIDER_TIMEOUT", retryable=True) from exc
        except httpx.RequestError as exc:
            raise Base44MarketError("PROVIDER_UNAVAILABLE", retryable=True) from exc

        if response.status_code in (401, 403):
            raise Base44MarketError("PROVIDER_AUTH_REJECTED")
        if response.status_code == 429:
            raise Base44MarketError("PROVIDER_RATE_LIMITED", retryable=True)
        if response.is_redirect:
            raise Base44MarketError("PROVIDER_REDIRECT_REJECTED")
        if response.status_code >= 500:
            raise Base44MarketError("PROVIDER_UNAVAILABLE", retryable=True)
        if response.status_code >= 400:
            raise Base44MarketError("PROVIDER_REJECTED_REQUEST")
        if response.status_code != 200:
            raise Base44MarketError("PROVIDER_UNEXPECTED_STATUS")
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise Base44MarketError("PROVIDER_RESPONSE_TOO_LARGE")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise Base44MarketError("PROVIDER_INVALID_JSON")
        try:
            result = response.json()
        except ValueError as exc:
            raise Base44MarketError("PROVIDER_INVALID_JSON") from exc
        if not isinstance(result, dict):
            raise Base44MarketError("PROVIDER_INVALID_RESPONSE")
        return {
            "transport": "BASE44",
            "verification_status": "UNVERIFIED_PROVIDER_RESPONSE",
            "persisted": False,
            "market_value_updated": False,
            "shopify_updated": False,
            "payload": result,
        }


def response_shape_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    """Non-sensitive diagnostic summary, no prices or purported sales returned."""
    payload = result.get("payload")
    if not isinstance(payload, dict):
        raise Base44MarketError("PROVIDER_INVALID_RESPONSE")
    return {
        "transport": "BASE44",
        "verification_status": "UNVERIFIED_PROVIDER_RESPONSE",
        "persisted": False,
        "top_level_fields": sorted(str(key) for key in payload)[:100],
        "array_lengths": {
            str(key): len(value)
            for key, value in payload.items()
            if isinstance(value, list)
        },
    }
