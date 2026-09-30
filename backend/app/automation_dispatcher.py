from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse


def _json_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("Automation event payload must be a JSON object")


def event_envelope(event: Mapping[str, Any]) -> dict[str, Any]:
    created_at = event.get("created_at")
    if isinstance(created_at, datetime):
        occurred_at = created_at.astimezone(timezone.utc).isoformat()
    else:
        occurred_at = str(created_at or "").strip()
    if not occurred_at:
        raise ValueError("Automation event created_at is required")

    return {
        "event_id": str(event.get("event_id") or ""),
        "event_type": str(event.get("event_type") or ""),
        "schema_version": int(event.get("schema_version") or 0),
        "aggregate": {
            "type": str(event.get("aggregate_type") or ""),
            "id": str(event.get("aggregate_id") or ""),
        },
        "idempotency_key": str(event.get("idempotency_key") or ""),
        "owner_id": (
            str(event.get("owner_id"))
            if event.get("owner_id") is not None
            else None
        ),
        "attempt": int(event.get("attempt_count") or 0),
        "occurred_at": occurred_at,
        "payload": _json_payload(event.get("payload")),
    }


def canonical_event_body(event: Mapping[str, Any]) -> bytes:
    envelope = event_envelope(event)
    if not envelope["event_id"] or not envelope["event_type"]:
        raise ValueError("Automation event identity is incomplete")
    if envelope["schema_version"] < 1:
        raise ValueError("Automation event schema version is invalid")
    aggregate = envelope["aggregate"]
    if not aggregate["type"] or not aggregate["id"]:
        raise ValueError("Automation event aggregate is incomplete")
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def signature_headers(
    *,
    secret: str,
    body: bytes,
    timestamp: datetime | None = None,
) -> dict[str, str]:
    clean_secret = secret.strip()
    if len(clean_secret) < 32:
        raise ValueError("Automation webhook secret must be at least 32 characters")
    now = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp_text = str(int(now.timestamp()))
    signed = timestamp_text.encode("ascii") + b"." + body
    digest = hmac.new(
        clean_secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Drop-Rate-Timestamp": timestamp_text,
        "X-Drop-Rate-Signature": f"sha256={digest}",
    }


def verify_signed_body(
    *,
    secret: str,
    body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    now: datetime | None = None,
    max_skew_seconds: int = 300,
) -> bool:
    """Verify a Drop Rate HMAC request without parsing or mutating its body."""

    clean_secret = secret.strip()
    timestamp_text = str(timestamp_header or "").strip()
    supplied = str(signature_header or "").strip().lower()
    if len(clean_secret) < 32 or not body:
        return False
    if not timestamp_text.isdigit():
        return False
    if not supplied.startswith("sha256=") or len(supplied) != 71:
        return False
    digest_text = supplied.removeprefix("sha256=")
    if any(character not in "0123456789abcdef" for character in digest_text):
        return False

    timestamp_value = int(timestamp_text)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if abs(int(current.timestamp()) - timestamp_value) > max_skew_seconds:
        return False

    signed = timestamp_text.encode("ascii") + b"." + body
    expected = "sha256=" + hmac.new(
        clean_secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, supplied)


def retry_delay_seconds(attempt_count: int) -> int:
    """Deterministic exponential backoff capped at 30 minutes."""

    attempt = max(1, int(attempt_count))
    return min(15 * (2 ** (attempt - 1)), 1800)


def classify_http_failure(status_code: int) -> tuple[str, bool]:
    """Return (error_code, force_dead_letter).

    429 and 5xx are retryable. Other 4xx responses indicate a bad endpoint,
    authentication problem or event contract mismatch and are dead-lettered
    immediately so an operator sees the fault.
    """

    status = int(status_code)
    if status == 429:
        return "N8N_RATE_LIMITED", False
    if 500 <= status <= 599:
        return f"N8N_HTTP_{status}", False
    if 400 <= status <= 499:
        return f"N8N_HTTP_{status}", True
    return f"N8N_HTTP_{status}", False


def validate_webhook_url(value: str) -> str:
    """Allow HTTPS everywhere and HTTP only on Railway private DNS."""

    clean = value.strip()
    parsed = urlparse(clean)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("Automation webhook URL must include a hostname")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Automation webhook URL contains unsupported URL components")
    if parsed.scheme == "https":
        return clean
    if parsed.scheme == "http" and hostname.endswith(".railway.internal"):
        return clean
    raise ValueError(
        "Automation webhook URL must use HTTPS unless it targets Railway private DNS"
    )
