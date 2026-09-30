from __future__ import annotations

import asyncio
import json
import os
import sys

print(
    json.dumps(
        {
            "event": "SHOPIFY_ORDER_RECONCILIATION_PROCESS_START",
            "database_url_configured": bool(os.getenv("TCG_DATABASE_URL", "").strip()),
            "shopify_domain_configured": bool(os.getenv("TCG_SHOPIFY_SHOP_DOMAIN", "").strip()),
            "shopify_client_id_configured": bool(os.getenv("TCG_SHOPIFY_CLIENT_ID", "").strip()),
            "shopify_client_secret_configured": bool(os.getenv("TCG_SHOPIFY_CLIENT_SECRET", "").strip()),
        },
        sort_keys=True,
    ),
    flush=True,
)

try:
    import asyncpg

    from app.shopify_client import ShopifyAdminClient
    from app.shopify_reconciliation import reconcile_shopify_orders
except Exception as exc:
    print(
        json.dumps(
            {
                "event": "SHOPIFY_ORDER_RECONCILIATION_IMPORT_FAILED",
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


async def _run() -> int:
    client = ShopifyAdminClient(
        shop_domain=_required("TCG_SHOPIFY_SHOP_DOMAIN"),
        client_id=_required("TCG_SHOPIFY_CLIENT_ID"),
        client_secret=_required("TCG_SHOPIFY_CLIENT_SECRET"),
        api_version=os.getenv("TCG_SHOPIFY_API_VERSION", "2026-07").strip() or "2026-07",
    )

    connection = await asyncpg.connect(
        dsn=_required("TCG_DATABASE_URL"),
        timeout=15,
        command_timeout=30,
        server_settings={
            "application_name": "drop-rate-shopify-reconciliation",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "30000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        result = await reconcile_shopify_orders(connection, client=client)
    finally:
        await connection.close()

    print(
        json.dumps(
            {
                "event": "SHOPIFY_ORDER_RECONCILIATION_COMPLETE",
                "remote_count": result["remote_count"],
                "local_count": result["local_count"],
                "remote_only_count": result["remote_only_count"],
                "remote_anomaly_count": result["remote_anomaly_count"],
                "expected_pending_count": result["expected_pending_count"],
                "acknowledged_cancelled_count": result["acknowledged_cancelled_count"],
                "local_only_count": result["local_only_count"],
                "matched_count": result["matched_count"],
                "opened_alerts": result["opened_alerts"],
                "resolved_alerts": result["resolved_alerts"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> None:
    try:
        code = asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "SHOPIFY_ORDER_RECONCILIATION_FATAL",
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
