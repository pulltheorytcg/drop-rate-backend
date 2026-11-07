"""Disabled-by-default signed private archive transport for one n8n workflow.

JSON commands use the existing Drop Rate timestamp/body HMAC. Binary readback
signs a bounded JSON envelope in X-Drop-Rate-Command; that envelope binds the
authoritative source digest/size and reserved Drive file. Actual body bytes are
streamed and independently hashed before any durable success receipt is written.
"""
from __future__ import annotations

import base64
import asyncio
from datetime import datetime, timezone
import hashlib
import os
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .automation_dispatcher import verify_signed_body
from .drive_archive_transfer import (
    ArchiveTransfer, ArchiveTransferError, CHUNK_BYTES, MAX_OBJECT_BYTES,
    storage_call, validate_destination,
)
from .settings import get_settings

router = APIRouter(prefix='/api/v1/automation/commands/storage/drive-archive',
                   tags=['private-archive-transfer'])
MAX_COMMAND_BYTES = 64 * 1024
MAX_ENVELOPE_BYTES = 8 * 1024
COMMAND_READ_SECONDS = 10


class CommonCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1]
    execution_id: str = Field(min_length=1,max_length=120,pattern=r'^[A-Za-z0-9_.:-]+$')
    occurred_at: datetime
    destination: dict

    @model_validator(mode='after')
    def current_command(self):
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError('Aware command timestamp required')
        if abs((datetime.now(timezone.utc)-self.occurred_at).total_seconds()) > 300:
            raise ValueError('Current command timestamp required')
        return self


class ArchiveCommand(CommonCommand):
    kind: Literal['REFERENCE_HISTORY','OPENLIBRARY_REVIEWED']
    manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class PlanCommand(CommonCommand):
    action: Literal['PLAN_DRIVE_ARCHIVE_COPY']
    kind: Literal['REFERENCE_HISTORY','OPENLIBRARY_REVIEWED']
    cursor: str | None = Field(default=None,max_length=1500)
    limit: int = Field(default=2,ge=1,le=2,strict=True)


class MemberCommand(ArchiveCommand):
    object_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ReserveCommand(MemberCommand):
    action: Literal['RESERVE_DRIVE_ARCHIVE_FILE']
    proposed_file_id: str = Field(pattern=r'^[A-Za-z0-9_-]{10,200}$')


class ReadCommand(MemberCommand):
    action: Literal['READ_DRIVE_ARCHIVE_OBJECT']


class VerifyCommand(MemberCommand):
    action: Literal['VERIFY_DRIVE_ARCHIVE_READBACK']
    drive_file: dict


class CompleteCommand(ArchiveCommand):
    action: Literal['COMPLETE_DRIVE_ARCHIVE_COPY']


def _error(exc):
    code = str(exc)
    if code == 'OBJECT_NOT_FOUND':
        status = 404
    elif code in {'ARCHIVE_COPY_INCOMPLETE','FILE_ID_NOT_RESERVED'}:
        status = 409
    elif code.startswith(('INVALID_','UNSUPPORTED_','DESTINATION_','DRIVE_FILE_',
                          'SOURCE_CHECKPOINT_','SOURCE_MEMBER_','OBJECT_NOT_IN_')):
        status = 422
    elif code.endswith(('_MISMATCH','_INVALID')):
        status = 502
    else:
        status = 503
    return HTTPException(status_code=status,detail=code)


def _verify_hmac(request, raw):
    secret = str(get_settings().automation_command_secret or '').strip()
    if len(secret) < 32:
        raise HTTPException(503,'ARCHIVE_COMMAND_AUTH_UNAVAILABLE')
    if not verify_signed_body(secret=secret,body=raw,
            timestamp_header=request.headers.get('X-Drop-Rate-Timestamp'),
            signature_header=request.headers.get('X-Drop-Rate-Signature')):
        raise HTTPException(401,'INVALID_ARCHIVE_COMMAND_SIGNATURE')
    if os.getenv('TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED','false').strip().lower() not in {'true','1'}:
        raise HTTPException(409,'DRIVE_ARCHIVE_TRANSFER_DISABLED')


