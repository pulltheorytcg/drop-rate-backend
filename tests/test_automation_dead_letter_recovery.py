from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automation_recovery import AutomationReplayRequest


ROOT = Path(__file__).resolve().parents[1]
BASE_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930042000_automation_dead_letter_recovery.sql"
)
FIX_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930044500_fix_automation_replay_history.sql"
)
API = ROOT / "backend" / "app" / "automation_recovery.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_replay_reason_is_required_and_normalized() -> None:
    payload = AutomationReplayRequest(reason="  provider   outage fixed  ")
    assert payload.reason == "provider outage fixed"

    with pytest.raises(ValidationError):
        AutomationReplayRequest(reason="short")


def test_dead_letter_listing_is_read_only_and_sanitized() -> None:
    sql = BASE_MIGRATION.read_text().lower()

    assert "list_automation_dead_letters" in sql
    assert "where ae.status='dead_letter'" in sql
    assert "ae.payload" not in sql
    assert "acquisition_cost" not in sql
    assert "financial" not in sql
    assert "grant execute on function tcg.list_automation_dead_letters" in sql
    assert "to tcg_api" in sql


def test_replay_is_dead_letter_only_admin_gated_and_audited() -> None:
    sql = FIX_MIGRATION.read_text()
    lower = sql.lower()

    assert "replay_dead_letter_automation_event" in lower
    assert "m.role='PLATFORM_ADMIN'" in sql
    assert "o.owner_type='FOUNDER'" in sql
    assert "if v_event.status <> 'DEAD_LETTER'" in sql
    assert "Only DEAD_LETTER automation events may be replayed" in sql
    assert "AUTOMATION_EVENT_REPLAY_REQUESTED" in sql
    assert "insert into tcg.audit_events" in lower
    assert "attempt_count=0" not in lower
    assert "max_attempts=greatest(max_attempts,attempt_count+1)" in lower
    assert "last_error_code='manual_replay_requested'" in lower
    assert "p_request_id" in lower
    assert "status='PENDING'" in sql

    for forbidden in (
        "update tcg.inventory_items",
        "update tcg.shopify_inventory_links",
        "update tcg.orders",
        "update tcg.financial_ledger_entries",
        "update tcg.market_observations",
    ):
        assert forbidden not in lower


def test_replay_does_not_allow_delivered_or_superseded_history() -> None:
    lower = FIX_MIGRATION.read_text().lower()
    assert "where id=p_event_id" in lower
    assert "and status='dead_letter'" in lower
    assert "status='delivered'" not in lower
    assert "status='superseded'" not in lower


def test_recovery_functions_are_not_exposed_to_user_roles() -> None:
    lower = (BASE_MIGRATION.read_text() + "\n" + FIX_MIGRATION.read_text()).lower()
    for role in ("public", "anon", "authenticated", "service_role", "tcg_auditor"):
        assert f"from {role}" in lower or role in lower
    assert "to tcg_api" in lower


def test_api_requires_platform_admin_and_uses_database_guards() -> None:
    source = API.read_text()
    main = MAIN.read_text()

    assert "await require_platform_admin(connection)" in source
    assert "tcg.list_automation_dead_letters" in source
    assert "tcg.replay_dead_letter_automation_event($1,$2,$3,$4)" in source
    assert "request.state.request_id" in source
    assert 'status_code=404' in source
    assert 'status_code=409' in source
    assert "app.include_router(automation_recovery_router)" in main
