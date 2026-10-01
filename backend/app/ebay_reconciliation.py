from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def offer_listing_id(offer: Mapping[str, Any]) -> str | None:
    listing = offer.get("listing")
    if isinstance(listing, Mapping):
        value = str(listing.get("listingId") or "").strip()
        if value:
            return value
    value = str(offer.get("listingId") or "").strip()
    return value or None


def inventory_quantity(inventory_item: Mapping[str, Any]) -> int | None:
    availability = inventory_item.get("availability")
    if not isinstance(availability, Mapping):
        return None
    shipping = availability.get("shipToLocationAvailability")
    if not isinstance(shipping, Mapping):
        return None
    raw = shipping.get("quantity")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def offer_price_minor(offer: Mapping[str, Any]) -> int | None:
    pricing = offer.get("pricingSummary")
    price = pricing.get("price") if isinstance(pricing, Mapping) else None
    if not isinstance(price, Mapping):
        return None
    if str(price.get("currency") or "").upper() != "GBP":
        return None
    try:
        amount = Decimal(str(price.get("value")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return int((amount * 100).quantize(Decimal("1")))


def reconcile_ebay_link(
    local: Mapping[str, Any],
    *,
    offer: Mapping[str, Any] | None,
    inventory_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare canonical/local link state with eBay read-back state.

    This function is deliberately diagnostic only. It never decides inventory,
    ownership, price, settlement or publication state.
    """
    discrepancies: list[str] = []
    local_state = str(local.get("state") or "").strip().upper()
    physical_status = str(local.get("inventory_status") or "").strip().upper()
    sale_intent = str(local.get("sale_intent") or "").strip().upper()
    local_sku = str(local.get("sku") or "").strip()
    local_listing_id = str(local.get("listing_id") or "").strip() or None
    local_offer_id = str(local.get("offer_id") or "").strip() or None
    local_marketplace = str(local.get("marketplace_id") or "").strip()
    local_price = local.get("listed_price_minor")

    if offer is None:
        discrepancies.append("REMOTE_OFFER_MISSING")
        remote_offer_status = None
        remote_listing_id = None
        remote_offer_id = None
        remote_marketplace = None
        remote_price_minor = None
    else:
        remote_offer_status = str(offer.get("status") or "").strip().upper() or None
        remote_listing_id = offer_listing_id(offer)
        remote_offer_id = str(offer.get("offerId") or "").strip() or None
        remote_marketplace = str(offer.get("marketplaceId") or "").strip() or None
        remote_price_minor = offer_price_minor(offer)

        remote_sku = str(offer.get("sku") or "").strip()
        if remote_sku and local_sku and remote_sku != local_sku:
            discrepancies.append("REMOTE_SKU_MISMATCH")
        if (
            local_marketplace
            and remote_marketplace
            and remote_marketplace != local_marketplace
        ):
            discrepancies.append("REMOTE_MARKETPLACE_MISMATCH")
        if local_offer_id and remote_offer_id and remote_offer_id != local_offer_id:
            discrepancies.append("REMOTE_OFFER_ID_MISMATCH")
        if local_listing_id and remote_listing_id and remote_listing_id != local_listing_id:
            discrepancies.append("REMOTE_LISTING_ID_MISMATCH")
        if (
            local_price is not None
            and remote_price_minor is not None
            and int(local_price) != remote_price_minor
        ):
            discrepancies.append("REMOTE_PRICE_MISMATCH")

    quantity = inventory_quantity(inventory_item or {})

    if local_state == "LIVE":
        if remote_offer_status != "PUBLISHED":
            discrepancies.append("LIVE_LINK_REMOTE_NOT_PUBLISHED")
        if not remote_listing_id:
            discrepancies.append("LIVE_LINK_REMOTE_LISTING_ID_MISSING")
        if quantity is None:
            discrepancies.append("REMOTE_QUANTITY_UNKNOWN")
        elif quantity != 1:
            discrepancies.append("LIVE_LINK_REMOTE_QUANTITY_NOT_ONE")

    if local_state in {"WITHDRAWN", "SOLD"} and remote_offer_status == "PUBLISHED":
        discrepancies.append("NON_LIVE_LINK_REMOTE_STILL_PUBLISHED")

    if physical_status in {"SOLD", "RESERVED"} and remote_offer_status == "PUBLISHED":
        discrepancies.append("CROSS_CHANNEL_OVERSELL_RISK")

    if (
        local_state == "LIVE"
        and (physical_status != "APPROVED" or sale_intent != "FOR_SALE")
    ):
        discrepancies.append("LOCAL_LIVE_LINK_INVENTORY_NOT_SELLABLE")

    if local_state == "ERROR":
        discrepancies.append("LOCAL_LINK_ERROR")

    return {
        "healthy": not discrepancies,
        "discrepancies": list(dict.fromkeys(discrepancies)),
        "remote": {
            "offer_status": remote_offer_status,
            "offer_id": remote_offer_id,
            "listing_id": remote_listing_id,
            "marketplace_id": remote_marketplace,
            "quantity": quantity,
            "price_minor": remote_price_minor,
        },
    }
