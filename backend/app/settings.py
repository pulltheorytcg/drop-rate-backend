from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    auth_issuer: str
    auth_audience: str
    jwks_url: str
    supabase_url: str
    supabase_publishable_key: str
    environment: str
    db_pool_min: int
    db_pool_max: int
    parse_api_key: str | None
    ebay_client_id: str | None
    ebay_client_secret: str | None
    ebay_marketplace_id: str
    ebay_deletion_verification_token: str | None
    ebay_deletion_endpoint: str | None
    market_ingestion_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        issuer = _required("TCG_AUTH_ISSUER").rstrip("/")
        pool_min = _positive_int("TCG_DB_POOL_MIN", 1)
        pool_max = _positive_int("TCG_DB_POOL_MAX", 5)
        if pool_min > pool_max:
            raise RuntimeError("TCG_DB_POOL_MIN cannot exceed TCG_DB_POOL_MAX")
        if not issuer.endswith("/auth/v1"):
            raise RuntimeError("TCG_AUTH_ISSUER must end with /auth/v1")
        return cls(
            database_url=_required("TCG_DATABASE_URL"),
            auth_issuer=issuer,
            auth_audience=_required("TCG_AUTH_AUDIENCE"),
            jwks_url=os.getenv("TCG_JWKS_URL", f"{issuer}/.well-known/jwks.json").strip(),
            supabase_url=issuer.removesuffix("/auth/v1"),
            supabase_publishable_key=_required("TCG_SUPABASE_PUBLISHABLE_KEY"),
            environment=os.getenv("TCG_ENVIRONMENT", "development").strip(),
            db_pool_min=pool_min,
            db_pool_max=pool_max,
            parse_api_key=_optional("TCG_PARSE_API_KEY"),
            ebay_client_id=_optional("TCG_EBAY_CLIENT_ID"),
            ebay_client_secret=_optional("TCG_EBAY_CLIENT_SECRET"),
            ebay_marketplace_id=os.getenv("TCG_EBAY_MARKETPLACE_ID", "EBAY_GB").strip() or "EBAY_GB",
            ebay_deletion_verification_token=_optional("TCG_EBAY_DELETION_VERIFICATION_TOKEN"),
            ebay_deletion_endpoint=_optional("TCG_EBAY_DELETION_ENDPOINT"),
            market_ingestion_enabled=_boolean("TCG_MARKET_INGESTION_ENABLED", False),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
