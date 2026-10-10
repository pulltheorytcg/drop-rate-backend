"""Official Shopify Shipping adapter for Drop Rate's own Shopify Admin API.

The ChatGPT connector uses an older 2026-01 schema; the existing FastAPI
ShopifyAdminClient uses the merchant app's 2026-07+ token. This module never
uses the chat connector or attempts a carrier login.

Read-only Order/FulfillmentOrder preflight is available to authenticated
physical owners. Label purchase and result polling are *internal-only* until a
durable purchase journal, shipper verification, real quote, and confirmed
proceeds policy exist; no public route invokes the purchase mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import re

from .shopify_client import ShopifyAdminClient, ShopifyApiError


ORDER_SHIPPING_QUERY = """
query DropRateShopifyFulfilmentPreflight($orderId: ID!) {
  order(id: $orderId) {
    id name cancelledAt fullyPaid displayFinancialStatus displayFulfillmentStatus
    lineItems(first: 100) {
      nodes { id quantity currentQuantity title sku }
      pageInfo { hasNextPage }
    }
    fulfillmentOrders(first: 40) {
      nodes {
        id status requestStatus orderId
        assignedLocation { location { id } countryCode }
        destination { countryCode }
        lineItems(first: 100) {
          nodes {
            id remainingQuantity totalQuantity requiresShipping
            lineItem { id }
          }
          pageInfo { hasNextPage }
        }
      }
      pageInfo { hasNextPage }
    }
  }
}
"""

# Official Admin API 2026-07+. NEVER invoke without an atomic purchase journal.
PURCHASE_LABEL_MUTATION = """
mutation DropRateShopifyShippingLabelPurchase($shippingLabelPurchase: ShippingLabelPurchaseInput!) {
  shippingLabelPurchase(shippingLabelPurchase: $shippingLabelPurchase) {
    shippingLabelPurchaseResult { id status }
    userErrors { field code message }
  }
}
"""

POLL_LABEL_QUERY = """
query DropRateShopifyShippingLabelStatus($id: ID!) {
  node(id: $id) {
    ... on ShippingLabelPurchaseResult {
      id status done
      errors { code message }
      shippingLabels {
        id cancellable printed
        trackingInfo { number company url }
        shippingDocuments { documentType format url }
      }
    }
  }
}
"""

_ORDER_ID_RE = re.compile(r"^\d{1,24}$")
_FO_ID_RE = re.compile(r"^gid://shopify/FulfillmentOrder/\d{1,24}$")
_RESULT_ID_RE = re.compile(r"^gid://shopify/ShippingLabelPurchaseResult/\d{1,24}$")
_RATE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")


def ensure_label_api_version(version: str) -> None:
    try:
        yy, mm = (int(i) for i in version.split("-"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Shopify Admin API version") from exc
    if (yy, mm) < (2026, 7):
        raise ValueError("Shopify Shipping labels require Admin API 2026-07+")


def canonical_shopify_order_gid(source_reference: str) -> str:
    number = str(source_reference or "").strip()
    if not _ORDER_ID_RE.fullmatch(number):
        raise ValueError("Exact numeric Shopify order reference is required")
    return f"gid://shopify/Order/{number}"


def canonical_shopify_line_gid(line_reference: str) -> str:
    number = str(line_reference or "").strip()
    if not _ORDER_ID_RE.fullmatch(number):
        raise ValueError("Exact numeric Shopify line-item reference is required")
    return f"gid://shopify/LineItem/{number}"


def ensure_shopify_store(client: ShopifyAdminClient, shop_domain: str) -> None:
    if client.shop_domain != str(shop_domain).strip().casefold():
        raise ValueError("Wrong Shopify store connection")


def evaluate_remote_shipping(
    *,
    order: Mapping[str, Any] | None,
    local_allocations: list[Mapping[str, Any]],
    target_line_gid: str,
) -> dict[str, Any]:
    """Fail-closed exact FulfillmentOrder allocation check, no customer PII.

    Only a FulfillmentOrder with *every* remaining item owned by the same
    physical shipper can be considered for a single native Shopify label.
    Mixed-owner or pooled-variant units require a reviewed split first.
    """
    blockers: list[str] = []
    if not isinstance(order, dict):
        return {
            "shopify_connected": True,
            "state": "REVIEW_REQUIRED",
            "blockers": ["SHOPIFY_ORDER_NOT_FOUND"],
            "fulfillment_order_id": None,
            "assigned_location_id": None,
            "destination_country": None,
            "can_buy_label": False,
            "can_confirm_dispatched": False,
        }
    if order.get("cancelledAt"):
        blockers.append("SHOPIFY_ORDER_CANCELLED")
    if order.get("displayFinancialStatus") != "PAID" or not order.get("fullyPaid"):
        blockers.append("SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED")
    if order.get("displayFulfillmentStatus") == "FULFILLED":
        blockers.append("SHOPIFY_ORDER_ALREADY_FULFILLED")
    if order.get("lineItems", {}).get("pageInfo", {}).get("hasNextPage"):
        blockers.append("SHOPIFY_LINE_ITEMS_TRUNCATED")
    fos = order.get("fulfillmentOrders") or {}
    if fos.get("pageInfo", {}).get("hasNextPage"):
        blockers.append("SHOPIFY_FULFILMENT_ORDERS_TRUNCATED")
    own_counts: dict[str, int] = {}
    local_broken = False
    for item in local_allocations:
        try:
            expected_order_gid = canonical_shopify_order_gid(item.get("shopify_order_id"))
            line_gid = canonical_shopify_line_gid(item.get("shopify_line_item_id"))
        except ValueError:
            local_broken = True
            continue
        if expected_order_gid != order.get("id") or item.get("physical_status") != "SOLD":
            local_broken = True
        own_counts[line_gid] = own_counts.get(line_gid, 0) + 1
    if not own_counts or target_line_gid not in own_counts or local_broken:
        blockers.append("LOCAL_OWNER_ALLOCATION_MISMATCH")

    matching: list[dict[str, Any]] = []
    for fo in fos.get("nodes", []):
        lines = (fo.get("lineItems") or {})
        if any(line.get("lineItem", {}).get("id") == target_line_gid for line in lines.get("nodes", [])):
            matching.append(fo)
    if len(matching) != 1:
        blockers.append("FULFILMENT_ORDER_NOT_UNIQUE")
        selected = None
    else:
        selected = matching[0]

    fo_gid = selected.get("id") if selected else None
    loc = selected.get("assignedLocation") if selected else None
    destination = selected.get("destination") if selected else None
    location_id = (loc or {}).get("location", {}) or {}
    location_id = location_id.get("id")
    country = (destination or {}).get("countryCode")

    if selected is not None:
        if selected.get("orderId") != order.get("id"):
            blockers.append("FULFILMENT_ORDER_WRONG_ORDER")
        if selected.get("status") != "OPEN" or selected.get("requestStatus") != "UNSUBMITTED":
            blockers.append("FULFILMENT_ORDER_NOT_OPEN")
        if not isinstance(loc, dict) or not location_id or not country:
            blockers.append("FULFILMENT_SHIPPING_ORIGIN_OR_DESTINATION_MISSING")
        if selected.get("lineItems", {}).get("pageInfo", {}).get("hasNextPage"):
            blockers.append("FULFILMENT_LINES_TRUNCATED")
        remaining = {
            line.get("lineItem", {}).get("id"): line.get("remainingQuantity")
            for line in (selected.get("lineItems") or {}).get("nodes", [])
            if line.get("requiresShipping") is True
        }
        for line in (selected.get("lineItems") or {}).get("nodes", []):
            if line.get("requiresShipping") is not True or not isinstance(line.get("remainingQuantity"), int):
                blockers.append("FULFILMENT_NON_SHIPPING_OR_INVALID_QUANTITY")
                break
            if line.get("remainingQuantity", 0) <= 0:
                blockers.append("FULFILMENT_ALREADY_DISPATCHED_OR_RESERVED")
                break
        # Crucial: FOs are location-scoped, not owner-scoped. NEVER buy
        # one FO-wide label covering another owner's item or unit.
        if remaining != own_counts:
            blockers.append("FULFILMENT_MIXED_OWNER_OR_QUANTITY_SPLIT_REQUIRED")

    if not blockers:
        blockers.append("PHYSICAL_SHIPPER_UNVERIFIED")
    if country and country != "GB":
        blockers.append("INTERNATIONAL_CUSTOMS_AND_INSURANCE_REVIEW")
    # Label charge is not available on the ShippingLabel GraphQL object,
    # therefore do not claim receipt of its actual GBP cost.
    blockers.append("SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING")
    unique = list(dict.fromkeys(blockers))
    return {
        "shopify_connected": True,
        "state": "AWAITING_DISPATCH_SETUP" if unique in (
            ["PHYSICAL_SHIPPER_UNVERIFIED", "SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING"],
        ) else "REVIEW_REQUIRED",
        "blockers": unique,
        "fulfillment_order_id": fo_gid,
        "assigned_location_id": location_id,
        "destination_country": country,
        "can_buy_label": False,
        "can_confirm_dispatched": False,
    }


@dataclass(frozen=True, slots=True)
class ConfirmedShipment:
    """Internal-only input, supplied by future atomic purchase-journal service.

    Cannot be constructed from browser-provided IDs without full owner,
    custody, Shopify, signed fee and idempotency validation.
    """
    fulfillment_order_gid: str
    shipping_datetime: datetime
    total_packed_weight_grams: float
    length_cm: float
    width_cm: float
    height_cm: float
    package_empty_weight_grams: float
    origin_address: dict[str, str]
    carrier_code: str
    service_code: str
    confirmed_charge_minor: int
    purchase_journal_reserved: bool
    physical_custody_verified: bool
    package_type: str = "BOX"


def build_confirmed_label_input(shipment: ConfirmedShipment) -> dict[str, Any]:
    """Construct the *official* 2026-07 Shopify input, with strong safety gates."""
    if not shipment.purchase_journal_reserved or not shipment.physical_custody_verified:
        raise ValueError("Verified owner, origin and durable purchase journal required")
    if not _FO_ID_RE.fullmatch(shipment.fulfillment_order_gid):
        raise ValueError("Invalid exact Shopify fulfillment order")
    dt = shipment.shipping_datetime
    if dt.tzinfo is None or not (datetime.now(timezone.utc) < dt <= datetime.now(timezone.utc) + timedelta(days=30)):
        raise ValueError("Shipping date must be a future timezone-aware time within 30 days")
    if not isinstance(shipment.confirmed_charge_minor, int) or shipment.confirmed_charge_minor <= 0:
        raise ValueError("An actual approved carrier quote is required")
    measures = [
        shipment.total_packed_weight_grams, shipment.length_cm,
        shipment.width_cm, shipment.height_cm, shipment.package_empty_weight_grams,
    ]
    if any(not isinstance(m, (int, float)) or isinstance(m, bool) or not (0 < m <= 100000)
           for m in measures):
        raise ValueError("Measured physical package dimensions and weight are required")
    if shipment.package_empty_weight_grams >= shipment.total_packed_weight_grams:
        raise ValueError("Total packed weight must exceed empty packaging weight")
    if shipment.package_type not in {"BOX", "ENVELOPE", "FLAT_RATE", "SOFT_PACK"}:
        raise ValueError("Invalid verified carrier package type")
    origin = dict(shipment.origin_address)
    for field in ("address1", "city", "zip", "countryCode", "firstName", "lastName"):
        if not isinstance(origin.get(field), str) or not origin[field].strip():
            raise ValueError("Verified seller ship-from address incomplete")
    if not _COUNTRY_CODE_RE.fullmatch(origin.get("countryCode", "")):
        raise ValueError("Invalid seller ship-from country code")
    if not _RATE_CODE_RE.fullmatch(shipment.carrier_code) or not _RATE_CODE_RE.fullmatch(shipment.service_code):
        raise ValueError("Verified carrier and service codes required")
    allow = {
        "address1", "address2", "city", "company", "countryCode",
        "firstName", "lastName", "phone", "provinceCode", "zip",
    }
    return {
        "fulfillmentOrderId": shipment.fulfillment_order_gid,
        "shippingDatetime": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "totalWeight": {"value": float(shipment.total_packed_weight_grams), "unit": "GRAMS"},
        "packageInfo": {"customPackage": {
            "weight": {"value": float(shipment.package_empty_weight_grams), "unit": "GRAMS"},
            "dimensions": {
                "length": float(shipment.length_cm), "width": float(shipment.width_cm),
                "height": float(shipment.height_cm), "unit": "CENTIMETERS",
            },
            "type": shipment.package_type,
        }},
        "originAddress": {k: v.strip() for k, v in origin.items() if k in allow and v},
        "preferredRateSelection": {
            "carrierCode": shipment.carrier_code,
            "serviceCode": shipment.service_code,
        },
        # Dispatch confirmation and customer notification happen separately.
        "notifyCustomer": False,
    }


async def purchase_confirmed_shopify_label(
    client: ShopifyAdminClient, shipment: ConfirmedShipment,
) -> str:
    """For a future tested journalled service ONLY. This CHARGES the store.

    No public endpoint in this release invokes it. On Shopify timeouts a caller
    MUST retain an UNKNOWN journal state and never blindly purchase again.
    """
    ensure_label_api_version(client.api_version)
    variables = {"shippingLabelPurchase": build_confirmed_label_input(shipment)}
    data = await client.graphql(query=PURCHASE_LABEL_MUTATION, variables=variables)
    result = data.get("shippingLabelPurchase") or {}
    errors = result.get("userErrors") or []
    if errors:
        # Error messages may embed addresses: never place them in client errors.
        raise ShopifyApiError("Shopify rejected the shipping label purchase request")
    job = result.get("shippingLabelPurchaseResult") or {}
    gid = job.get("id")
    if not isinstance(gid, str) or not _RESULT_ID_RE.fullmatch(gid):
        raise ShopifyApiError("Shopify did not return a valid label purchase job ID")
    return gid


async def poll_shopify_label_result(
    client: ShopifyAdminClient, purchase_result_gid: str,
) -> dict[str, Any]:
    """Internal label poll; docs URLs never returned directly to buyer browser."""
    ensure_label_api_version(client.api_version)
    if not _RESULT_ID_RE.fullmatch(purchase_result_gid):
        raise ValueError("Invalid label purchase job ID")
    data = await client.graphql(
        query=POLL_LABEL_QUERY, variables={"id": purchase_result_gid},
    )
    result = data.get("node")
    if not isinstance(result, dict):
        raise ShopifyApiError("Shopify could not retrieve the label purchase job")
    status = str(result.get("status") or "")
    if status not in {"PENDING_PURCHASE", "PURCHASED", "PURCHASE_FAILED"}:
        raise ShopifyApiError("Unknown Shopify shipping label purchase status")
    # Do not include shipping documents or buyer data in the default return.
    labels = result.get("shippingLabels") or []
    if status == "PURCHASED" and not labels:
        raise ShopifyApiError("Purchased label missing printable documents")
    return {
        "status": status,
        "job_gid": purchase_result_gid,
        "label_ids": [x["id"] for x in labels if isinstance(x, dict) and x.get("id")],
        "has_label_document": any(
            bool(l.get("shippingDocuments")) for l in labels if isinstance(l, dict)
        ),
        "tracking": [
            {"company": (l.get("trackingInfo") or {}).get("company"),
             "number": (l.get("trackingInfo") or {}).get("number")}
            for l in labels if isinstance(l, dict)
        ] if status == "PURCHASED" else [],
        "error_codes": [
            str(error.get("code") or "UNKNOWN")
            for error in result.get("errors") or []
            if isinstance(error, dict)
        ],
        "verified_cost_minor": None,  # Shopify's label object exposes no cost.
    }
