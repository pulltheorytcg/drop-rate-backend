from __future__ import annotations

import asyncpg
from fastapi import HTTPException


async def current_owner(connection: asyncpg.Connection) -> asyncpg.Record:
    """Resolve the active owner linked to the authenticated user.

    user_connection() sets tcg.user_id from the verified Supabase JWT before any
    route reaches this helper. Ownership therefore follows owner_memberships and
    never falls back to "first active owner".
    """

    rows = await connection.fetch(
        """
        select
            o.id,
            o.display_name,
            o.owner_type,
            o.founder_slot,
            m.role
        from tcg.owner_memberships m
        join tcg.owners o on o.id = m.owner_id
        where m.user_id = tcg.current_user_id()
          and m.active
          and o.active
        order by m.created_at, m.id
        limit 2
        """
    )
    if not rows:
        raise HTTPException(status_code=403, detail="No active owner membership")
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple active owner memberships require administrator review",
        )
    return rows[0]
