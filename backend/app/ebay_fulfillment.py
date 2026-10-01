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


def fulfillment_line_items(fulfillment: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
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
    """Identify a fulfillment already representing the exact requested package.

    A later write path must read existing fulfillments first and use this check to
    avoid duplicating shipment updates after retries/timeouts.
    """
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
