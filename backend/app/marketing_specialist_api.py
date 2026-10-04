"""Signed internal API and PostgreSQL repository for nonpublishing specialists."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from .access_control import require_platform_admin
from .db import user_connection
from .marketing_specialists import (
    Command, JobInput, MODEL, PROMPT_VERSION, OpenAIModel, StrictModel,
    digest, registry, run_specialist,
)
from .settings import get_settings

router = APIRouter(prefix='/marketing', tags=['marketing-specialists'])


class ActorCommand(StrictModel):
    actor_user_id: UUID


class JobCommand(ActorCommand):
    job_id: UUID
    revision: Literal[1] = 1


class CreateCommand(JobCommand):
    input: JobInput


def require_enabled():
    if os.getenv('TCG_MARKETING_SPECIALISTS_ENABLED', '').strip().lower() != 'true':
        raise HTTPException(409, 'Marketing specialists are disabled')


async def verified(request: Request, schema):
    # Delayed import avoids a cycle with the existing automation router.
    from .automation_commands import _verified_command_body
    body = await _verified_command_body(
        request,
        timestamp_header=request.headers.get('X-Drop-Rate-Timestamp'),
        signature_header=request.headers.get('X-Drop-Rate-Signature'),
    )
    try:
        return schema.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, 'Invalid marketing specialist command') from None


class PostgresStore:
    def __init__(self, pool, actor_user_id: UUID, request_id: str):
        self.pool, self.actor, self.request_id = pool, actor_user_id, request_id

    @asynccontextmanager
    async def connection(self):
        async with user_connection(self.pool, self.actor, self.request_id) as connection:
            await require_platform_admin(connection)
            yield connection

    async def read_job(self, command) -> dict:
        async with self.connection() as connection:
            row = await connection.fetchrow(
                'select * from tcg.marketing_specialist_jobs where id=$1 and revision=$2 and created_by=$3',
                command.job_id, command.revision, self.actor,
            )
        if not row:
            raise HTTPException(404, 'Marketing job not found')
        return dict(row)

    async def read_stage(self, command, stage: str):
        async with self.connection() as connection:
            row = await connection.fetchrow(
                'select * from tcg.marketing_specialist_runs where job_id=$1 and revision=$2 and stage=$3 and created_by=$4',
                command.job_id, command.revision, stage, self.actor,
            )
        return dict(row) if row else None

    async def create(self, command: CreateCommand):
        value = command.input.model_dump(mode='json')
        input_hash = digest(value)
        async with self.connection() as connection:
            # Serialise per-actor job creation to enforce a bounded daily allowance.
            await connection.execute("select pg_advisory_xact_lock(hashtextextended('marketing:' || $1, 0))", str(self.actor))
            old = await connection.fetchrow('select * from tcg.marketing_specialist_jobs where id=$1 and revision=$2', command.job_id, command.revision)
            if old:
                if str(old['created_by']) != str(self.actor) or old['input_sha256'] != input_hash:
                    raise HTTPException(409, 'Job ID conflicts with an immutable input')
                return dict(old)
            count = await connection.fetchval(
                "select count(*) from tcg.marketing_specialist_jobs where created_by=$1 and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'",
                self.actor,
            )
            if count >= 10:
                raise HTTPException(429, 'Daily marketing job limit reached')
            row = await connection.fetchrow(
                'insert into tcg.marketing_specialist_jobs(id,revision,created_by,input,input_sha256) values($1,$2,$3,$4::jsonb,$5) on conflict do nothing returning *',
                command.job_id, command.revision, self.actor, value, input_hash,
            )
            if not row:
                raise HTTPException(409, 'Job ID unavailable')
            return dict(row)

    async def claim(self, command: Command, context: dict, input_hash: str, prompt_hash: str):
        async with self.connection() as connection:
            await connection.execute("select pg_advisory_xact_lock(hashtextextended('marketing:' || $1, 0))", str(self.actor))
            # Worker loss is not permission to reissue a paid call. Retain UNKNOWN.
            await connection.execute(
                "update tcg.marketing_specialist_runs set state='UNKNOWN',output_sha256=$2,output='{\"error_code\":\"WORKER_RESULT_UNKNOWN\"}'::jsonb,finished_at=now() where created_by=$1 and state='RUNNING' and started_at < now()-interval '5 minutes'",
                self.actor, digest({'error_code': 'WORKER_RESULT_UNKNOWN'}),
            )
            existing = await connection.fetchrow(
                'select * from tcg.marketing_specialist_runs where job_id=$1 and revision=$2 and stage=$3 and created_by=$4',
                command.job_id, command.revision, command.stage, self.actor,
            )
            if existing:
                return False, dict(existing)
            daily = await connection.fetchval(
                "select count(*) from tcg.marketing_specialist_runs where created_by=$1 and started_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'", self.actor,
            )
            active = await connection.fetchval("select count(*) from tcg.marketing_specialist_runs where created_by=$1 and state='RUNNING'", self.actor)
            if daily >= 30 or active >= 2:
                raise HTTPException(429, 'Marketing run allowance reached')
            row = await connection.fetchrow(
                'insert into tcg.marketing_specialist_runs(job_id,revision,stage,created_by,input,input_sha256,prompt_version,prompt_sha256,model) values($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9) on conflict do nothing returning *',
                command.job_id, command.revision, command.stage, self.actor, context, input_hash, PROMPT_VERSION, prompt_hash, MODEL,
            )
            if not row:
                raise HTTPException(409, 'Marketing run already claimed')
            return True, dict(row)

    async def finish(self, command: Command, state: str, output: dict, usage: dict):
        async with self.connection() as connection:
            row = await connection.fetchrow(
                "update tcg.marketing_specialist_runs set state=$1,output=$2::jsonb,output_sha256=$3,usage=$4::jsonb,finished_at=now() where job_id=$5 and revision=$6 and stage=$7 and created_by=$8 and state='RUNNING' returning *",
                state, output, digest(output), usage, command.job_id, command.revision, command.stage, self.actor,
            )
            if row:
                return dict(row)
            row = await connection.fetchrow(
                'select * from tcg.marketing_specialist_runs where job_id=$1 and revision=$2 and stage=$3 and created_by=$4',
                command.job_id, command.revision, command.stage, self.actor,
            )
            if not row:
                raise HTTPException(409, 'Marketing run finalisation unavailable')
            return dict(row)


def store_for(request: Request, command):
    return PostgresStore(request.app.state.db_pool, command.actor_user_id, request.state.request_id)


@router.post('/catalog')
async def catalog(request: Request):
    command = await verified(request, ActorCommand)
    async with store_for(request, command).connection():
        pass
    return {'specialists': registry(), 'enabled': os.getenv('TCG_MARKETING_SPECIALISTS_ENABLED', '').strip().lower() == 'true', 'published': False}


@router.post('/create')
async def create_job(request: Request):
    command = await verified(request, CreateCommand)
    require_enabled()
    job = await store_for(request, command).create(command)
    return {'job_id': str(job['id']), 'revision': job['revision'], 'actor_user_id': str(command.actor_user_id),
            'expected_input_sha256': job['input_sha256'], 'publishable': False}


@router.post('/read')
async def read_job(request: Request):
    command = await verified(request, JobCommand)
    store = store_for(request, command)
    job = await store.read_job(command)
    async with store.connection() as connection:
        stages = await connection.fetch('select * from tcg.marketing_specialist_runs where job_id=$1 and revision=$2 and created_by=$3 order by started_at', command.job_id, command.revision, command.actor_user_id)
    return jsonable_encoder({'job': job, 'stages': [dict(row) for row in stages], 'publishable': False, 'published': False})


@router.post('/run')
async def run_stage(request: Request):
    command = await verified(request, Command)
    require_enabled()
    key = get_settings().openai_api_key
    if not key and command.stage != 'publishing':
        raise HTTPException(503, 'Marketing model credential not configured')
    result = await run_specialist(store_for(request, command), OpenAIModel(key or ''), command)
    # n8n receives identifiers/status only. Review outputs live in PostgreSQL.
    selected = {key: result[key] for key in ('stage', 'state', 'reason', 'replayed', 'publishable', 'published') if key in result}
    return {**command.model_dump(mode='json'), **selected}
