from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any


def build_shipping_fulfillment_payload(
    line_items: Iterable[tuple[str, int]],
    *,
    shipping_carrier_code: str,
    tracking_number: str,
) -> dict[str, Any]:
    """Build a strict tracked-shipment payload without performing a provider write."""
    carrier = str(shipping_carrier_code or "").strip()
    tracking = str(tracking_number or "").strip()
    if not carrier:
        raise ValueError("shipping_carrier_code is required")
    if not tracking:
        raise ValueError("tracking_number is required")
    if len(carrier) > 100:
        raise ValueError("shipping_carrier_code is too long")
    if len(tracking) > 200:
        raise ValueError("tracking_number is too long")
    if re.fullmatch(r"[A-Za-z0-9]+", tracking) is None:
        raise ValueError("tracking_number must contain only ASCII alphanumeric characters")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line_item_id, raw_quantity in line_items:
        line_item_id = str(raw_line_item_id or "").strip()
        if not line_item_id:
            raise ValueError("line_item_id is required")
        if line_item_id in seen:
            raise ValueError("shipping fulfillment contains a duplicate line item")
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError("shipping fulfillment quantity must be an integer") from exc
        if quantity < 1:
            raise ValueError("shipping fulfillment quantity must be positive")
        seen.add(line_item_id)
        normalized.append({"lineItemId": line_item_id, "quantity": quantity})

    if not normalized:
        raise ValueError("shipping fulfillment requires at least one line item")

    return {
        "lineItems": normalized,
        "shippingCarrierCode": carrier,
        "trackingNumber": tracking,
    }


def fulfillment_line_items(
    fulfillment: Mapping[str, Any],
) -> tuple[tuple[str, int], ...]:
    rows = fulfillment.get("lineItems")
    if not isinstance(rows, list):
        return ()
    normalized: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        line_item_id = str(row.get("lineItemId") or "").strip()
        try:
            quantity = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if line_item_id and quantity > 0:
            normalized.append((line_item_id, quantity))
    return tuple(sorted(normalized))


def shipping_fulfillment_matches(
    fulfillment: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
) -> bool:
    """Match the exact remote package for retry-safe read-before-write logic."""
    carrier = str(fulfillment.get("shippingCarrierCode") or "").strip()
    tracking = str(fulfillment.get("trackingNumber") or "").strip()
    expected_carrier = str(payload.get("shippingCarrierCode") or "").strip()
    expected_tracking = str(payload.get("trackingNumber") or "").strip()

    expected_rows = payload.get("lineItems")
    if not isinstance(expected_rows, list):
        return False
    expected = fulfillment_line_items({"lineItems": expected_rows})

    return (
        bool(expected)
        and carrier == expected_carrier
        and tracking == expected_tracking
        and fulfillment_line_items(fulfillment) == expected
    )


