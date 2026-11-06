"""Private R2 catalogue export to one explicitly trusted GitHub Actions OIDC job.

Temporary migration-only transport: owner-free, permission-reviewed Lorcast
reference facts. No prices, inventory, owner records, Shopify or R2 writes.
The fixed active Postgres source registry authorizes each R2 content digest.
Disabled unless TCG_R2_D1_SHADOW_EXPORT_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import r2_first_catalogue as codec
from . import r2_first_service
from .access_control import require_platform_admin
from .db import user_connection
from .object_storage import ObjectStorageError

router = APIRouter(prefix="/api/v1/internal/d1-shadow", tags=["internal"], include_in_schema=False)
log = logging.getLogger(__name__)

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS = OIDC_ISSUER + "/.well-known/jwks"
OIDC_AUDIENCE = "drop-rate-readonly-r2-d1-shadow-20261106"
EXPECTED_REPOSITORY = "pulltheorytcg/drop-rate-backend"
EXPECTED_REPOSITORY_ID = "1382317534"
EXPECTED_WORKFLOW_REF = (
    EXPECTED_REPOSITORY + "/.github/workflows/d1-real-r2-to-d1.yml@refs/heads/main"
)
# GitHub automatically uses immutable name@id subjects for repositories
# created after 15 July 2026; our repository was created after that rollout.
EXPECTED_OWNER_ID = "331793868"
EXPECTED_SUBJECT = (
    "repo:pulltheorytcg@" + EXPECTED_OWNER_ID
    + "/drop-rate-backend@" + EXPECTED_REPOSITORY_ID
    + ":ref:refs/heads/main"
)
ALLOWED_SOURCE = ("lorcast", "DISNEY_LORCANA", "English")
YUGIOH_SOURCE = ("ygoprodeck", "YUGIOH", "English")
YUGIOH_WORKFLOW_REF = (
    EXPECTED_REPOSITORY + "/.github/workflows/d1-yugioh-r2-shadow.yml@refs/heads/main"
)
MAX_TOKEN_BYTES = 8192
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")

# The JOSE keys are fetched only from GitHub's fixed HTTPS JWKS endpoint.
# Cache for 5 minutes; failed lookups fail closed and never expose their body.
_jwks_client = jwt.PyJWKClient(OIDC_JWKS, cache_jwk_set=True, lifespan=300, timeout=5)


def verify_github_oidc(
    authorization: str | None, *,
    workflow_ref: str = EXPECTED_WORKFLOW_REF,
    allowed_events: tuple[str, ...] = ("push",),
) -> dict:
    """Verify GitHub-issued JWT signature, audience and the exact main workflow."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    token = authorization[7:]
    if len(token) > MAX_TOKEN_BYTES or token.count(".") != 2 or not token:
        raise HTTPException(401, "Unauthorized")
    try:
        key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=["RS256"],
            audience=OIDC_AUDIENCE, issuer=OIDC_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=15,
        )
    except (jwt.PyJWTError, ValueError, OSError, TimeoutError):
        raise HTTPException(401, "Unauthorized") from None
    requirements = {
        "repository": EXPECTED_REPOSITORY,
        "repository_id": EXPECTED_REPOSITORY_ID,
        "repository_owner_id": EXPECTED_OWNER_ID,
        "workflow_ref": workflow_ref,
        "ref": "refs/heads/main",
        "sub": EXPECTED_SUBJECT,
        "runner_environment": "github-hosted",
    }
    if (any(claims.get(key) != expected for key, expected in requirements.items())
            or claims.get("event_name") not in allowed_events):
        raise HTTPException(403, "Forbidden")
    if (not isinstance(claims.get("run_id"), str)
            or not re.fullmatch(r"[0-9]{1,20}", claims["run_id"])
            or not isinstance(claims.get("sha"), str)
            or not SHA_PATTERN.fullmatch(claims["sha"])):
        raise HTTPException(403, "Forbidden")
    return {"run_id": claims["run_id"], "sha": claims["sha"]}


def _enabled() -> bool:
    return os.getenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED", "false").casefold() in {"1", "true"}


def _verify_export_access(
    request: Request, *,
    workflow_ref: str = EXPECTED_WORKFLOW_REF,
    allowed_events: tuple[str, ...] = ("push",),
) -> None:
    if not _enabled():
        raise HTTPException(404, "Not found")
    verify_github_oidc(
        request.headers.get("authorization"),
        workflow_ref=workflow_ref,
        allowed_events=allowed_events,
    )


