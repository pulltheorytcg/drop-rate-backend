from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder


async def verify_shopify_order_processed(
    connection: Any,
    *,
    order_id: UUID,
    source_reference: str,
    expected_item_count: int,
) -> dict[str, Any]:
    snapshot = await connection.fetchval(
        "select tcg.shopify_order_automation_snapshot($1)",
        order_id,
    )
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=404,
            detail="Committed Shopify order was not found",
        )

    blockers: list[str] = []
    item_count = int(snapshot.get("item_count") or 0)
    if str(snapshot.get("source_reference") or "") != str(source_reference):
        blockers.append("source_reference")
    if str(snapshot.get("status") or "") != "PAID":
        blockers.append("order_status")
    if str(snapshot.get("currency") or "") != "GBP":
        blockers.append("currency")
    if item_count != int(expected_item_count) or item_count < 1:
        blockers.append("item_count")
    if int(snapshot.get("sold_inventory_count") or 0) != item_count:
        blockers.append("sold_inventory")
    if int(snapshot.get("sold_shopify_link_count") or 0) != item_count:
        blockers.append("sold_shopify_links")
    if int(snapshot.get("shopify_order_item_link_count") or 0) != item_count:
        blockers.append("shopify_order_item_links")
    if int(snapshot.get("owner_mismatch_count") or 0) != 0:
        blockers.append("inventory_owner_mismatch")
    if int(snapshot.get("ledger_owner_mismatch_count") or 0) != 0:
        blockers.append("ledger_owner_mismatch")

    if blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Shopify order has not reached a verified committed state",
                "retryable": True,
                "blockers": blockers,
                "order_id": str(order_id),
            },
        )

    return jsonable_encoder({
        "status": "VERIFIED",
        "order_id": order_id,
        "source_reference": snapshot["source_reference"],
        "item_count": item_count,
        "owner_count": int(snapshot.get("owner_count") or 0),
        "ledger_entry_count": int(snapshot.get("ledger_entry_count") or 0),
    })
