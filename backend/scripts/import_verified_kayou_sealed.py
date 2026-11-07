"""One-time, explicit, admin-only import of four publisher-verified Naruto SKUs.

Dry-run is the default. No website requests, price imports, stock creation,
Shopify publishing, or external seller activation.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from uuid import UUID, uuid4

from app.access_control import require_platform_admin
from app.db import create_pool, user_connection
from app.settings import get_settings
from app.verified_kayou_sealed import candidate_manifest, register_verified_publisher_products


async def run(actor: UUID, *, apply: bool) -> dict:
    candidates = candidate_manifest()
    if not apply:
        return {"mode": "DRY_RUN", "candidate_count": len(candidates),
                "manufacturer_models": [p["provider_id"] for _, p in candidates],
                "market_prices_added": 0, "inventory_items_changed": 0,
                "catalogue_products_created": 0}
    pool = await create_pool(get_settings())
    try:
        async with user_connection(pool, actor, str(uuid4())) as connection:
            await require_platform_admin(connection)
            return {"mode": "APPLIED", **(await register_verified_publisher_products(connection))}
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-user-id", type=UUID, required=False)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and args.actor_user_id is None:
        parser.error("--apply requires an authorised platform-admin --actor-user-id")
    result = asyncio.run(run(args.actor_user_id, apply=args.apply))
    print("KAYOU_SEALED_CURATED " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
