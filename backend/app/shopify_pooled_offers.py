from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping, Sequence

from fastapi import HTTPException

from .marketplace_listings import listing_shape


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _stable_offer_sku(listing_fingerprint: str) -> str:
    digest = hashlib.sha256(
        f"drop-rate-shopify-offer:{listing_fingerprint}".encode("utf-8")
    ).hexdigest()[:16].upper()
    return f"DR-{digest}"


def _linked_at_sort_value(value: object) -> tuple[int, str]:
    if isinstance(value, datetime):
        return (0, value.isoformat())
    text = _clean(value)
    return (0, text) if text else (1, "")


def _anchor_sort_key(row: Mapping[str, Any]) -> tuple[object, ...]:
    state = _clean(row.get("sync_state")).upper()
    return (
        0 if state == "PUBLISHED" else 1,
        *_linked_at_sort_value(row.get("linked_at")),
        _clean(row.get("inventory_code")),
        _clean(row.get("inventory_id") or row.get("id")),
    )


def _member_sort_key(row: Mapping[str, Any]) -> tuple[object, ...]:
    priority = row.get("allocation_priority")
    try:
        parsed_priority = int(priority)
    except (TypeError, ValueError):
        parsed_priority = 100
    return (
        parsed_priority,
        *_linked_at_sort_value(row.get("linked_at")),
        _clean(row.get("inventory_code")),
        _clean(row.get("inventory_id") or row.get("id")),
    )


def _shape_input(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("inventory_id") or row.get("id"),
        "catalogue_id": row.get("catalogue_id"),
        "product_type": row.get("product_type"),
        "language": row.get("language"),
        "catalogue_language": row.get("catalogue_language"),
        "condition": row.get("condition"),
        "grading_company": row.get("grading_company"),
        "grade": row.get("grade"),
        "seal_status": row.get("seal_status"),
    }


def _shape_or_block(row: Mapping[str, Any]) -> tuple[dict[str, object] | None, str | None]:
    try:
        return listing_shape(_shape_input(row)), None
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, Mapping):
            message = _clean(detail.get("message"))
        else:
            message = _clean(detail)
        return None, message or "Inventory cannot be assigned to a sellable offer"


