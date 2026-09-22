from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    auth_issuer: str
    auth_audience: str
    jwks_url: str
    environment: str
    db_pool_min: int
    db_pool_max: int

    @classmethod
    def from_env(cls) -> "Settings":
        issuer = _required("TCG_AUTH_ISSUER").rstrip("/")
        pool_min = _positive_int("TCG_DB_POOL_MIN", 1)
        pool_max = _positive_int("TCG_DB_POOL_MAX", 5)
        if pool_min > pool_max:
            raise RuntimeError("TCG_DB_POOL_MIN cannot exceed TCG_DB_POOL_MAX")
        return cls(
            database_url=_required("TCG_DATABASE_URL"),
            auth_issuer=issuer,
            auth_audience=_required("TCG_AUTH_AUDIENCE"),
            jwks_url=os.getenv(
                "TCG_JWKS_URL", f"{issuer}/.well-known/jwks.json"
            ).strip(),
            environment=os.getenv("TCG_ENVIRONMENT", "development").strip(),
            db_pool_min=pool_min,
            db_pool_max=pool_max,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
