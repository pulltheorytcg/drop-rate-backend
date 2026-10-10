"""Shipping revenue versus actual postage cost: seller settlement contracts.

Shopify owns customer-facing delivery charges and delivery eligibility. These
tests safeguard the existing deterministic FastAPI finance calculations; they
do not purchase labels, create shipments, or change production ledgers.
"""
from app.finance import allocate_minor, _settlement_amounts, _settlement_reconciliation_state


def owner_shipping_settlement(*, merchandise_minor, shipping_revenue_minor, actual_postage_minor):
    return _settlement_amounts(
        item_revenue_minor=merchandise_minor,
        shipping_revenue_minor=shipping_revenue_minor,
        item_refunds_minor=0,
        shipping_refunds_minor=0,
        platform_fees_minor=0,
        payment_fees_minor=0,
        shipping_cost_minor=actual_postage_minor,
        fulfilment_material_cost_minor=0,
        commission_minor=0,
        adjustments_minor=0,
        effective_cogs_minor=None,
    )


def test_free_standard_shipping_deducts_real_postage_once_from_seller():
    # At Shopify checkout, free postage creates ZERO buyer shipping revenue.
    # The seller only bears the ACTUAL carrier label amount after a real
    # purchased-label transaction is verified.
    actual_label_cost_minor = 349
    result = owner_shipping_settlement(
        merchandise_minor=1200, shipping_revenue_minor=0,
        actual_postage_minor=actual_label_cost_minor,
    )
    assert result["gross_proceeds_minor"] == 1200
    assert result["external_deductions_minor"] == actual_label_cost_minor
    assert result["net_owner_proceeds_minor"] == 851


def test_paid_delivery_offsets_actual_postage_without_double_charge():
    # £4.99 is the current buyer-facing UK Standard rate. It is NOT the
    # necessarily equal Royal Mail / Shopify Shipping label purchase price.
    result = owner_shipping_settlement(
        merchandise_minor=950, shipping_revenue_minor=499,
        actual_postage_minor=349,
    )
    assert result["gross_proceeds_minor"] == 1449
    assert result["external_deductions_minor"] == 349
    assert result["net_owner_proceeds_minor"] == 1100
    assert result["net_owner_proceeds_minor"] - 950 == 499 - 349


def test_multiowner_one_parcel_free_delivery_spreads_only_real_label_cost():
    # The same carrier charge must never be deducted in full from two owners.
    shipping_cost_minor = 381
    shares = allocate_minor(shipping_cost_minor, [700, 300])
    assert len(shares) == 2 and sum(shares) == shipping_cost_minor
    a = owner_shipping_settlement(
        merchandise_minor=700, shipping_revenue_minor=0,
        actual_postage_minor=shares[0],
    )
    b = owner_shipping_settlement(
        merchandise_minor=300, shipping_revenue_minor=0,
        actual_postage_minor=shares[1],
    )
    assert a["net_owner_proceeds_minor"] + b["net_owner_proceeds_minor"] == 1000 - 381
    assert a["external_deductions_minor"] + b["external_deductions_minor"] == 381


def test_two_separate_free_shipments_charge_each_responsible_seller_once():
    # When sellers each physically send one parcel, one order can have
    # TWO different labels. Each receives its own real invoice/cost entry.
    a = owner_shipping_settlement(
        merchandise_minor=1000, shipping_revenue_minor=0,
        actual_postage_minor=283,
    )
    b = owner_shipping_settlement(
        merchandise_minor=1200, shipping_revenue_minor=0,
        actual_postage_minor=359,
    )
    assert a["net_owner_proceeds_minor"] == 717
    assert b["net_owner_proceeds_minor"] == 841
    assert 2200 - a["net_owner_proceeds_minor"] - b["net_owner_proceeds_minor"] == 642


def test_customer_paid_shipping_revenue_is_allocated_once_per_shopify_order():
    # Shopify's paid-order engine already allocates the ONE paid shipping
    # charge by net line item weights; it must never replicate £4.99 per owner.
    paid_shipping_minor = 499
    shares = allocate_minor(paid_shipping_minor, [900, 600])
    assert sum(shares) == paid_shipping_minor
    a = owner_shipping_settlement(
        merchandise_minor=900, shipping_revenue_minor=shares[0],
        actual_postage_minor=220,
    )
    b = owner_shipping_settlement(
        merchandise_minor=600, shipping_revenue_minor=shares[1],
        actual_postage_minor=279,
    )
    assert a["net_owner_proceeds_minor"] + b["net_owner_proceeds_minor"] == 1500
    assert shares != [499, 499]


def test_unknown_label_cost_must_keep_settlement_unverified():
    status, blockers = _settlement_reconciliation_state(
        source="SHOPIFY", fees_reconciled=True, shipping_cost_reconciled=False,
    )
    assert "POSTAGE" in status
    assert any("postage" in item.lower() for item in blockers)
