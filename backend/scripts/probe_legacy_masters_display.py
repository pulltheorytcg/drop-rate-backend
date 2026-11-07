"""Bounded read-only proof of legacy Masters catalogue and inventory displays.

Run with the configured maintenance actor:
    PYTHONPATH=backend python backend/scripts/probe_legacy_masters_display.py
Only public card identities and aggregate inventory counts are printed.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import UUID

from app.access_control import require_platform_admin
from app.db import create_pool, user_connection
from app.inventory_catalogue_reference import (
    PRODUCTS_SQL, CACHE_SQL, catalogue_guide, catalogue_number_key, catalogue_system,
)
from app.inventory_reference_values import add_shared_reference_values
from app.language import clean_language
from app.settings import get_settings


async def probe(connection):
    now = datetime.now(timezone.utc)
    ids = [r["id"] for r in await connection.fetch("""
        select id from tcg.catalogue_products
        where product_type='CARD' and game='Dragon Ball Super'
        order by id limit 101""")]
    if len(ids) > 100:
        raise ValueError("LEGACY_CATALOGUE_BOUND_EXCEEDED")
    products = [dict(r) for r in await connection.fetch(PRODUCTS_SQL, ids)]
    lookups = [
        dict(catalogue_id=str(p["id"]), system_code=catalogue_system(p),
             number_key=catalogue_number_key(p))
        for p in products if catalogue_system(p) and catalogue_number_key(p) and not p["blocked"]
    ]
    references = defaultdict(list)
    if lookups:
        for row in await connection.fetch(CACHE_SQL, json.dumps(lookups)):
            references[str(row["catalogue_id"])].append(dict(row))
    cards = []
    for product in products:
        guide = catalogue_guide(product, references[str(product["id"])],
                                clean_language(product.get("language")), now=now)
        cards.append({
            **{k: product[k] for k in ("name", "set_name", "card_number", "variant")},
            "guide_minor": guide["market_value_minor"] if guide else None,
            "label": guide["label"] if guide else None,
            "checked_at": guide["checked_at"] if guide else None,
        })
    items = [dict(r) for r in await connection.fetch("""
        select i.id,i.catalogue_id,i.condition,i.grading_company,i.grade,
          i.seal_status,i.language,p.language as catalogue_language,
          p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity
        from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
        where i.catalogue_id=any($1::uuid[])
          and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
        order by i.id limit 501""", ids)]
    if len(items) > 500:
        raise ValueError("LEGACY_INVENTORY_BOUND_EXCEEDED")
    await add_shared_reference_values(connection, items, now=now)
    states = Counter(
        "physical_reference" if i.get("market_value_minor") is not None
        else "display_reference" if (i.get("catalogue_reference") or {}).get("market_value_minor") is not None
        else "unavailable"
        for i in items
    )
    return dict(status="COMPLETE", read_only=True, provider_calls=0, database_writes=0,
                observed_at=now, catalogue_count=len(products),
                catalogue_guides=sum(c["guide_minor"] is not None for c in cards),
                active_inventory_count=len(items), active_inventory_display_counts=dict(states),
                cards=sorted(cards, key=lambda c: (c["set_name"], c["card_number"], c["variant"])))


async def run():
    settings = get_settings()
    actor = settings.catalogue_maintenance_actor_user_id
    if not actor:
        raise ValueError("MAINTENANCE_ADMINISTRATOR_REQUIRED")
    pool = await create_pool(settings)
    try:
        async with user_connection(pool, UUID(actor), "legacy-masters-display-probe") as connection:
            await require_platform_admin(connection)
            return await probe(connection)
    finally:
        await pool.close()


if __name__ == "__main__":
    try:
        result = asyncio.run(asyncio.wait_for(run(), timeout=45))
    except Exception as exc:
        print("LEGACY_MASTERS_DISPLAY " + json.dumps(
            dict(status="FAILED", read_only=True, error_type=type(exc).__name__)), flush=True)
        raise SystemExit(2)
    print("LEGACY_MASTERS_DISPLAY " + json.dumps(result, default=str, sort_keys=True), flush=True)
