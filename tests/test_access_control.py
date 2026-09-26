from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.access_control import current_access_context, require_owner_portal, require_platform_admin


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260926213000_access_control_foundation.sql"


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.sql = ""

    async def fetch(self, sql: str):
        self.sql = sql
        if self.row is None:
            return []
        if isinstance(self.row, list):
            return self.row
        return [self.row]


@pytest.mark.asyncio
async def test_platform_admin_context_allows_founder_hq() -> None:
    connection = FakeConnection(
        {
            "user_id": "user-1",
            "owner_id": "owner-1",
            "role": "PLATFORM_ADMIN",
            "membership_active": True,
            "display_name": "Sunny",
            "owner_type": "FOUNDER",
            "owner_active": True,
            "founder_slot": 1,
        }
    )

    context = await current_access_context(connection)

    assert context["access_role"] == "PLATFORM_ADMIN"
    assert context["founder_hq_allowed"] is True
    assert context["portal"] == "FOUNDER_HQ"
    assert "m.user_id=tcg.current_user_id()" in connection.sql
    assert "limit 2" in connection.sql


@pytest.mark.asyncio
async def test_owner_context_is_restricted_to_owner_portal() -> None:
    connection = FakeConnection(
        {
            "user_id": "user-2",
            "owner_id": "owner-2",
            "role": "OWNER",
            "membership_active": True,
            "display_name": "Consignor",
            "owner_type": "CONSIGNOR",
            "owner_active": True,
            "founder_slot": None,
        }
    )

    context = await current_access_context(connection)

    assert context["access_role"] == "OWNER"
    assert context["founder_hq_allowed"] is False
    assert context["portal"] == "OWNER_PORTAL"


@pytest.mark.asyncio
async def test_owner_cannot_pass_platform_admin_guard() -> None:
    connection = FakeConnection(
        {
            "user_id": "user-2",
            "owner_id": "owner-2",
            "role": "OWNER",
            "membership_active": True,
            "display_name": "Consignor",
            "owner_type": "CONSIGNOR",
            "owner_active": True,
            "founder_slot": None,
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_platform_admin(connection)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Platform administrator access required"


@pytest.mark.asyncio
async def test_unlinked_account_fails_closed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await current_access_context(FakeConnection(None))

    assert exc_info.value.status_code == 403


def test_rbac_migration_separates_permission_from_owner_type() -> None:
    sql = MIGRATION.read_text()

    assert "PLATFORM_ADMIN" in sql
    assert "'OWNER'" in sql
    assert "update tcg.owner_memberships" in sql
    assert "where role='FOUNDER'" in sql
    assert "tcg.is_platform_admin()" in sql
    assert "m.user_id=tcg.current_user_id()" in sql
    assert "m.role = 'PLATFORM_ADMIN'" in sql
    assert "values (v_user_id, v_owner.id, 'PLATFORM_ADMIN', true)" in sql
    assert "alter column role set default 'OWNER'" in sql


def test_founder_hq_invite_route_requires_platform_admin() -> None:
    source = (ROOT / "backend" / "app" / "founder_onboarding.py").read_text()

    assert "require_platform_admin" in source
    assert "await require_platform_admin(connection)" in source

def test_internal_control_plane_routers_are_platform_admin_only() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()

    guarded = (
        "pricing_router",
        "imported_benchmark_pricing_router",
        "ebay_sold_pricing_router",
        "pricing_preview_router",
        "market_ingestion_router",
        "market_mappings_router",
        "marketplace_listings_router",
        "market_discovery_router",
        "market_provider_probe_router",
        "market_smoke_router",
        "imports_router",
        "import_review_router",
        "inventory_intake_router",
        "inventory_intelligence_router",
        "inventory_market_values_router",
        "inventory_state_router",
        "identity_review_router",
        "condition_review_router",
        "shopify_pipeline_router",
        "shopify_readiness_router",
        "purchase_lots_router",
        "storage_locations_router",
    )
    for router_name in guarded:
        assert (
            f"app.include_router({router_name}, "
            "dependencies=[Depends(require_platform_admin_request)])"
        ) in main

    assert "from fastapi import Depends, FastAPI, Request" in main

@pytest.mark.asyncio
async def test_owner_passes_owner_portal_guard() -> None:
    connection = FakeConnection(
        {
            "user_id": "user-2",
            "owner_id": "owner-2",
            "role": "OWNER",
            "membership_active": True,
            "display_name": "Consignor",
            "owner_type": "CONSIGNOR",
            "owner_active": True,
            "founder_slot": None,
        }
    )

    context = await require_owner_portal(connection)

    assert context["owner_id"] == "owner-2"
    assert context["access_role"] == "OWNER"
    assert context["portal"] == "OWNER_PORTAL"


@pytest.mark.asyncio
async def test_platform_admin_cannot_use_owner_portal_api_guard() -> None:
    connection = FakeConnection(
        {
            "user_id": "user-1",
            "owner_id": "owner-1",
            "role": "PLATFORM_ADMIN",
            "membership_active": True,
            "display_name": "Sunny",
            "owner_type": "FOUNDER",
            "owner_active": True,
            "founder_slot": 1,
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_owner_portal(connection)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Owner portal access required"

@pytest.mark.asyncio
async def test_multiple_active_memberships_fail_closed() -> None:
    connection = FakeConnection(
        [
            {
                "user_id": "user-3",
                "owner_id": "owner-a",
                "role": "OWNER",
                "membership_active": True,
                "display_name": "Owner A",
                "owner_type": "CONSIGNOR",
                "owner_active": True,
                "founder_slot": None,
            },
            {
                "user_id": "user-3",
                "owner_id": "owner-b",
                "role": "OWNER",
                "membership_active": True,
                "display_name": "Owner B",
                "owner_type": "CONSIGNOR",
                "owner_active": True,
                "founder_slot": None,
            },
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await current_access_context(connection)

    assert exc_info.value.status_code == 409
    assert "Multiple active owner memberships" in exc_info.value.detail