async def _active_catalogue_manifest(request: Request, scope: tuple[str, str, str]):
    # The legacy R2 registry has FORCE ROW LEVEL SECURITY. A raw pool read
    # has no tcg.user_id role context and therefore returns NO ROW, even
    # though the publication exists. Do not disable RLS or use a superuser.
    #
    # The signed GitHub OIDC job was already authorized at the route boundary.
    # Inside the database, use the existing verified maintenance principal
    # and require PLATFORM_ADMIN under a bounded read-only transaction.
    try:
        actor = UUID(os.environ.get("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID", ""))
        async with user_connection(
            request.app.state.db_pool, actor, str(uuid4()),
            readonly_snapshot=True,
        ) as conn:
            await require_platform_admin(conn)
            old = await conn.fetchrow("""
              select provider,system_code,language,manifest_sha256,
                     source_revision,source_url,permission_ref,record_count,raw_bytes
              from tcg_private.r2_first_catalogue_publications
              where active and provider=$1
                    and system_code=$2 and language=$3
              """, *scope)
    except Exception as exc:
        log.warning("D1_R2_SHADOW_SOURCE_UNAVAILABLE stage=rls_authorized_read error_type=%s",
                    type(exc).__name__)
        raise HTTPException(503, "Verified source unavailable") from None
    if old is None:
        log.warning("D1_R2_SHADOW_SOURCE_UNAVAILABLE stage=publication_not_visible error_type=Missing")
        raise HTTPException(503, "Active verified catalogue unavailable")
    publication = dict(old)
    stage = "storage_configuration"
    try:
        storage = r2_first_service.storage()
        stage = "manifest_object_read"
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot,
                                      publication["manifest_sha256"])
        stage = "manifest_structural_verification"
        manifest = codec.validate_manifest(codec._decode(raw))
        stage = "manifest_publication_binding"
        r2_first_service._manifest_binding(manifest, publication)
        stage = "manifest_scope"
        if tuple(manifest[field] for field in ("provider","system_code","language")) != scope:
            raise codec.R2FirstCatalogueError("Unexpected catalogue partition")
    except Exception as exc:
        # Only a closed stage name and Python exception CLASS reach logs.
        # Never log an exception string, R2 path, signed request, digest,
        # Cloudflare response, token, JWT claim or private data. Remain 503.
        log.warning("D1_R2_SHADOW_SOURCE_UNAVAILABLE stage=%s error_type=%s",
                    stage, type(exc).__name__)
        raise HTTPException(503, "Verified source unavailable") from None
    return storage, publication, manifest, raw


async def _active_lorcana_manifest(request: Request):
    return await _active_catalogue_manifest(request, ALLOWED_SOURCE)


@router.get("/manifest")
async def exported_manifest(request: Request) -> Response:
    _verify_export_access(request)
    _, _, _, raw = await _active_lorcana_manifest(request)
    return Response(content=raw, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/part/{ordinal}")
async def exported_part(request: Request, ordinal: int) -> Response:
    _verify_export_access(request)
    storage, _, manifest, _ = await _active_lorcana_manifest(request)
    if type(ordinal) is not int or not 0 <= ordinal < len(manifest["parts"]):
        raise HTTPException(404, "Not found")
    part = manifest["parts"][ordinal]
    try:
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot, part["sha256"])
        codec._parse_part(raw, part, ALLOWED_SOURCE)
    except (codec.R2FirstCatalogueError, ObjectStorageError, ValueError):
        raise HTTPException(503, "Verified source unavailable") from None
    return Response(content=raw, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


# The separate Yu-Gi-Oh! import is fixed to its source/workflow. Do not accept
# caller-provided S3 keys, provider names, arbitrary workflow refs, or JWT events.
# Existing Lorcana exports remain scoped to their original push-only workflow.
@router.get("/yugioh/manifest")
async def exported_yugioh_manifest(request: Request) -> Response:
    _verify_export_access(
        request, workflow_ref=YUGIOH_WORKFLOW_REF,
        allowed_events=("push", "schedule"),
    )
    _, _, _, raw = await _active_catalogue_manifest(request, YUGIOH_SOURCE)
    return Response(content=raw, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/yugioh/part/{ordinal}")
async def exported_yugioh_part(request: Request, ordinal: int) -> Response:
    _verify_export_access(
        request, workflow_ref=YUGIOH_WORKFLOW_REF,
        allowed_events=("push", "schedule"),
    )
    storage, _, manifest, _ = await _active_catalogue_manifest(request, YUGIOH_SOURCE)
    if type(ordinal) is not int or not 0 <= ordinal < len(manifest["parts"]):
        raise HTTPException(404, "Not found")
    part = manifest["parts"][ordinal]
    try:
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot, part["sha256"])
        codec._parse_part(raw, part, YUGIOH_SOURCE)
    except (codec.R2FirstCatalogueError, ObjectStorageError, ValueError):
        raise HTTPException(503, "Verified source unavailable") from None
    return Response(content=raw, media_type="application/json",
                    headers={"Cache-Control": "no-store"})
