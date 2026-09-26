from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from .settings import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: UUID
    session_id: str | None
    email: str | None = None


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    settings = get_settings()
    return PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=300)


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )

    settings = get_settings()
    try:
        token = credentials.credentials
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_signature": True,
            },
        )
        if claims.get("is_anonymous") is True:
            raise InvalidTokenError("Anonymous sessions are not allowed")
        if claims.get("role") != "authenticated":
            raise InvalidTokenError("Authenticated role required")
        user_id = UUID(str(claims["sub"]))
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc

    email_claim = claims.get("email")
    email = str(email_claim).strip() if email_claim else None
    return AuthenticatedUser(
        user_id=user_id,
        session_id=claims.get("session_id"),
        email=email,
    )
