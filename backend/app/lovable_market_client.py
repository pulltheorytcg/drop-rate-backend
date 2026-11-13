"""Strict read-only transport for the existing published Lovable eBay candidate API.

Lovable discovers ACTIVE asking prices. Drop Rate's existing pricing engine is
the only Market Value authority, and no candidate response performs DB writes.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx


# Fixed host avoids SSRF even if a deployment variable is accidentally changed.
PUBLISHED_URL = "https://drop-rate-market-scout.lovable.app/api/v1/market/candidates"
HEALTH_URL = "https://drop-rate-market-scout.lovable.app/api/v1/market/health"
_ALLOWED_STATUS = {"EXACT_MATCH", "REVIEW_REQUIRED", "REJECTED", "INSUFFICIENT_IDENTITY"}
_SAFE_FIELDS = (
    "name", "game", "category", "set_name", "set_code", "card_number",
    "variant", "rarity", "language", "edition", "printing", "condition",
    "grading_company", "grade", "cert_number", "product_type", "publisher",
    "series", "issue_number", "volume", "isbn", "manufacturer", "franchise",
    "product_number", "seal_status",
)


class LovableMarketError(RuntimeError):
    def __init__(self, code: str, *, status: int = 502, retryable: bool = False):
        self.code = code
        self.status = status
        self.retryable = retryable
        super().__init__(code)


def _valid_endpoint(endpoint: str) -> str:
    if endpoint != PUBLISHED_URL:
        raise LovableMarketError("LOVABLE_ENDPOINT_INVALID", status=503)
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or parts.hostname != "drop-rate-market-scout.lovable.app":
        raise LovableMarketError("LOVABLE_ENDPOINT_INVALID", status=503)
    return endpoint


def clean_lookup(lookup: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(lookup, Mapping):
        raise LovableMarketError("INVALID_LOOKUP", status=422)
    if set(lookup) - set(_SAFE_FIELDS):
        raise LovableMarketError("INVALID_LOOKUP", status=422)
    clean: dict[str, str] = {}
    for key in _SAFE_FIELDS:
        v = lookup.get(key)
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or len(v) > 160:
            raise LovableMarketError("INVALID_LOOKUP", status=422)
        clean[key] = v.strip()
    if not clean.get("name") or not (clean.get("game") or clean.get("category")):
        raise LovableMarketError("IDENTITY_REQUIRED", status=422)
    if bool(clean.get("grade")) != bool(clean.get("grading_company")):
        raise LovableMarketError("GRADE_PAIR_REQUIRED", status=422)
    return clean


def _gbp_positive(v: Any) -> str | None:
    try:
        if isinstance(v, bool):
            return None
        x = Decimal(str(v))
        if x.is_finite() and Decimal("0.01") <= x <= Decimal("100000") and x.as_tuple().exponent >= -2:
            return f"{x:.2f}"
    except (ValueError, TypeError, InvalidOperation):
        pass
    return None


def safe_candidates(data: Any) -> dict[str, Any]:
    """Fail closed on unexpected evidence semantics; never invent Market Value."""
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise LovableMarketError("LOVABLE_RESPONSE_INVALID")
    if (data.get("market_value_gbp") is not None
            or data.get("market_value_eligible") is not False
            or data.get("actual_paid_price_verified") is not False
            or data.get("observation_type") != "ACTIVE"
            or data.get("verified_sold_count") != 0):
        raise LovableMarketError("LOVABLE_EVIDENCE_POLICY_VIOLATION")
    if len(data["candidates"]) > 100:
        raise LovableMarketError("LOVABLE_RESPONSE_TOO_LARGE")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in data["candidates"]:
        if not isinstance(item, dict) or item.get("source") != "EBAY_BROWSE":
            continue
        item_id = item.get("source_item_id")
        status = item.get("match_status")
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 160 or item_id in seen:
            continue
        if status not in _ALLOWED_STATUS:
            continue
        if item.get("actual_paid_price_verified") is not False or item.get("observation_type") != "ACTIVE":
            continue
        title = item.get("title")
        if not isinstance(title, str):
            continue
        seen.add(item_id)
        url = item.get("source_url")
        url = url if isinstance(url, str) and url.startswith(("https://www.ebay.co.uk/", "https://www.ebay.com/")) else None
        money = _gbp_positive(item.get("asking_price_gbp"))
        conflicts = item.get("conflicting_signals") or []
        if not isinstance(conflicts, list):
            conflicts = []
        if conflicts and status == "EXACT_MATCH":
            status = "REJECTED"
        rows.append({
            "source": "EBAY_BROWSE", "source_item_id": item_id,
            "title": title[:250], "url": url, "match_status": status,
            "asking_price_gbp": money, "currency": "GBP" if money is not None else None,
            "evidence_type": "ACTIVE_ASKING_PRICE",
            "actual_paid_price_verified": False,
            "market_value_eligible": False,
            "seller_id": str(item.get("seller_id") or "")[:120] or None,
            "matched_signals": [str(x)[:100] for x in (item.get("matched_signals") or [])[:20]],
            "missing_signals": [str(x)[:100] for x in (item.get("missing_signals") or [])[:20]],
            "conflicting_signals": [str(x)[:100] for x in conflicts[:20]],
        })
    return {
        "transport": "LOVABLE_EBAY_BROWSE",
        "evidence_type": "ACTIVE_ASKING_PRICE",
        "market_value_gbp": None,
        "market_value_eligible": False,
        "verified_sold_count": 0,
        "persisted": False,
        "candidate_count": len(rows),
        "exact_count": sum(x["match_status"] == "EXACT_MATCH" for x in rows),
        "review_count": sum(x["match_status"] == "REVIEW_REQUIRED" for x in rows),
        "search_calls": data.get("search_calls") if type(data.get("search_calls")) is int else None,
        "detail_calls": data.get("detail_calls") if type(data.get("detail_calls")) is int else None,
        "cache_hit": data.get("cache_hit") is True,
        "candidates": rows,
    }


class LovableMarketClient:
    def __init__(
        self, endpoint: str, api_key: str, *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.endpoint = _valid_endpoint(endpoint)
        if not isinstance(api_key, str) or len(api_key) < 32:
            raise LovableMarketError("LOVABLE_SECRET_NOT_CONFIGURED", status=503)
        self.api_key = api_key
        self.transport = transport

    @classmethod
    def from_environment(cls) -> "LovableMarketClient":
        if os.getenv("LOVABLE_MARKET_READ_ONLY_ENABLED", "").strip().lower() != "true":
            raise LovableMarketError("LOVABLE_INTEGRATION_DISABLED", status=503)
        return cls(
            os.getenv("LOVABLE_MARKET_API_URL", ""),
            os.getenv("LOVABLE_MARKET_API_KEY", ""),
        )

    async def search(self, lookup: Mapping[str, Any]) -> dict[str, Any]:
        clean = clean_lookup(lookup)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                transport=self.transport, follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self.endpoint, json={"lookup": clean},
                    headers={"x-api-key": self.api_key, "accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise LovableMarketError("LOVABLE_TIMEOUT", retryable=True) from exc
        except httpx.RequestError as exc:
            raise LovableMarketError("LOVABLE_UNAVAILABLE", retryable=True) from exc
        if response.status_code in (401, 403):
            raise LovableMarketError("LOVABLE_AUTH_REJECTED", status=503)
        if response.status_code == 429:
            raise LovableMarketError("LOVABLE_RATE_LIMITED", status=429, retryable=True)
        if response.is_redirect:
            raise LovableMarketError("LOVABLE_REDIRECT_REJECTED")
        if response.status_code >= 500:
            raise LovableMarketError("LOVABLE_PROVIDER_UNAVAILABLE", retryable=True)
        if response.status_code != 200:
            raise LovableMarketError("LOVABLE_REQUEST_REJECTED", status=422 if response.status_code < 500 else 502)
        if len(response.content) > 512_000:
            raise LovableMarketError("LOVABLE_RESPONSE_TOO_LARGE")
        if "json" not in response.headers.get("content-type", "").lower():
            raise LovableMarketError("LOVABLE_INVALID_JSON")
        try:
            body = response.json()
        except ValueError as exc:
            raise LovableMarketError("LOVABLE_INVALID_JSON") from exc
        return safe_candidates(body)
