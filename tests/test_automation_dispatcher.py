from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from app.automation_dispatcher import (
    canonical_event_body,
    classify_http_failure,
    retry_delay_seconds,
    signature_headers,
    validate_webhook_url,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260928033000_automation_event_outbox.sql"
)
SCRIPT = ROOT / "backend" / "scripts" / "run_automation_dispatcher.py"
DOCKERFILE = ROOT / "Dockerfile.automation"


def _event(**overrides):
    row = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "event_type": "inventory.approved",
        "schema_version": 1,
        "aggregate_type": "INVENTORY_ITEM",
        "aggregate_id": "33333333-3333-3333-3333-333333333333",
        "idempotency_key": "inventory.approved:33333333-3333-3333-3333-333333333333:v4",
        "payload": {
            "inventory_id": "33333333-3333-3333-3333-333333333333",
            "inventory_code": "INV-PKM-000001",
            "status": "APPROVED",
            "version": 4,
        },
        "attempt_count": 1,
        "max_attempts": 8,
        "created_at": datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_event_body_is_canonical_and_excludes_unlisted_fields() -> None:
    event = _event()
    event["private_note"] = "must never leave backend"
    event["acquisition_cost_minor"] = 999999

    body = canonical_event_body(event)
    decoded = json.loads(body)

    assert decoded["event_id"] == event["event_id"]
    assert decoded["event_type"] == "inventory.approved"
    assert decoded["schema_version"] == 1
    assert decoded["aggregate"] == {
        "type": "INVENTORY_ITEM",
        "id": event["aggregate_id"],
    }
    assert decoded["payload"]["inventory_code"] == "INV-PKM-000001"
    assert "private_note" not in decoded
    assert "acquisition_cost_minor" not in decoded


def test_event_body_is_stable_for_payload_key_order() -> None:
    first = _event(payload={"b": 2, "a": 1})
    second = _event(payload={"a": 1, "b": 2})

    assert canonical_event_body(first) == canonical_event_body(second)


def test_signature_is_hmac_sha256_over_timestamp_and_body() -> None:
    secret = "x" * 32
    body = canonical_event_body(_event())
    timestamp = datetime(2026, 9, 28, 3, 30, tzinfo=timezone.utc)

    headers = signature_headers(
        secret=secret,
        body=body,
        timestamp=timestamp,
    )

    timestamp_text = str(int(timestamp.timestamp()))
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp_text.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    assert headers["X-Drop-Rate-Timestamp"] == timestamp_text
    assert headers["X-Drop-Rate-Signature"] == f"sha256={expected}"
    assert headers["Content-Type"] == "application/json"


def test_signature_rejects_weak_secret() -> None:
    body = canonical_event_body(_event())
    try:
        signature_headers(secret="too-short", body=body)
    except ValueError as exc:
        assert "at least 32 characters" in str(exc)
    else:
        raise AssertionError("weak webhook secret should be rejected")


def test_retry_backoff_is_bounded() -> None:
    assert retry_delay_seconds(1) == 15
    assert retry_delay_seconds(2) == 30
    assert retry_delay_seconds(3) == 60
    assert retry_delay_seconds(8) == 1800
    assert retry_delay_seconds(100) == 1800


def test_http_failure_classification() -> None:
    assert classify_http_failure(429) == ("N8N_RATE_LIMITED", False)
    assert classify_http_failure(500) == ("N8N_HTTP_500", False)
    assert classify_http_failure(503) == ("N8N_HTTP_503", False)
    assert classify_http_failure(400) == ("N8N_HTTP_400", True)
    assert classify_http_failure(401) == ("N8N_HTTP_401", True)
    assert classify_http_failure(404) == ("N8N_HTTP_404", True)


