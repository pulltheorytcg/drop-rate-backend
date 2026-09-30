from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.automation_operations import ReplayAutomationEventRequest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930043000_automation_dead_letter_replay.sql"
)
API = ROOT / "backend" / "app" / "automation_operations.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_replay_reason_is_required_and_bounded() -> None:
    assert ReplayAutomationEventRequest(reason="provider recovered").reason == "provider recovered"
    with pytest.raises(ValidationError):
        ReplayAutomationEventRequest(reason="short")
    with pytest.raises(ValidationError):
        ReplayAutomationEventRequest(reason="x" * 501)


def test_outbox_listing_is_sanitized_and_read_only() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()
    list_section = lower.split(
        "create or replace function tcg.list_automation_outbox_events", 1
    )[1].split(
        "create or replace function tcg.replay_dead_letter_automation_event", 1
    )[0]

    assert "security definer" in list_section
    assert "idempotency_key text" in list_section
    assert "last_error_code text" in list_section
    assert "payload jsonb" not in list_section
    assert "ae.payload" not in list_section
    assert "update tcg.automation_events" not in list_section
    assert "delete from tcg.automation_events" not in list_section
    assert "grant execute on function tcg.list_automation_outbox_events" in lower
    assert "grant select on tcg.automation_events" not in lower


def test_replay_is_dead_letter_only_and_preserves_failure_history() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()
    replay = lower.split(
        "create or replace function tcg.replay_dead_letter_automation_event", 1
    )[1]

    assert "if v_event.status <> 'dead_letter'" in replay
    assert "only dead_letter automation events may be replayed" in replay
    assert "status='pending'" in replay
    assert "dead_lettered_at=null" in replay
    assert "last_error_code='manual_replay_requested'" in replay
    assert "attempt_count=0" not in replay
    assert "delivered_at=null" not in replay
    assert "superseded_at=null" not in replay
    assert "automation_event_replay_requested" in replay
    assert "insert into tcg.audit_events" in replay
    assert "v_request_id" in replay
    assert "m.role='platform_admin'" in replay
    assert "o.owner_type='founder'" in replay
    assert "platform administrator access required" in replay
    assert "p_actor_user_id" in replay
    assert "update tcg.inventory_items" not in replay
    assert "update tcg.shopify_inventory_links" not in replay
    assert "financial_ledger_entries" not in replay


def test_admin_api_derives_actor_from_authenticated_user() -> None:
    api = API.read_text()
    main = MAIN.read_text()

    assert 'prefix="/api/v1/automation/operations"' in api
    assert "Depends(require_user)" in api
    assert "user.user_id" in api
    assert "request.state.request_id" in api
    assert "replay_dead_letter_automation_event" in api
    assert "actor = " not in api
    assert "payload jsonb" not in api.lower()
    assert (
        "app.include_router(automation_operations_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
    ) in main
