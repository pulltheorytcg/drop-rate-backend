from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.automation_commands import InventoryApprovedEvent


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "backend" / "app" / "automation_commands.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def _event() -> dict:
    inventory_id = "33333333-3333-3333-3333-333333333333"
    return {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "event_type": "inventory.approved",
        "schema_version": 1,
        "aggregate": {"type": "INVENTORY_ITEM", "id": inventory_id},
        "idempotency_key": f"inventory.approved:{inventory_id}:v4",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "attempt": 1,
        "occurred_at": "2026-09-28T17:50:00+00:00",
        "payload": {
            "inventory_id": inventory_id,
            "inventory_code": "INV-PKM-000001",
            "catalogue_id": "44444444-4444-4444-4444-444444444444",
            "status": "APPROVED",
            "version": 4,
        },
    }


def test_inventory_approved_command_contract_binds_every_identity() -> None:
    event = InventoryApprovedEvent.model_validate(_event())
    assert event.event_type == "inventory.approved"
    assert event.schema_version == 1
    assert event.aggregate.id == event.payload.inventory_id
    assert event.owner_id == UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.parametrize(
    "mutation",
    [
        "aggregate",
        "idempotency",
        "status",
        "schema",
        "event_type",
    ],
)
def test_inventory_approved_command_rejects_contract_mismatch(mutation: str) -> None:
    payload = deepcopy(_event())
    if mutation == "aggregate":
        payload["aggregate"]["id"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    elif mutation == "idempotency":
        payload["idempotency_key"] = "inventory.approved:wrong:v4"
    elif mutation == "status":
        payload["payload"]["status"] = "DRAFT"
    elif mutation == "schema":
        payload["schema_version"] = 2
    elif mutation == "event_type":
        payload["event_type"] = "inventory.changed"

    with pytest.raises(ValidationError):
        InventoryApprovedEvent.model_validate(payload)


def test_automation_command_is_hmac_only_not_founder_jwt_impersonation() -> None:
    source = COMMANDS.read_text()
    main = MAIN.read_text()

    assert "TCG_AUTOMATION_COMMAND_SECRET" not in source
    assert "automation_command_secret" in source
    assert "verify_signed_body" in source
    assert "require_user" not in source
    assert "actor_user_id=None" in source
    assert "automation_event_id=event.event_id" in source
    assert 'prefix="/api/v1/automation"' in source

    assert "app.include_router(automation_commands_router)" in main
    assert (
        "app.include_router(automation_commands_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
        not in main
    )


def test_automation_command_fails_closed_until_bulk_publish_is_enabled() -> None:
    source = COMMANDS.read_text()
    assert "if not settings.shopify_publish_enabled:" in source
    assert '"Automated Shopify publishing is locked off"' in source
    assert "MAX_AUTOMATION_COMMAND_BODY_BYTES = 64 * 1024" in source
