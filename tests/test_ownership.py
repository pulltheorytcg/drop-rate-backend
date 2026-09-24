from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ownership import current_owner


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    async def fetch(self, sql: str):
        self.sql = sql
        return self.rows


@pytest.mark.asyncio
async def test_current_owner_resolves_through_authenticated_membership() -> None:
    connection = FakeConnection(
        [
            {
                "id": "owner-2",
                "display_name": "Riaz",
                "owner_type": "FOUNDER",
                "founder_slot": 2,
                "role": "FOUNDER",
            }
        ]
    )

    owner = await current_owner(connection)

    assert owner["id"] == "owner-2"
    assert "owner_memberships" in connection.sql
    assert "m.user_id = tcg.current_user_id()" in connection.sql
    assert "where active" not in connection.sql.lower()


@pytest.mark.asyncio
async def test_current_owner_rejects_unlinked_user() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await current_owner(FakeConnection([]))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No active owner membership"


@pytest.mark.asyncio
async def test_current_owner_fails_closed_on_multiple_active_memberships() -> None:
    rows = [
        {"id": "a", "display_name": "A", "owner_type": "FOUNDER", "founder_slot": 1, "role": "FOUNDER"},
        {"id": "b", "display_name": "B", "owner_type": "FOUNDER", "founder_slot": 2, "role": "FOUNDER"},
    ]

    with pytest.raises(HTTPException) as exc_info:
        await current_owner(FakeConnection(rows))

    assert exc_info.value.status_code == 409