def existing_shipping_fulfillment(
    fulfillments: Iterable[Mapping[str, Any]],
    *,
    payload: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    matches = [
        fulfillment
        for fulfillment in fulfillments
        if shipping_fulfillment_matches(fulfillment, payload=payload)
    ]
    if len(matches) > 1:
        raise ValueError("multiple eBay shipping fulfillments match the same package")
    return matches[0] if matches else None


def evaluate_shipping_fulfillment_preview(
    *,
    ebay_order_id: str,
    owner_id: str,
    payload: Mapping[str, Any],
    local_rows: Iterable[Mapping[str, Any]],
    remote_order: Mapping[str, Any],
    remote_fulfillments: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove local/remote order identity before any future fulfillment write."""
    order_id = str(ebay_order_id or "").strip()
    owner = str(owner_id or "").strip()
    blockers: list[str] = []
    local = [dict(row) for row in local_rows]
    remote_packages = [dict(row) for row in remote_fulfillments]

    expected_rows = payload.get("lineItems")
    requested = fulfillment_line_items({"lineItems": expected_rows})
    requested_ids = {line_item_id for line_item_id, _ in requested}
    if not order_id:
        blockers.append("EBAY_ORDER_ID_REQUIRED")
    if not owner:
        blockers.append("OWNER_ID_REQUIRED")
    if not requested:
        blockers.append("PACKAGE_LINE_ITEMS_REQUIRED")
    if not local:
        blockers.append("LOCAL_ORDER_MAPPING_MISSING")

    local_by_line: dict[str, dict[str, Any]] = {}
    internal_order_ids: set[str] = set()
    for row in local:
        line_item_id = str(row.get("ebay_line_item_id") or "").strip()
        if not line_item_id or line_item_id in local_by_line:
            blockers.append("LOCAL_LINE_ITEM_MAPPING_AMBIGUOUS")
            continue
        local_by_line[line_item_id] = row
        internal_order_ids.add(str(row.get("order_id") or ""))

        if str(row.get("ebay_order_id") or "").strip() != order_id:
            blockers.append("LOCAL_EBAY_ORDER_MISMATCH")
        if str(row.get("owner_id") or "").strip() != owner:
            blockers.append("LOCAL_OWNER_MISMATCH")
        if str(row.get("order_item_owner_id") or "").strip() != owner:
            blockers.append("ORDER_ITEM_OWNER_MISMATCH")
        if str(row.get("inventory_owner_id") or "").strip() != owner:
            blockers.append("INVENTORY_OWNER_MISMATCH")
        if str(row.get("inventory_id") or "") != str(
            row.get("order_item_inventory_id") or ""
        ):
            blockers.append("ORDER_ITEM_INVENTORY_MISMATCH")
        if str(row.get("order_source") or "").upper() != "EBAY":
            blockers.append("INTERNAL_ORDER_SOURCE_MISMATCH")
        if str(row.get("source_reference") or "").strip() != order_id:
            blockers.append("INTERNAL_ORDER_REFERENCE_MISMATCH")
        if str(row.get("order_status") or "").upper() != "PAID":
            blockers.append("INTERNAL_ORDER_NOT_PAID")
        if str(row.get("inventory_status") or "").upper() != "SOLD":
            blockers.append("INVENTORY_NOT_SOLD")

    if len(internal_order_ids) > 1:
        blockers.append("MULTIPLE_INTERNAL_ORDERS")

    missing_requested = sorted(requested_ids - set(local_by_line))
    if missing_requested:
        blockers.append("REQUESTED_LINE_NOT_MAPPED")

    remote_id = str(remote_order.get("orderId") or "").strip()
    if remote_id != order_id:
        blockers.append("REMOTE_ORDER_ID_MISMATCH")

    remote_lines = remote_order.get("lineItems")
    remote_by_line: dict[str, int] = {}
    if not isinstance(remote_lines, list) or not remote_lines:
        blockers.append("REMOTE_ORDER_LINES_MISSING")
    else:
        for row in remote_lines:
            if not isinstance(row, Mapping):
                blockers.append("REMOTE_LINE_ITEM_INVALID")
                continue
            line_item_id = str(row.get("lineItemId") or "").strip()
            try:
                quantity = int(row.get("quantity") or 0)
            except (TypeError, ValueError):
                quantity = 0
            if not line_item_id or quantity < 1 or line_item_id in remote_by_line:
                blockers.append("REMOTE_LINE_ITEM_INVALID")
                continue
            remote_by_line[line_item_id] = quantity

    if set(remote_by_line) != set(local_by_line):
        blockers.append("REMOTE_LOCAL_ORDER_LINES_MISMATCH")

    for line_item_id, quantity in requested:
        if remote_by_line.get(line_item_id) != quantity:
            blockers.append("REQUESTED_REMOTE_QUANTITY_MISMATCH")

    exact_existing = existing_shipping_fulfillment(
        remote_packages,
        payload=payload,
    )

    conflicting_package_ids: list[str] = []
    for package in remote_packages:
        if exact_existing is package:
            continue
        package_ids = {line_id for line_id, _ in fulfillment_line_items(package)}
        if requested_ids.intersection(package_ids):
            conflicting_package_ids.append(
                str(package.get("fulfillmentId") or "").strip() or "UNKNOWN"
            )
    if conflicting_package_ids:
        blockers.append("LINE_ALREADY_ASSIGNED_TO_OTHER_FULFILLMENT")

    remote_status = str(remote_order.get("orderFulfillmentStatus") or "").upper()
    if remote_status == "FULFILLED" and exact_existing is None:
        blockers.append("REMOTE_ORDER_ALREADY_FULFILLED")
    elif remote_status not in {"NOT_STARTED", "IN_PROGRESS", "FULFILLED"}:
        blockers.append("REMOTE_FULFILLMENT_STATUS_UNSUPPORTED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    existing_id = (
        str(exact_existing.get("fulfillmentId") or "").strip()
        if exact_existing is not None
        else None
    )
    return {
        "ready_for_create": not unique_blockers and exact_existing is None,
        "idempotent_existing": exact_existing is not None and not unique_blockers,
        "existing_fulfillment_id": existing_id or None,
        "blockers": unique_blockers,
        "requested_line_item_ids": sorted(requested_ids),
        "mapped_line_item_ids": sorted(local_by_line),
        "remote_line_item_ids": sorted(remote_by_line),
        "conflicting_fulfillment_ids": sorted(conflicting_package_ids),
        "remote_order_fulfillment_status": remote_status or None,
    }
