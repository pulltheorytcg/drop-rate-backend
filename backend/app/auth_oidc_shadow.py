"""INACTIVE OIDC migration boundary for Supabase Auth retirement.

This module is deliberately NOT wired into FastAPI require_user, its session
store, any current login page or founder permissions. Existing sessions and
Supabase Auth stay live. No passwords, MFA secrets, email auto-linking or refresh
tokens are copied. The replacement provider requires an independently verified
exact provider+external-subject -> legacy UUID mapping, as staged in private D1.

Purpose: reject issuer/audience/key confusion and trust no claims about owner
roles. Only deterministic database membership/roster can authorise founders.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID
import re

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError


ALGORITHMS=("RS256","ES256")
PROVIDER_RE=re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
MAX_TOKEN_BYTES=8192
MAX_SUBJECT_LENGTH=256


class OIDCIdentityError(ValueError):
    pass


def _https_url(text:str) -> tuple[str,str]:
    if not isinstance(text,str) or len(text)>1024:
        raise OIDCIdentityError("Unexpected OIDC URL")
    parsed=urlsplit(text)
    if (parsed.scheme!="https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None,443)
            or parsed.query or parsed.fragment
            or parsed.hostname in {"localhost","127.0.0.1","0.0.0.0"}):
        raise OIDCIdentityError("OIDC authority must be fixed HTTPS")
    return parsed.hostname.lower(),parsed.path


@dataclass(frozen=True,slots=True)
class TrustedOIDCProvider:
    provider: str
    issuer: str
    audience: str
    jwks_url: str

    def __post_init__(self):
        if (not isinstance(self.provider,str)
                or not PROVIDER_RE.fullmatch(self.provider)
                or self.provider=="supabase"
                or not isinstance(self.audience,str)
                or not 3<=len(self.audience)<=256
                ):
            raise OIDCIdentityError("Expected separately configured external identity provider")
        issuer_host,_=_https_url(self.issuer)
        jwks_host,jwks_path=_https_url(self.jwks_url)
        if issuer_host!=jwks_host or not jwks_path.endswith("/.well-known/jwks.json"):
            raise OIDCIdentityError("JWKS endpoint must belong to the exact trusted issuer host")


@dataclass(frozen=True,slots=True)
class VerifiedExternalSubject:
    provider: str
    subject: str
    issuer: str

    # NOTE: intentionally no owner ID, founder slot, role, email or privileges.


def verify_external_token(token:str,trust:TrustedOIDCProvider,
                          jwks:PyJWKClient) -> VerifiedExternalSubject:
    """Verify signature, issuer, audience and time. Do not map email to UUID."""
    if not isinstance(token,str) or not 1<len(token)<=MAX_TOKEN_BYTES:
        raise OIDCIdentityError("Missing or oversized external access token")
    try:
        header=jwt.get_unverified_header(token)
        if not isinstance(header,dict) or header.get("alg") not in ALGORITHMS:
            raise OIDCIdentityError("External token algorithm not allowed")
        signing_key=jwks.get_signing_key_from_jwt(token)
        payload=jwt.decode(
            token,signing_key.key,algorithms=list(ALGORITHMS),
            audience=trust.audience,issuer=trust.issuer,
            options={"require":["exp","iat","iss","aud","sub"],
                     "verify_signature":True,
                     "verify_exp":True,
                     "verify_iat":True,
                     "verify_nbf":True},
        )
        external=payload.get("sub")
        if (not isinstance(external,str)
                or not 1<=len(external)<=MAX_SUBJECT_LENGTH
                or payload.get("is_anonymous") is True):
            raise OIDCIdentityError("Invalid external subject")
        return VerifiedExternalSubject(
            provider=trust.provider,subject=external,issuer=trust.issuer)
    except OIDCIdentityError:
        raise
    except (PyJWTError,KeyError,ValueError,TypeError) as exc:
        raise OIDCIdentityError("Invalid or expired external JWT") from exc


def verified_legacy_identity(rows:list[dict],token:VerifiedExternalSubject,
                             *,generation_id:str) -> UUID:
    """Resolve only a previously verified exact external->internal link.

    D1 rows are obtained server-side. Never accept an owner UUID, email, role
    or member list from JWT claims, even when the JWT is correctly signed.
    No link is auto-created by this function.
    """
    if (not isinstance(rows,list) or not isinstance(generation_id,str)
            or not generation_id.startswith("src-") or len(generation_id)>80):
        raise OIDCIdentityError("Unexpected private identity generation")
    matching=[
        row for row in rows if isinstance(row,dict)
        and row.get("provider")==token.provider
        and row.get("external_subject")==token.subject
        and row.get("generation_id")==generation_id
        and isinstance(row.get("verified_at"),str) and row["verified_at"].strip()
    ]
    if len(rows)!=1 or len(matching)!=1:
        raise OIDCIdentityError("Unlinked, ambiguous or unverified external subject")
    try:
        return UUID(str(matching[0]["legacy_user_id"]))
    except (ValueError,TypeError,KeyError) as exc:
        raise OIDCIdentityError("Invalid private legacy UUID mapping") from exc


def read_verified_identity_link(client,dbid:str,generation_id:str,
                                token:VerifiedExternalSubject) -> UUID:
    """Read D1 identity link; deliberately neither create nor mutate it."""
    if not isinstance(dbid,str) or not re.fullmatch(r"[a-fA-F0-9-]{36}",dbid):
        raise OIDCIdentityError("Invalid protected D1 database selector")
    sql=(
        "SELECT generation_id,legacy_user_id,provider,external_subject,verified_at "
        "FROM ops_shadow_identity_map WHERE generation_id=? "
        "AND provider=? AND external_subject=? LIMIT 2"
    )
    try:
        result,_=client.query(dbid,sql,[
            generation_id,token.provider,token.subject])
        rows=result.get("results") if isinstance(result,dict) else None
    except Exception as exc:
        raise OIDCIdentityError("Identity look-up failed closed") from exc
    return verified_legacy_identity(rows,token,generation_id=generation_id)