async def _command(request, model, *, binary=False):
    if binary:
        encoded = request.headers.get('X-Drop-Rate-Command','')
        if not 0 < len(encoded) <= MAX_ENVELOPE_BYTES or not re.fullmatch(r'[A-Za-z0-9_-]+',encoded):
            raise HTTPException(413,'INVALID_ARCHIVE_COMMAND_ENVELOPE')
        try:
            raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,'INVALID_ARCHIVE_COMMAND_ENVELOPE') from exc
        if base64.urlsafe_b64encode(raw).decode().rstrip('=') != encoded:
            raise HTTPException(422,'INVALID_ARCHIVE_COMMAND_ENVELOPE')
    else:
        body = bytearray()
        try:
            async with asyncio.timeout(COMMAND_READ_SECONDS):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_COMMAND_BYTES:
                        raise HTTPException(413,'ARCHIVE_COMMAND_TOO_LARGE')
                    body.extend(chunk)
        except TimeoutError as exc:
            raise HTTPException(408,'ARCHIVE_COMMAND_READ_TIMEOUT') from exc
        raw = bytes(body)
        if not raw:
            raise HTTPException(413,'ARCHIVE_COMMAND_EMPTY')
    _verify_hmac(request,raw)
    try:
        command = model.model_validate_json(raw)
        validate_destination(command.destination)
    except ValidationError as exc:
        raise HTTPException(422,'INVALID_ARCHIVE_COMMAND') from exc
    except ArchiveTransferError as exc:
        raise _error(exc) from exc
    return command


def _service(request):
    # Tests inject a synthetic bucket; normal app setup never sets this field.
    service = getattr(request.app.state,'drive_archive_transfer',None)
    if service is not None:
        return service
    try:
        return ArchiveTransfer.configured()
    except Exception as exc:
        raise HTTPException(503,'PRIVATE_ARCHIVE_STORAGE_UNAVAILABLE') from exc


async def _bundle(service, command):
    return await storage_call(service.load_archive,command.kind,command.manifest_sha256)


@router.post('/plan')
async def plan(request: Request):
    command = await _command(request,PlanCommand)
    try:
        result = await storage_call(_service(request).plan,command.kind,
                                    cursor=command.cursor,limit=command.limit)
    except ArchiveTransferError as exc:
        raise _error(exc) from exc
    return {'accepted':True,'execution_id':command.execution_id,**result}


@router.post('/reserve')
async def reserve(request: Request):
    command = await _command(request,ReserveCommand)
    service = _service(request)
    try:
        bundle = await _bundle(service,command)
        member = bundle.member(command.object_sha256)
        result = await storage_call(service.reserve,bundle,member,command.proposed_file_id)
    except ArchiveTransferError as exc:
        raise _error(exc) from exc
    return {'accepted':True,'execution_id':command.execution_id,**result}


@router.post('/object')
async def read_object(request: Request):
    command = await _command(request,ReadCommand)
    service = _service(request)
    try:
        bundle = await _bundle(service,command)
        staged = await storage_call(service.stage,bundle,bundle.member(command.object_sha256))
    except ArchiveTransferError as exc:
        raise _error(exc) from exc

    async def body():
        try:
            with staged.path.open('rb') as source:
                while chunk := source.read(CHUNK_BYTES):
                    yield chunk
        finally:
            staged.cleanup()

    return StreamingResponse(body(),media_type=staged.member.mime_type,headers={
        'Content-Length':str(staged.member.size_bytes),
        'Content-Disposition':f'attachment; filename="{staged.file_name}"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'X-Drop-Rate-Content-SHA256':staged.member.sha256,
    })


@router.post('/verify-readback')
async def verify_readback(request: Request):
    command = await _command(request,VerifyCommand,binary=True)
    service = _service(request)
    try:
        bundle = await _bundle(service,command)
        member = bundle.member(command.object_sha256)
        permission = validate_destination(command.destination)
        await storage_call(service.validate_drive_file,bundle,member,command.drive_file,permission)
        content_length = request.headers.get('content-length')
        if content_length is not None and (not content_length.isdigit() or int(content_length) != member.size_bytes):
            raise ArchiveTransferError('DRIVE_READBACK_SIZE_MISMATCH')
        sha, size = hashlib.sha256(), 0
        # This is an independently computed checksum of the downloaded bytes,
        # never a caller-provided Google checksum or a metadata listing result.
        async with asyncio.timeout(120):
            async for chunk in request.stream():
                size += len(chunk)
                if size > min(member.size_bytes,MAX_OBJECT_BYTES):
                    raise ArchiveTransferError('DRIVE_READBACK_SIZE_MISMATCH')
                sha.update(chunk)
        result = await storage_call(service.record_verified_bytes,bundle,member,command.drive_file,
            actual_sha256=sha.hexdigest(),actual_size=size,execution_id=command.execution_id,
            account_permission_id=permission)
    except TimeoutError as exc:
        raise HTTPException(408,'DRIVE_READBACK_TIMEOUT') from exc
    except ArchiveTransferError as exc:
        raise _error(exc) from exc
    return {'accepted':True,'execution_id':command.execution_id,**result}


@router.post('/complete')
async def complete(request: Request):
    command = await _command(request,CompleteCommand)
    service = _service(request)
    try:
        bundle = await _bundle(service,command)
        result = await storage_call(service.complete,bundle,command.execution_id)
    except ArchiveTransferError as exc:
        raise _error(exc) from exc
    return {'accepted':True,'execution_id':command.execution_id,**result}
