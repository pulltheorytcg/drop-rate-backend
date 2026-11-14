"""Read-only provenance audit of Cardmarket's official public bulk exports.

This inspects source-side ID alignment only. It cannot establish a Drop Rate
printing crosswalk, sale evidence, licence to display, or physical Market Value.
Reuse the guarded Cardmarket parser rather than building a second price engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .cardmarket_public_pilot import PilotError, _id, _rows

GAME_IDS = {
    "magic": 1,
    "pokemon": 6,
    "yugioh": 3,
    "one_piece": 18,
    "lorcana": 19,
}
PRODUCT_KINDS = ("singles", "nonsingles")
SCHEMA = "drop-rate-cardmarket-bulk-source-audit-v1"


def audit_bulk_exports(*, game: str, product_kind: str, products_export: dict,
                       price_export: dict, now: datetime) -> dict[str, Any]:
    """Count Cardmarket source IDs, without returning prices or matching cards.

    A Cardmarket idProduct join is NOT a verified canonical printing match.
    Unsupported, stale or conflicting provider files fail closed.
    """
    if game not in GAME_IDS or product_kind not in PRODUCT_KINDS:
        raise PilotError("Unsupported Cardmarket game or product kind")
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise PilotError("Audit clock must be timezone aware")
    now = now.astimezone(timezone.utc)
    for payload in (products_export, price_export):
        if not isinstance(payload, dict) or (
            "version" in payload and (type(payload["version"]) is not int or payload["version"] != 1)
        ):
            raise PilotError("Unsupported Cardmarket export schema version")
    products, product_time = _rows(products_export, "products", now=now)
    guides, price_time = _rows(price_export, "priceGuides", now=now)
    if abs(product_time - price_time) > timedelta(days=2):
        raise PilotError("Cardmarket source exports have inconsistent timestamps")

    product_ids: dict[int, int | None] = {}
    for item in products:
        source_id = _id(item.get("idProduct"))
        if source_id is None or source_id in product_ids:
            raise PilotError("Invalid or duplicate Cardmarket product ID")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise PilotError("Cardmarket source product has no name")
        if not isinstance(item.get("categoryName"), str) or not item["categoryName"].strip():
            raise PilotError("Cardmarket source product has no category")
        category_id = _id(item.get("idCategory"))
        if item.get("idCategory") is not None and category_id is None:
            raise PilotError("Invalid Cardmarket product category ID")
        product_ids[source_id] = category_id

    guide_ids: set[int] = set()
    overlap = 0
    for item in guides:
        source_id = _id(item.get("idProduct"))
        if source_id is None or source_id in guide_ids:
            raise PilotError("Invalid or duplicate Cardmarket guide ID")
        guide_ids.add(source_id)
        if source_id in product_ids:
            price_category = _id(item.get("idCategory"))
            if item.get("idCategory") is not None and price_category is None:
                raise PilotError("Invalid Cardmarket price category ID")
            product_category = product_ids[source_id]
            if price_category is not None and product_category is not None and (
                price_category != product_category
            ):
                raise PilotError("Conflicting Cardmarket product/price category")
            overlap += 1
    # Deliberately no guide price, card ID or unlicensed price redisplay.
    # Guide row intersection is not proof that an amount exists, and cannot
    # be counted as pricing coverage on Drop Rate.
    return {
        "schema": SCHEMA,
        "status": "REVIEW_ONLY_SOURCE_ALIGNMENT",
        "game": game,
        "cardmarket_game_id": GAME_IDS[game],
        "product_kind": product_kind,
        "product_export_at": product_time.isoformat(),
        "guide_export_at": price_time.isoformat(),
        "catalogue_product_count": len(product_ids),
        "price_guide_row_count": len(guide_ids),
        "source_id_intersection_count": overlap,
        "catalogue_without_guide_row_count": len(product_ids) - overlap,
        "price_guide_rows_outside_selected_catalogue": len(guide_ids) - overlap,
        "canonical_printings_verified": 0,
        "verified_item_level_sales": 0,
        "physical_market_values_added": 0,
        "store_prices_changed": 0,
        "database_writes": 0,
        "shopify_writes": 0,
        "publishable": False,
        "commercial_display_permission": "NOT_VERIFIED",
        "source_id_join_is_not_printing_match": True,
    }