def test_outbox_migration_is_fail_closed_and_idempotent() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "create table tcg.automation_events" in lower
    assert "unique(idempotency_key)" in lower
    assert "for update skip locked" in lower
    assert "security definer" in lower
    assert "dead_letter" in lower
    assert "lease_until" in lower
    assert "attempt_count" in lower
    assert "max_attempts" in lower
    assert "payload jsonb" in lower
    assert "inventory.approved" in sql
    assert "acquisition_cost_minor" not in sql
    assert "perform *" in lower
    assert "tcg.enqueue_automation_event" in lower

    for role in (
        "public",
        "anon",
        "authenticated",
        "service_role",
        "tcg_api",
        "tcg_auditor",
    ):
        assert f"revoke all on tcg.automation_events from {role}" in lower


def test_inventory_approval_event_is_transactional_and_minimal() -> None:
    sql = MIGRATION.read_text()

    assert "after insert" in sql.lower()
    assert "after update of status" in sql.lower()
    assert "emit_inventory_approved_event" in sql
    assert "'inventory.approved'" in sql
    assert "'INVENTORY_ITEM'" in sql
    assert "'inventory_id',new.id" in sql
    assert "'inventory_code',new.inventory_code" in sql
    assert "'catalogue_id',new.catalogue_id" in sql
    assert "'version',new.version" in sql
    assert "new.owner_id" in sql


def test_dispatcher_never_knows_n8n_database_credentials_or_core_business_logic() -> None:
    source = SCRIPT.read_text()

    assert "TCG_DATABASE_URL" in source
    assert "TCG_N8N_WEBHOOK_URL" in source
    assert "TCG_N8N_WEBHOOK_SECRET" in source
    assert "claim_automation_events" in source
    assert "ack_automation_event" in source
    assert "fail_automation_event" in source

    # The worker delivers already-created domain events. It does not calculate
    # ownership, settlements, pricing or Shopify publication decisions.
    forbidden = (
        "shopify_client",
        "stripe",
        "settlement",
        "financial_ledger_entries",
        "acquisition_cost",
        "set status='approved'",
        "update tcg.inventory_items",
    )
    lowered = source.lower()
    for value in forbidden:
        assert value not in lowered


def test_dispatcher_dockerfile_is_minimal() -> None:
    dockerfile = DOCKERFILE.read_text()

    assert "FROM python:3.12-slim" in dockerfile
    assert "PYTHONPATH=/app/backend" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "run_automation_dispatcher.py" in dockerfile
    assert "uvicorn" not in dockerfile.lower()


def test_webhook_url_accepts_public_https() -> None:
    assert validate_webhook_url("https://automation.example.com/webhook/drop-rate") == "https://automation.example.com/webhook/drop-rate"


def test_webhook_url_accepts_railway_private_http() -> None:
    url = "http://drop-rate-n8n-e840.railway.internal:5678/webhook/drop-rate"
    assert validate_webhook_url(url) == url


def test_webhook_url_rejects_public_http() -> None:
    try:
        validate_webhook_url("http://automation.example.com/webhook/drop-rate")
    except ValueError as exc:
        assert "must use HTTPS" in str(exc)
    else:
        raise AssertionError("public HTTP webhook must be rejected")


def test_webhook_url_rejects_railway_lookalike_hostname() -> None:
    for url in (
        "http://railway.internal.evil.com/webhook/drop-rate",
        "http://evilrailway.internal/webhook/drop-rate",
        "http://railway.internal/webhook/drop-rate",
    ):
        try:
            validate_webhook_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"lookalike private hostname accepted: {url}")


def test_webhook_url_rejects_userinfo_and_fragments() -> None:
    for url in (
        "https://user:pass@automation.example.com/webhook/drop-rate",
        "http://drop-rate-n8n-e840.railway.internal:5678/webhook/drop-rate#fragment",
    ):
        try:
            validate_webhook_url(url)
        except ValueError as exc:
            assert "unsupported URL components" in str(exc)
        else:
            raise AssertionError(f"unsafe webhook URL accepted: {url}")