def build_shopify_offer_plan(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic, read-only Shopify offer consolidation plan.

    Pooling rules deliberately reuse marketplace_listings.listing_shape:
    - interchangeable raw cards pool by catalogue + language + condition;
    - graded, sealed and force-unique shapes remain unique physical offers.

    This planner never mutates Shopify or Postgres. It is safe to run against
    production-shaped data before an APPLY migration is introduced.
    """

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    preblocked: list[dict[str, Any]] = []

    for row in rows:
        inventory_id = _clean(row.get("inventory_id") or row.get("id"))
        shape, reason = _shape_or_block(row)
        if shape is None:
            preblocked.append(
                {
                    "inventory_id": inventory_id,
                    "inventory_code": _clean(row.get("inventory_code")),
                    "code": "INVALID_OFFER_SHAPE",
                    "detail": reason,
                }
            )
            continue
        grouped[str(shape["fingerprint"])].append({**dict(row), "_shape": shape})

    offers: list[dict[str, Any]] = []
    blocked_offers = 0
    pooled_units = 0
    unique_units = 0
    duplicate_products_to_retire = 0

    for fingerprint, members in sorted(grouped.items()):
        members = sorted(members, key=_member_sort_key)
        shape = members[0]["_shape"]
        pooling_mode = str(shape["pooling_mode"])
        blockers: list[dict[str, str]] = []

        prices = {
            int(row["store_price_minor"])
            for row in members
            if row.get("store_price_minor") is not None
        }
        if any(row.get("store_price_minor") is None for row in members):
            blockers.append(
                {
                    "code": "MISSING_PRICE",
                    "detail": "Every inventory member needs a store price before consolidation",
                }
            )
        if pooling_mode == "POOLED" and len(prices) > 1:
            blockers.append(
                {
                    "code": "MIXED_MEMBER_PRICES",
                    "detail": (
                        "Interchangeable copies currently have different store prices; "
                        "an explicit shared offer price is required"
                    ),
                }
            )

        domains = {_clean(row.get("shop_domain")) for row in members if _clean(row.get("shop_domain"))}
        if len(domains) > 1:
            blockers.append(
                {
                    "code": "MIXED_SHOP_DOMAINS",
                    "detail": "One offer cannot span multiple Shopify shops",
                }
            )

        locations = {
            _clean(row.get("shopify_location_gid"))
            for row in members
            if _clean(row.get("shopify_location_gid"))
        }
        if len(locations) > 1:
            blockers.append(
                {
                    "code": "MIXED_SHOPIFY_LOCATIONS",
                    "detail": "One pooled offer must use one Shopify inventory location",
                }
            )

        if pooling_mode == "UNIQUE" and len(members) != 1:
            blockers.append(
                {
                    "code": "UNIQUE_OFFER_COLLISION",
                    "detail": "A unique physical offer unexpectedly contains multiple inventory items",
                }
            )

        anchor = min(members, key=_anchor_sort_key)
        anchor_product_gid = _clean(anchor.get("shopify_product_gid"))
        anchor_variant_gid = _clean(anchor.get("shopify_variant_gid"))
        anchor_inventory_item_gid = _clean(anchor.get("shopify_inventory_item_gid"))
        if not anchor_product_gid or not anchor_variant_gid or not anchor_inventory_item_gid:
            blockers.append(
                {
                    "code": "INCOMPLETE_SHOPIFY_LINK",
                    "detail": "The deterministic anchor is missing Shopify product/variant/inventory IDs",
                }
            )

        product_gids = {
            _clean(row.get("shopify_product_gid"))
            for row in members
            if _clean(row.get("shopify_product_gid"))
        }
        retired = sorted(gid for gid in product_gids if gid != anchor_product_gid)

        allocation_rows: list[dict[str, Any]] = []
        for index, row in enumerate(members, start=1):
            allocation_rows.append(
                {
                    "inventory_id": _clean(row.get("inventory_id") or row.get("id")),
                    "inventory_code": _clean(row.get("inventory_code")),
                    "owner_id": _clean(row.get("owner_id")),
                    "allocation_priority": index,
                    "current_product_gid": _clean(row.get("shopify_product_gid")),
                    "current_variant_gid": _clean(row.get("shopify_variant_gid")),
                    "sync_state": _clean(row.get("sync_state")).upper(),
                }
            )

        offer = {
            "listing_fingerprint": fingerprint,
            "listing_key": f"offer:{fingerprint}",
            "sku": _stable_offer_sku(fingerprint),
            "pooling_mode": pooling_mode,
            "catalogue_id": _clean(members[0].get("catalogue_id")),
            "language": shape.get("language"),
            "condition": shape.get("condition"),
            "grading_company": shape.get("grading_company"),
            "grade": shape.get("grade"),
            "seal_status": shape.get("seal_status"),
            "store_price_minor": next(iter(prices)) if len(prices) == 1 else None,
            "quantity": len(members),
            "target": {
                "shopify_product_gid": anchor_product_gid,
                "shopify_variant_gid": anchor_variant_gid,
                "shopify_inventory_item_gid": anchor_inventory_item_gid,
                "shopify_location_gid": _clean(anchor.get("shopify_location_gid")),
            },
            "retire_product_gids": retired,
            "members": allocation_rows,
            "blockers": blockers,
            "ready": not blockers,
        }
        offers.append(offer)

        if blockers:
            blocked_offers += 1
        else:
            duplicate_products_to_retire += len(retired)
            if pooling_mode == "POOLED":
                pooled_units += len(members)
            else:
                unique_units += len(members)

    ready_offers = len(offers) - blocked_offers
    pooled_offers = sum(1 for offer in offers if offer["pooling_mode"] == "POOLED")
    unique_offers = sum(1 for offer in offers if offer["pooling_mode"] == "UNIQUE")

    return {
        "mode": "DRY_RUN",
        "input_units": len(rows),
        "planned_units": sum(len(offer["members"]) for offer in offers),
        "preblocked_units": len(preblocked),
        "offer_count": len(offers),
        "ready_offer_count": ready_offers,
        "blocked_offer_count": blocked_offers,
        "pooled_offer_count": pooled_offers,
        "unique_offer_count": unique_offers,
        "ready_pooled_units": pooled_units,
        "ready_unique_units": unique_units,
        "duplicate_products_to_retire": duplicate_products_to_retire,
        "preblocked": preblocked,
        "offers": offers,
    }
