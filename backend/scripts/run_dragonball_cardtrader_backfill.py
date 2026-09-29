from __future__ import annotations

import argparse
import asyncio
import json
import os
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.cardtrader_client import CardTraderClient
from app.cardtrader_media import lookup_one as lookup_cardtrader_one
from app.db import create_pool, user_connection
from app.import_enrichment import _process_one, _seed_batch
from app.settings import get_settings


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe or run Dragon Ball import enrichment through existing backend rules."
    )
    parser.add_argument(
        "--mode",
        choices=("probe", "apply"),
        default=_env("TCG_DRAGONBALL_BACKFILL_MODE") or "probe",
    )
    parser.add_argument(
        "--batch-id",
        default=_env("TCG_DRAGONBALL_BACKFILL_BATCH_ID"),
    )
    parser.add_argument(
        "--actor-user-id",
        default=_env("TCG_DRAGONBALL_BACKFILL_ACTOR_USER_ID"),
    )
    parser.add_argument(
        "--default-language",
        default=_env("TCG_DRAGONBALL_BACKFILL_DEFAULT_LANGUAGE") or "English",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(_env("TCG_DRAGONBALL_BACKFILL_LIMIT") or "35"),
    )
    return parser


def _require_uuid(value: str | None, label: str) -> UUID:
    if not value:
        raise SystemExit(f"{label} is required")
    try:
        return UUID(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be a UUID") from exc


def _sanitise_provider_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "resolved",
        "reason",
        "provider_id",
        "provider_name",
        "provider_set",
        "collector_number",
        "provider_language",
        "finish_key",
        "expansion_id",
        "game_line",
        "candidate_count",
        "expansion_candidate_count",
        "provider_status_code",
        "retryable",
        "image_url",
    )
    return {key: result.get(key) for key in keys if key in result}


async def _batch_context(pool, *, batch_id: UUID, actor_user_id: UUID, request_id: str):
    async with user_connection(pool, actor_user_id, request_id) as connection:
        row = await connection.fetchrow(
            """
            select b.id,b.owner_id,b.status,
                   exists(
                     select 1
                     from tcg.owner_memberships om
                     where om.owner_id=b.owner_id
                       and om.user_id=$2
                       and om.active=true
                       and om.role in ('PLATFORM_ADMIN','OWNER')
                   ) as actor_authorized
            from tcg.import_batches b
            where b.id=$1
            """,
            batch_id,
            actor_user_id,
        )
    if row is None:
        raise RuntimeError("Import batch was not found")
    if not row["actor_authorized"]:
        raise RuntimeError("Actor is not an active founder/admin for the import batch owner")
    if row["status"] != "COMMITTED":
        raise RuntimeError("Dragon Ball backfill requires a COMMITTED import batch")
    return row


async def _probe(
    pool,
    *,
    settings,
    batch_id: UUID,
    actor_user_id: UUID,
    default_language: str,
    request_id: str,
) -> dict[str, Any]:
    if not settings.cardtrader_api_token:
        return {
            "status": "BLOCKED",
            "reason": "TCG_CARDTRADER_API_TOKEN is not configured",
        }

    context = await _batch_context(
        pool,
        batch_id=batch_id,
        actor_user_id=actor_user_id,
        request_id=request_id,
    )
    async with user_connection(pool, actor_user_id, request_id) as connection:
        rows = await connection.fetch(
            """
            with ranked as (
              select
                i.*,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
                p.rarity,p.language as catalogue_language,
                row_number() over(partition by p.game order by p.set_name,p.card_number,p.name,i.id) as rn
              from tcg.inventory_items i
              join tcg.catalogue_products p on p.id=i.catalogue_id
              left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
              where i.import_batch_id=$1
                and i.owner_id=$2
                and i.sale_intent='FOR_SALE'
                and sil.id is null
                and p.game ilike 'Dragon Ball%'
            )
            select *
            from ranked
            where rn=1
            order by game
            """,
            batch_id,
            context["owner_id"],
        )

    client = CardTraderClient(api_token=settings.cardtrader_api_token)
    results: list[dict[str, Any]] = []
    for row in rows:
        probe_row = dict(row)
        if not probe_row.get("language"):
            probe_row["language"] = default_language
        result = await lookup_cardtrader_one(client, probe_row)
        results.append(
            {
                "inventory_id": str(row["id"]),
                "inventory_code": row["inventory_code"],
                "game": row["game"],
                "set_name": row["set_name"],
                "name": row["name"],
                "card_number": row["card_number"],
                "language_used": probe_row.get("language"),
                "provider_result": _sanitise_provider_result(dict(result)),
            }
        )

    return {
        "status": "OK",
        "mode": "probe",
        "batch_id": str(batch_id),
        "owner_id": str(context["owner_id"]),
        "probed": len(results),
        "results": results,
    }


