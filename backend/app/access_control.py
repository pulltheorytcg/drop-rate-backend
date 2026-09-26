from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1/access", tags=["access-control"])


async def current_access_context(connection: asyncpg.Connection) -> dict:
    row = await connection.fetchrow(
        """
        select
            m.user_id,
            m.owner_id,
            m.role,
            m.active as membership_active,
            o.display_name,
            o.owner_type,
            o.active as owner_active,
            o.founder_slot
        from tcg.owner_memberships m
        join tcg.owners o on o.id=m.owner_id
        where m.user_id=tcg.current_user_id()
          and m.active
          and o.active
        order by m.created_at,m.id
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")

    role = str(row["role"])
    if role not in {"PLATFORM_ADMIN", "OWNER"}:
        raise HTTPException(status_code=403, detail="Unsupported access role")

    return {
        "user_id": row["user_id"],
        "owner_id": row["owner_id"],
        "access_role": role,
        "owner_type": row["owner_type"],
        "display_name": row["display_name"],
        "founder_slot": row["founder_slot"],
        "founder_hq_allowed": role == "PLATFORM_ADMIN",
        "portal": "FOUNDER_HQ" if role == "PLATFORM_ADMIN" else "OWNER_PORTAL",
    }


async def require_platform_admin(connection: asyncpg.Connection) -> dict:
    context = await current_access_context(connection)
    if context["access_role"] != "PLATFORM_ADMIN":
        raise HTTPException(status_code=403, detail="Platform administrator access required")
    return context


@router.get("/me")
async def get_access_context(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        context = await current_access_context(connection)
    return jsonable_encoder({"access": context})


async def require_platform_admin_request(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """FastAPI dependency for routes that belong exclusively to Founder HQ admins."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        return await require_platform_admin(connection)


async def require_owner_portal(connection: asyncpg.Connection) -> dict:
    context = await current_access_context(connection)
    if context["access_role"] != "OWNER" or context["portal"] != "OWNER_PORTAL":
        raise HTTPException(status_code=403, detail="Owner portal access required")
    return context


async def require_owner_portal_request(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """FastAPI dependency for APIs exposed only to restricted owner accounts."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        return await require_owner_portal(connection)
