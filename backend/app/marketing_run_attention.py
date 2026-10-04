"""Record marketing terminal attention in the caller's existing transaction.

This does not execute a model, approve media, or publish a social post.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from .access_control import require_platform_admin

ATTENTION_STATES = frozenset({'FAILED', 'UNKNOWN', 'NEEDS_REVIEW'})
STAGES = frozenset({'research', 'brief', 'copywriting', 'design', 'social_management'})


async def record_marketing_attention(connection, record: Mapping[str, Any]) -> UUID | None:
    """Insert once, never reopen a resolved alert, and never commit independently.

    The persisted run and verified user determine identity. Provider messages and
    model output are deliberately excluded. An insert failure propagates so the
    caller rolls back finalisation and cannot report a partially saved success.
    """
    if record['state'] not in ATTENTION_STATES:
        return None
    if record['stage'] not in STAGES or record['revision'] != 1:
        raise ValueError('Unsupported marketing attention record')
    context = await require_platform_admin(connection)
    if UUID(str(record['created_by'])) != UUID(str(context['user_id'])):
        raise HTTPException(403, 'Marketing attention actor mismatch')
    owner_id = UUID(str(context['owner_id']))
    run_id = UUID(str(record['id']))
    job_id = UUID(str(record['job_id']))
    state = record['state']
    stage = record['stage']
    metadata = json.dumps({
        'job_id': str(job_id), 'revision': 1, 'run_id': str(run_id),
        'stage': stage, 'state': state, 'publishable': False,
    }, sort_keys=True, separators=(',', ':'))
    row = await connection.fetchrow(
        """
        insert into tcg.action_required_items(
            owner_id, category, code, severity, entity_type, entity_id,
            dedupe_key, title, detail, recommended_action, status, metadata
        ) values($1,'AUTOMATION',$2,$3,'OWNER',$1,$4,$5,$6,$7,'OPEN',$8::jsonb)
        on conflict(owner_id,dedupe_key) do nothing
        returning id
        """,
        owner_id,
        'MARKETING_' + state,
        'MEDIUM' if state == 'NEEDS_REVIEW' else 'HIGH',
        'marketing-run:' + str(run_id),
        'Marketing ' + stage.replace('_', ' ') + ' requires attention',
        'A saved marketing stage is ' + state + '. No publication was authorised.',
        'Review the saved job and evidence. Reconcile unknown outcomes before any retry; do not automatically repeat a paid call.',
        metadata,
    )
    return row['id'] if row is not None else None
