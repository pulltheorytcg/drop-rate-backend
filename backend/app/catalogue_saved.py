"""Private account bookmarks for catalogue references, never physical inventory."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from .access_control import current_access_context
from .auth import AuthenticatedUser, require_user
from .catalogue_browser import SOURCE_CTE
from .db import user_connection


router = APIRouter(prefix="/api/v1/catalogue-browser/saved", tags=["catalogue-saved"])
KEY_PATTERN = r"^(?:[rs]:[a-f0-9]{32}|x:[a-f0-9]{64}|c:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$"
ReferenceKey = Annotated[str, Field(pattern=KEY_PATTERN, max_length=80)]
SAVED_LIMIT = 100


class SavedReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ReferenceKey


class DeviceSavedImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[ReferenceKey] = Field(min_length=1, max_length=SAVED_LIMIT)
    confirmed: Literal[True]


async def _access(connection):
    access = await current_access_context(connection)
    if not await connection.fetchval("select to_regclass('tcg.catalogue_saved_references') is not null"):
        raise HTTPException(503, "Saved references are temporarily unavailable. Please try again shortly.")
    return access


async def _keys(connection, user_id):
    rows = await connection.fetch(
        "select reference_key from tcg.catalogue_saved_references "
        "where user_id=$1 order by created_at desc,reference_key limit 100", user_id)
    return [row["reference_key"] for row in rows]


async def _save(connection, access, user_id, requested, *, importing=False):
    # Serialize this account's writes, including concurrent tabs, before enforcing
    # the bounded list. The caller can never nominate a different account.
    await connection.execute(
        "select pg_advisory_xact_lock(hashtextextended('catalogue_saved:' || $1::text,0))",
        str(user_id))
    previous = set(await _keys(connection, user_id))
    requested = list(dict.fromkeys(requested))
    unknown = [key for key in requested if key not in previous]
    available = set()
    legacy_unknown = [key for key in unknown if not key.startswith('x:')]
    if legacy_unknown:
        rows = await connection.fetch(SOURCE_CTE + "select key from entries where key=any($2::text[])",
                                      access["owner_id"], legacy_unknown)
        available = {row["key"] for row in rows}
    from . import r2_first_service
    for key in unknown:
        if key.startswith('x:') and await r2_first_service.resolve(connection, key) is not None:
            available.add(key)
    rejected = [key for key in unknown if key not in available]
    if rejected and not importing:
        raise HTTPException(404, "This reference is no longer available in the catalogue.")
    additions = [key for key in unknown if key in available]
    if len(previous) + len(additions) > SAVED_LIMIT:
        raise HTTPException(409, "You can save up to 100 references. Remove a saved reference before adding more.")
    if additions:
        await connection.execute(
            "insert into tcg.catalogue_saved_references(user_id,reference_key) "
            "select $1,reference_key from unnest($2::text[]) as reference_key "
            "on conflict (user_id,reference_key) do nothing", user_id, additions)
    return {"keys": await _keys(connection, user_id), "limit": SAVED_LIMIT,
            "imported_count": len(additions), "unavailable_keys": rejected}


@router.get("")
async def saved_references(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _access(connection)
        return {"keys": await _keys(connection, user.user_id), "limit": SAVED_LIMIT}


@router.put("")
async def save_reference(payload: SavedReference, request: Request,
                         user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        access = await _access(connection)
        return await _save(connection, access, user.user_id, [payload.key])


@router.post("/import")
async def import_device_references(payload: DeviceSavedImport, request: Request,
                                   user: Annotated[AuthenticatedUser, Depends(require_user)]):
    # There is no background import: the browser must explicitly confirm this
    # signed-in account's own legacy device list before sending these keys.
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        access = await _access(connection)
        return await _save(connection, access, user.user_id, payload.keys, importing=True)


@router.delete("/{key}")
async def remove_reference(key: Annotated[str, Path(pattern=KEY_PATTERN, max_length=80)], request: Request,
                           user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _access(connection)
        await connection.execute(
            "select pg_advisory_xact_lock(hashtextextended('catalogue_saved:' || $1::text,0))", str(user.user_id))
        await connection.execute("delete from tcg.catalogue_saved_references where user_id=$1 and reference_key=$2",
                                 user.user_id, key)
        return {"keys": await _keys(connection, user.user_id), "limit": SAVED_LIMIT}
