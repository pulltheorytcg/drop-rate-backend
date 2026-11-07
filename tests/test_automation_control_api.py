from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from app import automation_control as control
from app.automation_dispatcher import signature_headers


SECRET = "synthetic-control-signing-key-" + "x" * 32
PRIVATE_MARKER = "PRIVATE_DATABASE_DETAIL_MUST_NOT_APPEAR"


class Connection:
    def __init__(self):
        self.calls = []
        self.error = None
        self.row = None

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.row


class Pool:
    def __init__(self):
        self.connection = Connection()
        self.acquisitions = 0

    @asynccontextmanager
    async def acquire(self):
        self.acquisitions += 1
        yield self.connection


@pytest.fixture
def api(monkeypatch):
    pool = Pool()
    app = FastAPI()
    app.state.db_pool = pool
    app.include_router(control.router)
    monkeypatch.setattr(
        control, "get_settings", lambda: SimpleNamespace(automation_command_secret=SECRET)
    )
    return app, pool


def payload(operation: str, **overrides):
    value = {
        "execution_id": "synthetic-123",
        "workflow_version": "v1",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    if operation == "heartbeat":
        value["heartbeat_key"] = "n8n-runtime"
    else:
        value.update(
            workflow_key="runtime-heartbeat",
            status="FAILED",
            idempotency_key="n8n-error:runtime-heartbeat:synthetic-123",
            error_code="N8N_HTTP_500",
            error_message="Synthetic fixture failure",
        )
    value.update(overrides)
    return value


async def post(api, operation: str, value=None, *, raw=None, headers=None):
    body = raw if raw is not None else json.dumps(value).encode()
    signed = signature_headers(secret=SECRET, body=body) if headers is None else headers
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api[0]), base_url="http://fixture"
    ) as client:
        return await client.post(
            "/api/v1/automation/control/" + operation, content=body, headers=signed
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
async def test_control_authenticates_exact_bytes_before_database_access(api, operation):
    body = json.dumps(payload(operation)).encode()
    headers = signature_headers(secret=SECRET, body=body)
    response = await post(api, operation, raw=body + b" ", headers=headers)
    assert response.status_code == 401
    assert api[1].acquisitions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
async def test_missing_control_secret_never_reaches_database(api, monkeypatch, operation):
    monkeypatch.setattr(
        control, "get_settings", lambda: SimpleNamespace(automation_command_secret="")
    )
    response = await post(api, operation, payload(operation))
    assert response.status_code == 503
    assert api[1].acquisitions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
@pytest.mark.parametrize("kind", ["oversize", "invalid_json", "naive_timestamp"])
async def test_control_rejects_invalid_payload_before_database_access(api, operation, kind):
    if kind == "oversize":
        response = await post(
            api, operation, raw=b"x" * (control.MAX_AUTOMATION_CONTROL_BODY_BYTES + 1)
        )
        assert response.status_code == 413
    elif kind == "invalid_json":
        response = await post(api, operation, raw=b"{")
        assert response.status_code == 422
    else:
        response = await post(
            api, operation, payload(operation, occurred_at="2026-10-27T16:00:00")
        )
        assert response.status_code == 422
    assert api[1].acquisitions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_heartbeat_preserves_database_contract_and_duplicate_receipt(api, duplicate):
    now = datetime.now(timezone.utc)
    api[1].connection.row = {
        "heartbeat_key": "n8n-runtime",
        "received_at": now,
        "beat_count": 3,
        "duplicate": duplicate,
    }
    response = await post(api, "heartbeat", payload("heartbeat"))
    assert response.status_code == 200
    result = response.json()
    assert datetime.fromisoformat(result.pop("received_at")) == now
    assert result == {
        "accepted": True,
        "heartbeat_key": "n8n-runtime",
        "beat_count": 3,
        "duplicate": duplicate,
    }
    [(query, args)] = api[1].connection.calls
    assert "tcg.record_automation_heartbeat($1,$2,$3,$4)" in query
    assert args[:3] == ("n8n-runtime", "v1", "synthetic-123")
    assert args[3].tzinfo is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
@pytest.mark.parametrize(
    "error_type,sqlstate",
    [(asyncpg.AmbiguousColumnError, "42702"), (asyncpg.UndefinedFunctionError, "42883")],
)
async def test_database_errors_are_retryable_and_log_only_sqlstate(
    api, caplog, operation, error_type, sqlstate
):
    api[1].connection.error = error_type(PRIVATE_MARKER)
    response = await post(api, operation, payload(operation))
    assert response.status_code == 503
    assert response.json() == {"detail": "Automation control storage is unavailable"}
    assert f"operation={operation} sqlstate={sqlstate}" in caplog.text
    assert PRIVATE_MARKER not in response.text + caplog.text
    assert "synthetic-123" not in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
async def test_database_rejected_control_input_is_sanitized(api, caplog, operation):
    api[1].connection.error = asyncpg.InvalidParameterValueError(PRIVATE_MARKER)
    response = await post(api, operation, payload(operation))
    assert response.status_code == 422
    assert response.json() == {"detail": f"Invalid automation {operation}"}
    assert PRIVATE_MARKER not in response.text + caplog.text
    assert "sqlstate=22023" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "receipt"])
async def test_missing_database_receipt_is_never_accepted(api, operation):
    response = await post(api, operation, payload(operation))
    assert response.status_code == 503
    assert response.json().get("accepted") is not True


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_receipt_uses_one_private_capability_without_owner_impersonation(api, duplicate):
    action = UUID("11111111-2222-4333-8444-555555555555")
    api[1].connection.row = {
        "owner_receipts_inserted": 0 if duplicate else 2,
        "duplicate_owner_receipts": 2 if duplicate else 0,
        "action_required_ids": [] if duplicate else [action],
    }
    value = payload("receipt")
    response = await post(api, "receipt", value)
    assert response.status_code == 200
    result = response.json()
    assert result == {
        "accepted": True,
        "workflow_key": value["workflow_key"],
        "execution_id": value["execution_id"],
        "status": "FAILED",
        "owner_receipts_inserted": 0 if duplicate else 2,
        "duplicate_owner_receipts": 2 if duplicate else 0,
        "action_required_ids": [] if duplicate else [str(action)],
    }
    [(query, _args)] = api[1].connection.calls
    assert "tcg_private.record_automation_execution_receipt" in query
    assert "tcg.owners" not in query
    assert "set_config" not in query
    assert "insert into" not in query.lower()
