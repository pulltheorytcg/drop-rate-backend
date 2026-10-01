from __future__ import annotations

import json
import re
from statistics import median
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from .db import user_connection
from .ebay_sold_pricing import TrawlApiError, TrawlEbaySoldClient, _money_minor, _sold_at
from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .ownership import current_owner as _owner
from .pricing import _recalculate_one
from .settings import get_settings


_MULTI_TERMS = (
    "booster box",
    "display box",
    "sealed box",
    "case of",
    "booster case",
    "full case",
    "box of",
    "lot of",
    "bundle",
    "multipack",
    "multi pack",
    "24 packs",
    "24 pack",
    "x24",
    "x 24",
    "12 packs",
    "12 pack",
    "x12",
    "x 12",
)
_PACK_TERMS = ("booster pack", "single pack", "1 pack", "one pack")
_JAPANESE_TERMS = ("japanese", "japan", "jpn", " jp ")
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _norm(value: object) -> str:
    clean = _TOKEN_RE.sub(" ", str(value or "").casefold())
    return f" {' '.join(clean.split())} "


def _contains(text: str, term: str) -> bool:
    return f" {_TOKEN_RE.sub(' ', term.casefold()).strip()} " in text


def _sealed_query(target: dict[str, Any]) -> str:
    parts = [
        "One Piece",
        target["set_code"],
        "Japanese" if target["language"].casefold() == "japanese" else target["language"],
        "booster pack",
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _sealed_comp_matches(row: dict[str, Any], target: dict[str, Any]) -> bool:
    title_raw = row.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        return False
    title = _norm(title_raw)

    set_code = str(target["set_code"] or "").strip()
    if not set_code or not _contains(title, set_code):
        return False

    if target["language"].strip().casefold() == "japanese":
        if not any(_contains(title, term) for term in _JAPANESE_TERMS):
            return False

    sealed_type = str(target["sealed_product_type"] or "").upper()
    if sealed_type != "BOOSTER_PACK":
        return False
    if not any(_contains(title, term) for term in _PACK_TERMS):
        return False
    if any(_contains(title, term) for term in _MULTI_TERMS):
        return False

    return True


def _select_five_sold(payload: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
    if str(payload.get("currency") or "").strip().upper() != "GBP":
        raise ValueError("Sold-data response is not GBP / eBay UK")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Sold-data response is missing results")

    accepted: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not _sealed_comp_matches(row, target):
            continue
        item_id = str(row.get("item_id") or "").strip()
        sold_at = _sold_at(row.get("date_sold"))
        price_minor = _money_minor(row.get("sale_price"))
        if not item_id or sold_at is None or price_minor is None or price_minor <= 0:
            continue
        shipping_minor = _money_minor(row.get("shipping_price"))
        accepted[item_id] = {
            "item_id": item_id,
            "title": str(row.get("title") or "").strip(),
            "sold_at": sold_at,
            "price_minor": price_minor,
            "shipping_minor": shipping_minor,
            "url": str(row.get("item_link") or "").strip() or None,
        }
    return sorted(
        accepted.values(),
        key=lambda item: item["sold_at"],
        reverse=True,
    )[:5]


async def _snapshot(
    pool,
    *,
    user_id: UUID,
    request_id: str,
    owner_id: UUID,
    inventory_code: str,
) -> dict[str, Any]:
    async with user_connection(pool, user_id, request_id) as connection:
        owner = await _owner(connection)
        if owner["id"] != owner_id:
            raise HTTPException(status_code=409, detail="Owner context changed")
        row = await connection.fetchrow(
            """
            select
                i.id,i.inventory_code,i.catalogue_id,i.version,i.status,
                i.identity_confirmed,i.language,i.seal_status,
                p.product_type,p.game,p.name,p.set_name,p.language as catalogue_language,
                pr.collectible_type,pr.identity_status as profile_identity_status,
                pr.set_code,
                sd.identity_status as sealed_identity_status,
                sealed_type.value_code as sealed_product_type
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
            join tcg.sealed_product_details sd on sd.catalogue_id=p.id
            left join lateral (
                select a.value_code
                from tcg.catalogue_taxonomy_assignments a
                where a.catalogue_id=p.id
                  and a.scope_kind='SEALED'
                  and a.dimension_code='SEALED_TYPE'
                order by
                  case when a.verification_status='VERIFIED' then 0 else 1 end,
                  a.created_at desc
                limit 1
            ) sealed_type on true
            where i.owner_id=$1 and i.inventory_code=$2
            """,
            owner_id,
            inventory_code,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        data = dict(row)

    if data["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
        raise HTTPException(status_code=409, detail="Only active inventory can be repriced")
    if data["product_type"] not in {"SEALED", "COLLECTION"}:
        raise HTTPException(status_code=422, detail="Sealed pricing supports sealed inventory only")
    if not data["identity_confirmed"]:
        raise HTTPException(status_code=409, detail="Sealed identity must be confirmed before pricing")
    if (
        data["collectible_type"] != "SEALED"
        or data["profile_identity_status"] != "VERIFIED"
        or data["sealed_identity_status"] != "VERIFIED"
    ):
        raise HTTPException(status_code=409, detail="Canonical sealed identity is not verified")
    if data["seal_status"] != "SEALED":
        raise HTTPException(status_code=422, detail="Physical sealed state is required for sealed pricing")
    if data["sealed_product_type"] != "BOOSTER_PACK":
        raise HTTPException(status_code=422, detail="This pricing path currently supports booster packs only")
    language = str(data["language"] or data["catalogue_language"] or "").strip()
    if not language:
        raise HTTPException(status_code=422, detail="Physical language is required for sealed pricing")
    data["language"] = language
    if not str(data["set_code"] or "").strip():
        raise HTTPException(status_code=422, detail="Exact sealed set code is required for pricing")
    return data


async def _fetch_uk_sold(target: dict[str, Any]) -> dict[str, Any]:
    api_key = get_settings().trawl_api_key
    if not api_key:
        raise HTTPException(
            status_code=409,
            detail="UK eBay sold-data access is not configured",
        )
    client = TrawlEbaySoldClient(api_key=api_key, timeout_seconds=20.0)
    query = _sealed_query(target)
    try:
        payload = await client.sold(query=query, max_pages=1)
    except TrawlApiError as exc:
        raise HTTPException(
            status_code=429 if exc.status_code == 429 else 502,
            detail=exc.detail,
        ) from exc

    comps = _select_five_sold(payload, target)
    if len(comps) < 5:
        return {
            "status": "BLOCKED",
            "detail": "Fewer than five exact comparable UK eBay sold booster packs were found",
            "query": query,
            "comparable_count": len(comps),
            "comps": comps,
        }
    return {
        "status": "READY",
        "detail": None,
        "query": query,
        "comparable_count": 5,
        "comps": comps,
        "median_minor": int(median([item["price_minor"] for item in comps])),
    }


async def refresh_verified_sealed_ebay_market(
    pool,
    *,
    user_id: UUID,
    request_id: str,
    owner_id: UUID,
    inventory_code: str,
) -> dict[str, Any]:
    """Refresh one verified sealed booster using five exact eBay UK sold comps.

    Provider HTTP is performed between two short user-scoped DB transactions.
    """

    target = await _snapshot(
        pool,
        user_id=user_id,
        request_id=request_id,
        owner_id=owner_id,
        inventory_code=inventory_code,
    )

    result = await _fetch_uk_sold(target)
    if result["status"] != "READY":
        return {
            **result,
            "inventory_id": target["id"],
            "inventory_code": target["inventory_code"],
            "market_value_minor": None,
        }

    async with user_connection(pool, user_id, request_id) as connection:
        owner = await _owner(connection)
        if owner["id"] != owner_id:
            raise HTTPException(status_code=409, detail="Owner context changed during pricing")
        current = await connection.fetchrow(
            """
            select
                i.version,i.status,i.catalogue_id,i.identity_confirmed,
                i.language,i.seal_status,
                pr.identity_status as profile_identity_status,pr.set_code,
                sd.identity_status as sealed_identity_status,
                sealed_type.value_code as sealed_product_type
            from tcg.inventory_items i
            join tcg.catalogue_product_profiles pr on pr.catalogue_id=i.catalogue_id
            join tcg.sealed_product_details sd on sd.catalogue_id=i.catalogue_id
            left join lateral (
                select a.value_code
                from tcg.catalogue_taxonomy_assignments a
                where a.catalogue_id=i.catalogue_id
                  and a.scope_kind='SEALED'
                  and a.dimension_code='SEALED_TYPE'
                order by
                  case when a.verification_status='VERIFIED' then 0 else 1 end,
                  a.created_at desc
                limit 1
            ) sealed_type on true
            where i.id=$1 and i.owner_id=$2
            for update of i
            """,
            target["id"],
            owner_id,
        )
        if current is None:
            raise HTTPException(status_code=409, detail="Inventory changed during sold-data lookup")
        fields = (
            "version","status","catalogue_id","identity_confirmed",
            "language","seal_status","profile_identity_status","set_code",
            "sealed_identity_status","sealed_product_type",
        )
        if any(current[field] != target[field] for field in fields):
            raise HTTPException(status_code=409, detail="Sealed inventory changed during sold-data lookup")

        inserted = 0
        for comp in result["comps"]:
            key = stable_source_record_key(
                "EBAY",
                "TRAWL",
                "SEALED",
                target["catalogue_id"],
                comp["item_id"],
                comp["sold_at"].isoformat(),
            )
            observation = NormalizedMarketObservation(
                source="EBAY",
                source_record_key=key,
                observation_type="SOLD",
                observed_at=comp["sold_at"],
                price_minor=comp["price_minor"],
                shipping_minor=comp["shipping_minor"],
                currency="GBP",
                price_gbp_minor=comp["price_minor"],
                shipping_gbp_minor=comp["shipping_minor"],
                fx_rate_to_gbp=1.0,
                catalogue_id=str(target["catalogue_id"]),
                condition=None,
                language=target["language"],
                seal_status="SEALED",
                source_country="GB",
                sample_size=1,
                evidence_quality=1.0,
                metadata={
                    "access_method": "TRAWL_API",
                    "market_source": "EBAY",
                    "marketplace": "EBAY_GB",
                    "provider_item_id": comp["item_id"],
                    "url": comp["url"],
                    "title": comp["title"],
                    "query": result["query"],
                    "sealed_product_type": target["sealed_product_type"],
                    "set_code": target["set_code"],
                    "selection_rule": "FIVE_NEWEST_EXACT_SEALED_PACK_SALES",
                    "sale_price_excludes_shipping": True,
                },
            ).validate()
            row = await connection.fetchrow(
                """
                insert into tcg.market_observations(
                    catalogue_id,source,source_record_key,observation_type,observed_at,
                    price_minor,shipping_minor,currency,price_gbp_minor,shipping_gbp_minor,
                    fx_rate_to_gbp,condition,grading_company,grade,language,seal_status,
                    source_country,sample_size,evidence_quality,metadata
                ) values(
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20::jsonb
                )
                on conflict(source,source_record_key) do nothing
                returning id
                """,
                UUID(observation.catalogue_id),
                observation.source,
                observation.source_record_key,
                observation.observation_type,
                observation.observed_at,
                observation.price_minor,
                observation.shipping_minor,
                observation.currency,
                observation.price_gbp_minor,
                observation.shipping_gbp_minor,
                observation.fx_rate_to_gbp,
                observation.condition,
                observation.grading_company,
                observation.grade,
                observation.language,
                observation.seal_status,
                observation.source_country,
                observation.sample_size,
                observation.evidence_quality,
                json.dumps(observation.metadata),
            )
            if row is not None:
                inserted += 1

        valuation = await _recalculate_one(connection, owner_id, target["id"])

    return {
        "status": "CALCULATED",
        "detail": None,
        "inventory_id": target["id"],
        "inventory_code": target["inventory_code"],
        "comparable_count": 5,
        "inserted_observations": inserted,
        "median_sold_minor": result["median_minor"],
        "valuation": valuation,
    }
