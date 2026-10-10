"""Produce a seller-only, Shopify-sourced packing slip data model.

Shopify Admin doesn't provide the standard merchant packing-slip PDF via
a supported public API. We render a branded, item-specific packing slip
from live Shopify Order.lineItems with no buyer address, payment detail,
or other seller's inventory. The carrier-issued shipping LABEL remains
Shopify Shipping's document and is purchased only after separate approval.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .shopify_shipping_labels import (
    canonical_shopify_line_gid,
    canonical_shopify_order_gid,
)


class PackingSlipNotReady(ValueError):
    """No packing slip should be prepared from a stale or unverified order."""


def build_shopify_owner_packing_slip(
    *,
    remote_order: Mapping[str, Any] | None,
    source_reference: str,
    owner_allocations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compose one packing slip for all physical copies owned by this shipper.

    Caller must fetch owner-scoped rows under Supabase RLS and active membership.
    It must not return addresses or another owner's items even when the Shopify
    order contains multiple owners or the same pooled variant.
    """
    if not isinstance(remote_order, Mapping):
        raise PackingSlipNotReady("Shopify order could not be verified")
    try:
        order_gid = canonical_shopify_order_gid(source_reference)
    except ValueError as exc:
        raise PackingSlipNotReady("Shopify order reference invalid") from exc
    if remote_order.get("id") != order_gid:
        raise PackingSlipNotReady("Shopify order identity mismatch")
    if (
        remote_order.get("cancelledAt")
        or not remote_order.get("fullyPaid")
        or remote_order.get("displayFinancialStatus") != "PAID"
        or remote_order.get("displayFulfillmentStatus") == "FULFILLED"
    ):
        raise PackingSlipNotReady("Shopify order is not eligible for packing")
    remote_items = remote_order.get("lineItems")
    if not isinstance(remote_items, Mapping) or (
        remote_items.get("pageInfo") or {}
    ).get("hasNextPage"):
        raise PackingSlipNotReady("Shopify line items require further verification")
    nodes = remote_items.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise PackingSlipNotReady("Shopify order has no confirmed lines")
    by_gid: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            raise PackingSlipNotReady("Shopify line item invalid")
        if node["id"] in by_gid:
            raise PackingSlipNotReady("Shopify line item duplicated")
        by_gid[node["id"]] = node

    if not owner_allocations:
        raise PackingSlipNotReady("No owner allocations exist")
    expected_counts: Counter[str] = Counter()
    physical_ids: set[str] = set()
    lines: list[dict[str, str]] = []
    for raw in owner_allocations:
        try:
            expected_order = canonical_shopify_order_gid(raw.get("shopify_order_id"))
            line_gid = canonical_shopify_line_gid(raw.get("shopify_line_item_id"))
        except ValueError as exc:
            raise PackingSlipNotReady("Owner allocation link is missing") from exc
        code = str(raw.get("inventory_code") or "").strip()
        physical_id = str(raw.get("order_item_id") or "").strip()
        if not code or not physical_id or physical_id in physical_ids:
            raise PackingSlipNotReady("Physical inventory identity is missing or duplicate")
        if (
            expected_order != order_gid
            or str(raw.get("physical_status") or "") != "SOLD"
            or str(raw.get("order_status") or "") != "PAID"
            or line_gid not in by_gid
        ):
            raise PackingSlipNotReady("Owner allocation or payment state changed")
        physical_ids.add(physical_id)
        expected_counts[line_gid] += 1
        official = by_gid[line_gid]
        title = str(official.get("title") or "").strip()
        if not title:
            raise PackingSlipNotReady("Shopify product title is unavailable")
        lines.append({
            "inventory_id": code,
            "shopify_line_id": line_gid,
            "title": title[:240],
            "sku": str(official.get("sku") or "").strip()[:150],
            "quantity": "1",
        })

    for gid, own_qty in expected_counts.items():
        shopify_remaining = by_gid[gid].get("currentQuantity")
        if not isinstance(shopify_remaining, int) or shopify_remaining < own_qty:
            raise PackingSlipNotReady("Shopify remaining quantity is insufficient")

    # The packing slip may be prepared *before* Shopify FulfillmentOrder split;
    # this does not authorize a carrier-label purchase or dispatch.
    return {
        "source": "SHOPIFY_ADMIN_ORDER",
        "document_type": "OWNER_PACKING_SLIP",
        "order_number": str(remote_order.get("name") or source_reference)[:80],
        "items": sorted(lines, key=lambda item: (item["title"], item["inventory_id"])),
        "item_count": len(lines),
        "ship_to": None,  # Address is intentionally on the purchased carrier label.
        "customer_personal_data_included": False,
        "is_shopify_native_print_template": False,
        "can_purchase_label": False,
        "can_confirm_dispatched": False,
        "notice": (
            "Packing slip generated from this Shopify order for your allocated "
            "physical items. Put inside the parcel; destination is on the "
            "official purchased carrier label."
        ),
    }
