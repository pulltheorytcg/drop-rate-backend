"""Seller-visible shipping money breakdown grounded in Shopify + owned ledger.

Shopify customer checkout shipping ≠ carrier-issued label purchase cost.
Read actual GBP Shopify order money and the physical owner's exact ledger share.
Never infer postage from configured checkout tariffs, cart thresholds or guesses.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


SHIPPING_CHARGES_QUERY = """
query DropRateOwnerShippingChargePreview($orderId: ID!) {
  order(id: $orderId) {
    id cancelledAt fullyPaid displayFinancialStatus
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    totalRefundedShippingSet { shopMoney { amount currencyCode } }
    shippingLines(first: 30) {
      nodes { title }
      pageInfo { hasNextPage }
    }
  }
}
"""


class ShippingCostReviewRequired(ValueError):
    """An unverified or inconsistent order must never display an agreed debit."""


def _money_minor(value: Any, *, label: str) -> int:
    if not isinstance(value, Mapping) or value.get("currencyCode") != "GBP":
        raise ShippingCostReviewRequired(f"{label} must be in GBP")
    try:
        amount = Decimal(str(value.get("amount")))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ShippingCostReviewRequired(f"{label} is invalid") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ShippingCostReviewRequired(f"{label} must be a valid non-negative GBP amount")
    pennies = amount * 100
    if pennies != pennies.to_integral_value():
        raise ShippingCostReviewRequired(f"{label} precision invalid")
    return int(pennies)


def _local_money(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise ShippingCostReviewRequired(f"{label} invalid")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ShippingCostReviewRequired(f"{label} invalid") from exc
    if amount < 0:
        raise ShippingCostReviewRequired(f"{label} invalid")
    return amount


def shipping_charge_breakdown(
    *,
    remote_order: Mapping[str, Any] | None,
    source_reference_gid: str,
    owner_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Return authenticated owner's Shopify checkout and ledger share.

    Seller shipping charge is UNKNOWN until actual carrier label cost is
    reconciled and recorded; a customer paid shipping line is not that cost.
    """
    if not isinstance(remote_order, Mapping) or remote_order.get("id") != source_reference_gid:
        raise ShippingCostReviewRequired("Shopify order identity not verified")
    if (
        remote_order.get("cancelledAt")
        or remote_order.get("displayFinancialStatus") != "PAID"
        or remote_order.get("fullyPaid") is not True
    ):
        raise ShippingCostReviewRequired("Shopify payment requires review")
    shipping_lines = remote_order.get("shippingLines")
    if not isinstance(shipping_lines, Mapping) or (
        shipping_lines.get("pageInfo") or {}
    ).get("hasNextPage"):
        raise ShippingCostReviewRequired("Shopify delivery methods require review")
    rows = shipping_lines.get("nodes")
    if not isinstance(rows, list):
        raise ShippingCostReviewRequired("Shopify delivery methods missing")
    names: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ShippingCostReviewRequired("Shopify delivery method invalid")
        name = str(row.get("title") or "").strip()
        if not name:
            raise ShippingCostReviewRequired("Shopify delivery method missing name")
        names.append(name[:120])
    total = remote_order.get("totalShippingPriceSet") or {}
    refunded = remote_order.get("totalRefundedShippingSet") or {}
    charged = _money_minor(total.get("shopMoney"), label="Customer shipping charged")
    returned = _money_minor(refunded.get("shopMoney"), label="Customer shipping refunded")
    if returned > charged:
        raise ShippingCostReviewRequired("Refunded shipping exceeds recorded checkout amount")
    net_customer_shipping = charged - returned

    owner_share = _local_money(owner_ledger.get("shipping_revenue_minor"), label="Owner shipping credit")
    owner_shipping_refund = _local_money(
        owner_ledger.get("shipping_refund_minor"), label="Owner shipping refund"
    )
    if owner_shipping_refund > owner_share:
        raise ShippingCostReviewRequired("Owner shipping refunds exceed credited shipping")
    net_owner_share = owner_share - owner_shipping_refund

    # One Shopify checkout is shared by any number of physical sellers.
    # Never show an owner credit greater than the entire customer's net
    # delivery payment; that indicates stale/mismatched financial evidence.
    if net_owner_share > net_customer_shipping:
        raise ShippingCostReviewRequired("Owner allocated shipping exceeds checkout")
    reconciled = bool(owner_ledger.get("postage_reconciled"))
    actual_postage: int | None = None
    debit: int | None = None
    credit: int | None = None
    if reconciled:
        actual_postage = _local_money(owner_ledger.get("postage_cost_minor"), label="Verified postage")
        debit = max(0, actual_postage - net_owner_share)
        credit = max(0, net_owner_share - actual_postage)

    return {
        "source": "SHOPIFY_CHECKOUT_AND_OWNER_LEDGER",
        "currency": "GBP",
        "service_names": names,
        "buyer_shipping_charged_minor": charged,
        "buyer_shipping_refunded_minor": returned,
        "buyer_shipping_retained_minor": net_customer_shipping,
        "owner_shipping_credit_minor": owner_share,
        "owner_shipping_refund_minor": owner_shipping_refund,
        "owner_allocated_shipping_minor": net_owner_share,
        "verified_postage_cost_minor": actual_postage,
        "seller_additional_shipping_charge_minor": debit,
        "seller_shipping_credit_after_postage_minor": credit,
        "postage_verification": "VERIFIED" if reconciled else "PENDING_VERIFIED_CARRIER_COST",
        "carrier_quote_minor": None,
        "purchase_allowed": False,
        "explanation": (
            "The customer delivery payment comes from Shopify; your portion "
            "comes from the existing owner ledger. The actual carrier label "
            "cost and final seller charge are pending verification."
        ),
    }
