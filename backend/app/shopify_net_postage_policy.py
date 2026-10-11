"""Deterministic Drop Rate shipping fee policy for NEW Shopify-paid orders.

Customer checkout shipping and actual carrier charges are platform accounting
facts. Sellers get only one net shipping charge: zero on customer-paid services,
or the verified label cost on eligible FREE UK Tracked 48 orders >= £50.
Never infer carrier cost or eligibility from a merchant's tariff alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


CUSTOMER_PAID = "COMPANY_FUNDED_CUSTOMER_PAID"
FREE_UK_TRACKED48 = "AUTOMATIC_FREE_UK_TRACKED_48"
OTHER_REVIEW = "COMPANY_FUNDED_REVIEW"


@dataclass(frozen=True)
class CheckoutShippingSnapshot:
    customer_shipping_paid_minor: int
    qualifying_merchandise_minor: int
    delivery_service: str
    destination_country: str
    evidence_status: str
    charge_policy: str


def _pennies(value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid Shopify shipping money") from exc
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("Invalid GBP Shopify shipping money")
    return int(amount * 100)


def _line_shipping_paid_minor(line: Mapping[str, Any]) -> int | None:
    price = line.get("discounted_price_set")
    if isinstance(price, Mapping) and isinstance(price.get("shop_money"), Mapping):
        shop_money = price["shop_money"]
        if str(shop_money.get("currency_code") or "GBP").upper() != "GBP":
            raise ValueError("Shopify shipping currency is not GBP")
        return _pennies(shop_money.get("amount"))
    # Legacy REST order webhooks can include discounted_price without a MoneyBag.
    if line.get("discounted_price") is not None:
        return _pennies(line["discounted_price"])
    return None


def classify_shopify_shipping(
    order_payload: Mapping[str, Any],
    *,
    merchandise_minor: int,
) -> CheckoutShippingSnapshot:
    """Classify from actual Shopify delivery after discounts (not rate name).

    Free standard charge may only be automated where we have an exact
    service, GB destination, fully evidenced zero paid shipping, and >=£50
    net merchandise. Every other free or incomplete case is company-funded
    pending review; customers paying anything owe sellers nothing.
    """
    if isinstance(merchandise_minor, bool) or not isinstance(merchandise_minor, int) or merchandise_minor < 0:
        raise ValueError("Invalid merchandise total")
    address = order_payload.get("shipping_address")
    country = str(address.get("country_code") or "").upper() if isinstance(address, Mapping) else ""
    if len(country) != 2 or not country.isalpha():
        country = "ZZ"

    lines = order_payload.get("shipping_lines")
    detailed = isinstance(lines, list) and len(lines) > 0 and all(isinstance(x, Mapping) for x in lines)
    price_minor: int | None = 0 if detailed else None
    names: list[str] = []
    if detailed:
        for line in lines:
            name = str(line.get("title") or "").strip()
            paid = _line_shipping_paid_minor(line)
            if not name or paid is None:
                detailed = False
            names.append(name[:120] or "UNKNOWN")
            if paid is not None:
                price_minor = int(price_minor or 0) + paid
    if not detailed:
        # Record the fallback amount for platform review. NEVER qualify a
        # seller debit when the paid shipping line data are incomplete.
        source = order_payload.get("total_shipping_price_set")
        money = source.get("shop_money") if isinstance(source, Mapping) else None
        if isinstance(money, Mapping):
            if str(money.get("currency_code") or "GBP").upper() != "GBP":
                raise ValueError("Shopify total shipping currency is not GBP")
            price_minor = _pennies(money.get("amount"))
        else:
            price_minor = 0
    paid = int(price_minor or 0)
    service = names[0] if len(names) == 1 else "MULTIPLE_OR_UNKNOWN"

    if detailed and paid > 0:
        policy = CUSTOMER_PAID
    elif (
        detailed
        and paid == 0
        and country == "GB"
        and service == "Royal Mail Tracked 48"
        and merchandise_minor >= 5000
    ):
        policy = FREE_UK_TRACKED48
    else:
        policy = OTHER_REVIEW
    return CheckoutShippingSnapshot(
        customer_shipping_paid_minor=paid,
        qualifying_merchandise_minor=merchandise_minor,
        delivery_service=service,
        destination_country=country,
        evidence_status="VERIFIED_SHIPPING_LINES" if detailed else "NEEDS_REVIEW",
        charge_policy=policy,
    )


def seller_auto_postage_charge(policy: str | None, actual_postage_minor: int) -> int:
    """Called automatically after an authenticated verified carrier receipt.

    No per-seller approval is needed; paid and unknown/other free services
    are company-funded, while eligible free UK Tracked48 deducts actual cost.
    """
    if isinstance(actual_postage_minor, bool) or not isinstance(actual_postage_minor, int) or actual_postage_minor < 0:
        raise ValueError("Invalid verified carrier charge")
    if policy == FREE_UK_TRACKED48:
        return actual_postage_minor
    if policy in {CUSTOMER_PAID, OTHER_REVIEW}:
        return 0
    if policy is None:
        # Historic legacy orders are deliberately handled separately.
        raise ValueError("Legacy shipping policy requires old reconciliation")
    raise ValueError("Unknown Shopify owner postage policy")
