"""Bounded Yu-Gi-Oh! reference pilot. Dry-run by default; no pricing or media writes.

Examples:
  PYTHONPATH=backend python backend/scripts/pilot_yugioh_catalogue.py --limit 25
  # Only in the configured admin worker, after CI and catalogue capacity check:
  PYTHONPATH=backend python backend/scripts/pilot_yugioh_catalogue.py --limit 25 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID, uuid4

import asyncpg
import httpx

from app.collectible_source_adapters import ReferenceSourceError, yugioh_printings
from app.reference_library import save_reference_set


ROOT = "https://db.ygoprodeck.com/api/v7"
MAX_PRINTINGS = 1000
MAX_DATABASE_BYTES = 400_000_000


async def preview(*, offset: int, limit: int, client: httpx.AsyncClient) -> tuple[dict, dict]:
    if not 0 <= offset <= 200000 or not 1 <= limit <= 1000:
        raise ValueError("Bounded Yu-Gi-Oh! offset/limit required")
    # Two requests per dry-run, nowhere near the published 20/s provider cap.
    sets_response = await client.get(f"{ROOT}/cardsets.php")
    sets_response.raise_for_status()
    cards_response = await client.get(f"{ROOT}/cardinfo.php",
                                      params={"format": "tcg", "num": limit, "offset": offset})
    cards_response.raise_for_status()
    set_data = sets_response.json()
    cards_data = cards_response.json()
    if (not isinstance(set_data, list) or len(set_data) > 10000
            or not isinstance(cards_data, dict) or not isinstance(cards_data.get("data"), list)
            or len(cards_data["data"]) > limit):
        raise ReferenceSourceError("Unexpected bounded YGOPRODeck API response")
    official_sets = {}
    for item in set_data:
        if not isinstance(item, dict) or not isinstance(item.get("set_name"), str):
            raise ReferenceSourceError("Invalid set catalogue")
        name = item["set_name"]
        if name in official_sets and official_sets[name].get("set_code") != item.get("set_code"):
            raise ReferenceSourceError("Duplicate official set name with different codes")
        official_sets[name] = item

    output = {}
    problems = []
    printing_count = 0
    for card in cards_data["data"]:
        try:
            items = yugioh_printings(card, official_tcg_sets=official_sets)
            if printing_count + len(items) > MAX_PRINTINGS:
                raise ReferenceSourceError("Batch exceeds 1000 printings; use fewer cards")
            for set_record, printing in items:
                bucket = output.get(set_record["set_id"])
                existing = bucket[1].get(printing["provider_id"]) if bucket else None
                if existing is not None and existing != printing:
                    raise ReferenceSourceError("Conflicting printings in same batch")
            # One printing identity can appear in more than one provider page.
            for set_record, printing in items:
                key = set_record["set_id"]
                bucket = output.setdefault(key, [set_record, {}])
                bucket[1][printing["provider_id"]] = printing
            printing_count += len(items)
        except ReferenceSourceError as exc:
            problems.append({"passcode": card.get("id") if isinstance(card, dict) else None,
                             "reason": str(exc)})
    report = {"cards_fetched": len(cards_data["data"]), "printing_candidates": sum(len(v[1]) for v in output.values()),
              "sets": len(output), "quarantined_cards": len(problems),
              "quarantine_sample": problems[:8], "images_mirrored": 0, "verified_prices_added": 0,
              "shopify_products_created": 0}
    return output, report


async def apply_reference_batch(grouped: dict) -> int:
    """Only configured, RLS-verified founder maintenance actors may write."""
    if os.getenv("TCG_EXPANDED_CATALOGUE_IMPORT_ENABLED", "false").lower() != "true":
        raise RuntimeError("Expanded-catalogue import feature flag is disabled")
    dsn = os.getenv("TCG_DATABASE_URL")
    actor = os.getenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID")
    if not dsn or not actor:
        raise RuntimeError("Configured production database and maintenance actor required")
    UUID(actor)
    conn = await asyncpg.connect(dsn=dsn, timeout=10, command_timeout=20,
                                 server_settings={"search_path": "pg_catalog,tcg",
                                                  "statement_timeout": "20000"})
    try:
        async with conn.transaction():
            await conn.execute("select set_config('tcg.user_id', $1, true)", actor)
            await conn.execute("select set_config('tcg.request_id', $1, true)", str(uuid4()))
            if not await conn.fetchval("select tcg.is_platform_admin()"):
                raise RuntimeError("Maintenance actor is not an authorised platform admin")
            size = await conn.fetchval("select pg_database_size(current_database())")
            if size >= MAX_DATABASE_BYTES:
                raise RuntimeError("Database near capacity: reference import postponed")
            for set_record, printings in grouped.values():
                await save_reference_set(conn, set_record, list(printings.values()))
        return sum(len(group[1]) for group in grouped.values())
    finally:
        await conn.close()


async def main(offset: int, limit: int, do_apply: bool) -> None:
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "DropRateReferenceImporter/1.0"}) as client:
        grouped, report = await preview(offset=offset, limit=limit, client=client)
    if do_apply:
        report["printings_saved"] = await apply_reference_batch(grouped)
    else:
        report["printings_saved"] = 0
    report["mode"] = "APPLY" if do_apply else "DRY_RUN"
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--apply", action="store_true", help="RLS-guarded DB write; disabled by default")
    args = parser.parse_args()
    asyncio.run(main(args.offset, args.limit, args.apply))
