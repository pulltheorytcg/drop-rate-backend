from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .market_adapters import stable_source_record_key
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/pricing/imported-benchmark", tags=["pricing"])

_MARKET_KEY_RE = re.compile(r"^Market Price \(As of (\d{4}-\d{2}-\d{2})\)$")
_ALGORITHM_VERSION = "collectr-import-provisional-v1"


def _money_minor(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def extract_imported_benchmark(source_record: object) -> dict[str, Any] | None:
    """Return the best positive benchmark present in an imported Collectr row.

    Explicit positive Price Override wins because it represents the source
    portfolio's deliberate value. Otherwise use the newest positive dated
    Market Price field. Zero/negative/malformed values are never accepted.
    """
    if not isinstance(source_record, dict):
        return None

    override_minor = _money_minor(source_record.get("Price Override"))
    if override_minor is not None:
        return {
            "basis": "PRICE_OVERRIDE",
            "price_minor": override_minor,
            "observed_at": None,
            "source_field": "Price Override",
        }

    candidates: list[tuple[datetime, str, int]] = []
    for key, value in source_record.items():
        match = _MARKET_KEY_RE.match(str(key))
        if not match:
            continue
        price_minor = _money_minor(value)
        if price_minor is None:
            continue
        try:
            observed_at = datetime.strptime(match.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        candidates.append((observed_at, str(key), price_minor))

    if not candidates:
        return None

    observed_at, source_field, price_minor = max(
        candidates,
        key=lambda item: item[0],
    )
    return {
        "basis": "MARKET_PRICE",
        "price_minor": price_minor,
        "observed_at": observed_at,
        "source_field": source_field,
    }


def _pricing_identity_key(item: dict[str, Any]) -> str:
    return stable_source_record_key(
        "COLLECTR_IMPORT_MARKET",
        item["catalogue_id"],
        item.get("condition"),
        item.get("grading_company"),
        item.get("grade"),
        item.get("language"),
        item.get("seal_status"),
        item["benchmark"]["observed_at"].date().isoformat()
        if item["benchmark"]["observed_at"]
        else "NO_DATE",
    )


async def _candidate_rows(connection, owner_id: UUID, limit: int) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        select
            i.id,
            i.catalogue_id,
            i.inventory_code,
            i.status,
            i.version,
            i.condition,
            i.grading_company,
            i.grade,
            i.language,
            i.seal_status,
            i.source_record,
            i.import_batch_id,
            i.source_row,
            i.identity_confirmed,
            p.name,
            p.set_name,
            p.card_number,
            p.variant
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        where i.owner_id=$1
          and i.status in ('DRAFT','INSPECTION','APPROVED')
          and i.store_price_minor is null
        order by i.created_at,i.id
        limit $2
        """,
        owner_id,
        limit,
    )

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        benchmark = extract_imported_benchmark(item.get("source_record"))
        if benchmark is None:
            continue
        item["benchmark"] = benchmark
        candidates.append(item)
        if len(candidates) >= limit:
            break
    return candidates


async def _insert_collectr_observation(connection, item: dict[str, Any]) -> bool:
    benchmark = item["benchmark"]
    if benchmark["basis"] != "MARKET_PRICE":
        return False

    metadata = {
        "access_method": "ORIGINAL_COLLECTR_IMPORT",
        "provider": "COLLECTR",
        "source_field": benchmark["source_field"],
        "import_batch_id": str(item["import_batch_id"]) if item["import_batch_id"] else None,
        "source_row": item["source_row"],
        "provisional": True,
    }
    row = await connection.fetchrow(
        """
        insert into tcg.market_observations(
            catalogue_id,source,source_record_key,observation_type,observed_at,
            price_minor,shipping_minor,currency,price_gbp_minor,shipping_gbp_minor,
            fx_rate_to_gbp,condition,grading_company,grade,language,seal_status,
            source_country,sample_size,evidence_quality,metadata
        ) values(
            $1,'COLLECTR',$2,'MARKET_AGGREGATE',$3,
            $4,null,'GBP',$4,null,
            1.0,$5,$6,$7,$8,$9,
            null,1,0.65,$10::jsonb
        )
        on conflict (source,source_record_key) do nothing
        returning id
        """,
        item["catalogue_id"],
        _pricing_identity_key(item),
        benchmark["observed_at"],
        benchmark["price_minor"],
        item["condition"],
        item["grading_company"],
        item["grade"],
        item["language"],
        item["seal_status"],
        json.dumps(metadata),
    )
    return row is not None


async def _apply_one(
    connection,
    *,
    owner_id: UUID,
    item: dict[str, Any],
) -> dict[str, Any]:
    benchmark = item["benchmark"]
    price_minor = int(benchmark["price_minor"])
    if price_minor <= 0:
        raise HTTPException(status_code=422, detail="Imported benchmark must be positive")

    if benchmark["basis"] == "MARKET_PRICE":
        source_count = 1
        observation_count = 1
        newest_observation_at = benchmark["observed_at"]
        market_value_minor = price_minor
        confidence = 0.35
    else:
        source_count = 0
        observation_count = 0
        newest_observation_at = None
        market_value_minor = price_minor
        confidence = 0.20

    quick_sale_minor = int(
        (Decimal(price_minor) * Decimal("0.92")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    acquisition_minor = int(
        (Decimal(price_minor) * Decimal("0.70")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )

    inserted_observation = await _insert_collectr_observation(connection, item)

    evidence = {
        "provisional": True,
        "source": "COLLECTR_IMPORT",
        "basis": benchmark["basis"],
        "source_field": benchmark["source_field"],
        "observed_at": (
            benchmark["observed_at"].isoformat()
            if benchmark["observed_at"] is not None
            else None
        ),
        "price_minor": price_minor,
        "import_batch_id": str(item["import_batch_id"]) if item["import_batch_id"] else None,
        "source_row": item["source_row"],
        "identity_confirmed": bool(item["identity_confirmed"]),
    }
    block_reasons = [
        "PROVISIONAL_IMPORTED_BENCHMARK",
        "NO_COMPARABLE_SOLD_HISTORY",
    ]
    if not item["identity_confirmed"]:
        block_reasons.append("IDENTITY_UNCONFIRMED")

    snapshot = await connection.fetchrow(
        """
        insert into tcg.pricing_snapshots(
            inventory_id,catalogue_id,owner_id,market_value_minor,
            recommended_retail_minor,quick_sale_minor,target_acquisition_minor,
            confidence,source_count,observation_count,sold_observation_count,
            volatility_pct,newest_observation_at,algorithm_version,evidence,
            auto_publish_eligible,block_reasons
        ) values(
            $1,$2,$3,$4,
            $5,$6,$7,
            $8,$9,$10,0,
            0,$11,$12,$13::jsonb,
            false,$14::jsonb
        )
        returning id
        """,
        item["id"],
        item["catalogue_id"],
        owner_id,
        market_value_minor,
        price_minor,
        quick_sale_minor,
        acquisition_minor,
        confidence,
        source_count,
        observation_count,
        newest_observation_at,
        _ALGORITHM_VERSION,
        json.dumps(evidence),
        json.dumps(block_reasons),
    )

    updated = await connection.fetchrow(
        """
        update tcg.inventory_items
        set
            store_price_minor=$1,
            market_value_minor=$2,
            recommended_retail_minor=$1,
            pricing_updated_at=now(),
            latest_pricing_snapshot_id=$3,
            version=version+1,
            updated_at=now()
        where id=$4
          and owner_id=$5
          and version=$6
          and store_price_minor is null
          and status in ('DRAFT','INSPECTION','APPROVED')
        returning id,inventory_code,store_price_minor,market_value_minor,
                  recommended_retail_minor,latest_pricing_snapshot_id,version
        """,
        price_minor,
        market_value_minor,
        snapshot["id"],
        item["id"],
        owner_id,
        item["version"],
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Inventory changed before provisional Store Price could be applied",
        )

    return {
        "inventory_id": item["id"],
        "inventory_code": item["inventory_code"],
        "name": item["name"],
        "set_name": item["set_name"],
        "card_number": item["card_number"],
        "basis": benchmark["basis"],
        "store_price_minor": price_minor,
        "inserted_market_observation": inserted_observation,
        "snapshot_id": snapshot["id"],
        "version": updated["version"],
    }


@router.get("/status")
async def imported_benchmark_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select source_record,store_price_minor
            from tcg.inventory_items
            where owner_id=$1
              and status in ('DRAFT','INSPECTION','APPROVED')
            """,
            owner["id"],
        )

    eligible = 0
    missing = 0
    for row in rows:
        if row["store_price_minor"] is None:
            missing += 1
            if extract_imported_benchmark(row["source_record"]) is not None:
                eligible += 1

    return {
        "missing_store_price": missing,
        "eligible_imported_benchmark": eligible,
        "still_missing_after_imported_benchmark": missing - eligible,
        "algorithm_version": _ALGORITHM_VERSION,
        "provisional_only": True,
    }


@router.post("/apply-missing")
async def apply_missing_imported_benchmarks(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=100, ge=1, le=100),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        candidates = await _candidate_rows(connection, owner["id"], limit)
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for item in candidates:
            try:
                async with connection.transaction():
                    results.append(
                        await _apply_one(
                            connection,
                            owner_id=owner["id"],
                            item=item,
                        )
                    )
            except HTTPException as exc:
                failures.append(
                    {
                        "inventory_id": str(item["id"]),
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    }
                )

    return jsonable_encoder(
        {
            "updated_count": len(results),
            "failed_count": len(failures),
            "updated": results,
            "failures": failures,
            "provisional_only": True,
        }
    )
