"""Private R2 catalogue export to one explicitly trusted GitHub Actions OIDC job.

Temporary migration-only transport: owner-free, permission-reviewed Lorcast
reference facts. No prices, inventory, owner records, Shopify or R2 writes.
The fixed active Postgres source registry authorizes each R2 content digest.
Disabled unless TCG_R2_D1_SHADOW_EXPORT_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import r2_first_catalogue as codec
from . import r2_first_service
from .object_storage import ObjectStorageError

router = APIRouter(prefix="/api/v1/internal/d1-shadow", tags=["internal"], include_in_schema=False)

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
MAX_TOKEN_BYTES = 8192
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")

# The JOSE keys are fetched only from GitHub's fixed HTTPS JWKS endpoint.
# Cache for 5 minutes; failed lookups fail closed and never expose their body.
_jwks_client = jwt.PyJWKClient(OIDC_JWKS, cache_jwk_set=True, lifespan=300, timeout=5)


def verify_github_oidc(authorization: str | None) -> dict:
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
        "workflow_ref": EXPECTED_WORKFLOW_REF,
        "ref": "refs/heads/main",
        "sub": EXPECTED_SUBJECT,
        "event_name": "push",
        "runner_environment": "github-hosted",
    }
    if any(claims.get(key) != expected for key, expected in requirements.items()):
        raise HTTPException(403, "Forbidden")
    if (not isinstance(claims.get("run_id"), str)
            or not re.fullmatch(r"[0-9]{1,20}", claims["run_id"])
            or not isinstance(claims.get("sha"), str)
            or not SHA_PATTERN.fullmatch(claims["sha"])):
        raise HTTPException(403, "Forbidden")
    return {"run_id": claims["run_id"], "sha": claims["sha"]}


def _enabled() -> bool:
    return os.getenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED", "false").casefold() in {"1", "true"}


def _verify_export_access(request: Request) -> None:
    if not _enabled():
        raise HTTPException(404, "Not found")
    verify_github_oidc(request.headers.get("authorization"))


async def _active_lorcana_manifest(request: Request):
    # Read-only legacy pointer is the current migration trust anchor.
    async with request.app.state.db_pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            old = await conn.fetchrow("""
              select provider,system_code,language,manifest_sha256,
                     source_revision,source_url,permission_ref,record_count,raw_bytes
              from tcg_private.r2_first_catalogue_publications
              where active and provider='lorcast'
                    and system_code='DISNEY_LORCANA' and language='English'
              """)
    if old is None:
        raise HTTPException(503, "Active verified catalogue unavailable")
    publication = dict(old)
    storage = r2_first_service.storage()
    try:
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot,
                                      publication["manifest_sha256"])
        manifest = codec.validate_manifest(codec._decode(raw))
        r2_first_service._manifest_binding(manifest, publication)
        if tuple(manifest[field] for field in ("provider","system_code","language")) != ALLOWED_SOURCE:
            raise codec.R2FirstCatalogueError("Unexpected catalogue partition")
    except Exception:
        # Missing object, revoked credentials, transport failures and source
        # validation errors all fail closed with no R2 bucket key disclosure.
        raise HTTPException(503, "Verified source unavailable") from None
    return storage, publication, manifest, raw


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
