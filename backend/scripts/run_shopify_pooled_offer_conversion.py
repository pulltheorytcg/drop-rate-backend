from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

print(
    json.dumps(
        {
            "event": "SHOPIFY_POOLED_OFFER_CONVERSION_PROCESS_START",
            "enabled": os.getenv(
                "TCG_SHOPIFY_POOLED_OFFER_CONVERSION_ENABLED", ""
            ).strip().casefold() in {"1", "true", "yes", "on"},
            "apply": os.getenv(
                "TCG_SHOPIFY_POOLED_OFFER_CONVERSION_APPLY", ""
            ).strip().casefold() in {"1", "true", "yes", "on"},
            "database_url_configured": bool(
                os.getenv("TCG_DATABASE_URL", "").strip()
            ),
            "shopify_domain_configured": bool(
                os.getenv("TCG_SHOPIFY_SHOP_DOMAIN", "").strip()
            ),
        },
        sort_keys=True,
    ),
    flush=True,
)

try:
    import asyncpg

    from app.db import _init_connection
    from app.shopify_pooled_offer_conversion import (
        run_shopify_pooled_offer_conversion,
    )
except Exception as exc:
    print(
        json.dumps(
            {
                "event": "SHOPIFY_POOLED_OFFER_CONVERSION_IMPORT_FAILED",
                "error_code": type(exc).__name__,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    raise


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _bounded_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    value = default if raw is None or not raw.strip() else int(raw)
    if value < minimum or value > maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _conversion_settings() -> SimpleNamespace:
    return SimpleNamespace(
        shopify_pooled_offer_conversion_enabled=_boolean(
            "TCG_SHOPIFY_POOLED_OFFER_CONVERSION_ENABLED", False
        ),
        shopify_pooled_offer_conversion_apply=_boolean(
            "TCG_SHOPIFY_POOLED_OFFER_CONVERSION_APPLY", False
        ),
        shopify_pooled_offer_language_map_json=_optional(
            "TCG_SHOPIFY_POOLED_OFFER_LANGUAGE_MAP_JSON"
        ),
        shopify_pooled_offer_conversion_limit=_bounded_int(
            "TCG_SHOPIFY_POOLED_OFFER_CONVERSION_LIMIT",
            100,
            minimum=1,
            maximum=1000,
        ),
        shopify_catalogue_bootstrap_actor_user_id=_required(
            "TCG_SHOPIFY_CATALOGUE_BOOTSTRAP_ACTOR_USER_ID"
        ),
        shopify_shop_domain=_required("TCG_SHOPIFY_SHOP_DOMAIN"),
        shopify_client_id=_optional("TCG_SHOPIFY_CLIENT_ID"),
        shopify_client_secret=_optional("TCG_SHOPIFY_CLIENT_SECRET"),
        shopify_location_gid=_optional("TCG_SHOPIFY_LOCATION_GID"),
        shopify_publication_gid=_optional("TCG_SHOPIFY_PUBLICATION_GID"),
        shopify_api_version=(
            os.getenv("TCG_SHOPIFY_API_VERSION", "2026-07").strip()
            or "2026-07"
        ),
        media_physical_photo_threshold_minor=_bounded_int(
            "TCG_MEDIA_PHYSICAL_PHOTO_THRESHOLD_MINOR",
            5_000,
            minimum=100,
            maximum=10_000_000,
        ),
    )


async def _run() -> dict:
    settings = _conversion_settings()
    pool = await asyncpg.create_pool(
        dsn=_required("TCG_DATABASE_URL"),
        min_size=1,
        max_size=2,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
        init=_init_connection,
        server_settings={
            "application_name": "drop-rate-shopify-pooled-offer-conversion",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "30000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        return await run_shopify_pooled_offer_conversion(pool, settings)
    finally:
        await pool.close()


def main() -> None:
    try:
        result = asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "SHOPIFY_POOLED_OFFER_CONVERSION_FATAL",
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc

    print(
        "POOLED_OFFER_CONVERSION_RESULT="
        + json.dumps(result, sort_keys=True, default=str),
        flush=True,
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