async def _apply(
    pool,
    *,
    batch_id: UUID,
    actor_user_id: UUID,
    default_language: str,
    limit: int,
    request_id: str,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise RuntimeError("limit must be between 1 and 100")

    context = await _batch_context(
        pool,
        batch_id=batch_id,
        actor_user_id=actor_user_id,
        request_id=request_id,
    )

    async with user_connection(pool, actor_user_id, request_id) as connection:
        await _seed_batch(
            connection,
            batch_id=batch_id,
            owner_id=context["owner_id"],
        )
        rows = await connection.fetch(
            """
            select ie.id as enrichment_id,ie.inventory_id
            from tcg.import_enrichment_items ie
            join tcg.inventory_items i on i.id=ie.inventory_id
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            where ie.batch_id=$1
              and ie.owner_id=$2
              and ie.overall_status in ('PENDING','ACTION_REQUIRED')
              and i.sale_intent='FOR_SALE'
              and sil.id is null
              and p.game ilike 'Dragon Ball%'
            order by p.game,p.set_name,p.card_number,p.name,i.id
            limit $3
            """,
            batch_id,
            context["owner_id"],
            limit,
        )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),
        state=SimpleNamespace(request_id=request_id),
    )
    fx_cache: dict[str, Any] = {}
    semaphore = asyncio.Semaphore(min(4, max(1, len(rows))))
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    async def run(row) -> None:
        async with semaphore:
            try:
                result = await _process_one(
                    request,
                    owner_id=context["owner_id"],
                    user_id=actor_user_id,
                    enrichment_id=row["enrichment_id"],
                    inventory_id=row["inventory_id"],
                    default_language=default_language,
                    fx_cache=fx_cache,
                )
                results.append(
                    {
                        "inventory_id": str(row["inventory_id"]),
                        "identity_status": result.get("identity_status"),
                        "media_status": result.get("media_status"),
                        "pricing_status": result.get("pricing_status"),
                        "overall_status": result.get("overall_status"),
                        "metadata": result.get("metadata") or {},
                    }
                )
            except Exception as exc:  # noqa: BLE001 - management command must report per-item failures
                failures.append(
                    {
                        "inventory_id": str(row["inventory_id"]),
                        "error": str(exc)[:1000],
                    }
                )

    await asyncio.gather(*(run(row) for row in rows))

    totals: dict[str, int] = {}
    for result in results:
        key = str(result.get("overall_status") or "UNKNOWN")
        totals[key] = totals.get(key, 0) + 1

    return {
        "status": "OK" if not failures else "PARTIAL",
        "mode": "apply",
        "batch_id": str(batch_id),
        "owner_id": str(context["owner_id"]),
        "default_language": default_language,
        "considered": len(rows),
        "totals": totals,
        "failure_count": len(failures),
        "failures": failures,
        "items": results,
    }


async def async_main() -> int:
    args = build_parser().parse_args()
    batch_id = _require_uuid(args.batch_id, "--batch-id")
    actor_user_id = _require_uuid(args.actor_user_id, "--actor-user-id")
    settings = get_settings()
    pool = await create_pool(settings)
    request_id = f"dragonball-cardtrader-backfill:{uuid4()}"
    try:
        if args.mode == "probe":
            result = await _probe(
                pool,
                settings=settings,
                batch_id=batch_id,
                actor_user_id=actor_user_id,
                default_language=args.default_language,
                request_id=request_id,
            )
        else:
            if not settings.cardtrader_api_token:
                result = {
                    "status": "BLOCKED",
                    "mode": "apply",
                    "reason": "TCG_CARDTRADER_API_TOKEN is not configured",
                }
            else:
                result = await _apply(
                    pool,
                    batch_id=batch_id,
                    actor_user_id=actor_user_id,
                    default_language=args.default_language,
                    limit=args.limit,
                    request_id=request_id,
                )
        print("DRAGONBALL_CARDTRADER_BACKFILL=" + json.dumps(result, default=str), flush=True)
        return 0 if result.get("status") in {"OK","PARTIAL"} else 2
    finally:
        await pool.close()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
