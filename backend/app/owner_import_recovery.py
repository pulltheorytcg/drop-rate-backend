"""Explicit zero-copy seller preview recovery; never applies inventory."""
import hashlib
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Request

from . import imports
from .auth import AuthenticatedUser, require_user
from .access_control import require_owner_portal
from .db import user_connection
from .ownership import current_owner
from .import_inventory import lock_import_owner
from .import_preview_rebuild import replace_preview, validate_rebuild_batch


def enabled(request):
    return getattr(getattr(request.app.state, 'settings', None), 'owner_import_preview_rebuild_enabled', False) is True


async def rebuild_owner_preview(batch_id: UUID, payload: imports.ImportPreviewRebuildRequest,
                                request: Request,
                                user: Annotated[AuthenticatedUser, Depends(require_user)]) -> dict:
    if not enabled(request):
        raise HTTPException(404, 'Seller import preview recovery is not enabled')
    digest = hashlib.sha256(payload.content.encode('utf-8')).hexdigest()
    try:
        async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as conn:
            await require_owner_portal(conn)
            owner = await current_owner(conn)
            await conn.execute("select set_config('lock_timeout','2s',true)")
            await lock_import_owner(conn, owner['id'])
            batch = await conn.fetchrow('select * from tcg.import_batches where id=$1 and owner_id=$2 for update', batch_id, owner['id'])
            validate_rebuild_batch(batch, version=payload.version, source_sha256=digest, allow_zero_copy_intake=True)
            if await conn.fetchval("""select exists(select 1 from tcg.inventory_items where import_batch_id=$1)
                or exists(select 1 from tcg.import_candidates where batch_id=$1 and status='COMMITTED')""", batch_id):
                raise HTTPException(409, 'This import already added copies; its source mappings cannot be rebuilt')
            if await conn.fetchval("""select exists(select 1 from tcg.import_batches where owner_id=$1
                and id<>$2 and automatic_intake and status='PREVIEW')""", owner['id'], batch_id):
                raise HTTPException(409, 'Finish the other open import before rebuilding this preview')
            original = payload.model_copy(update={'filename': batch['filename']})
            preview = await imports._build_preview(conn, owner, original, imports._parse_preview_source(original))
            result = await replace_preview(conn, actor_id=user.user_id, owner_id=owner['id'], batch_id=batch_id,
                                           version=payload.version, source_sha256=digest, preview=preview, owner_recovery=True)
            response = imports._preview_response(preview, batch_id=batch_id, version=result['version'], request=request, rebuilt=True)
            response['rebuild_enabled'] = True
            return response
    except asyncpg.InsufficientPrivilegeError as exc:
        raise HTTPException(403, 'Active owner access required') from exc
    except (asyncpg.LockNotAvailableError, asyncpg.ObjectNotInPrerequisiteStateError) as exc:
        raise HTTPException(409, 'Import changed or is busy; reopen the current preview') from exc
    except asyncpg.InvalidParameterValueError as exc:
        raise HTTPException(422, 'Preview failed source and candidate validation') from exc
