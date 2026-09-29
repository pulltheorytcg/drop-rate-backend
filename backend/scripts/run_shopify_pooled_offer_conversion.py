from __future__ import annotations

import asyncio
import json
import os
import sys

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
    from app.db import create_pool
    from app.settings import Settings
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


async def _run() -> dict:
    settings = Settings.from_env()
    pool = await create_pool(settings)
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
