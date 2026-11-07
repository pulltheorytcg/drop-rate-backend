"""New Shopify platform shipping funding policy: no owner postage on paid delivery."""
from pathlib import Path

import pytest

from app.shopify_net_postage_policy import (
    CUSTOMER_PAID, FREE_UK_TRACKED48, OTHER_REVIEW,
    classify_shopify_shipping, seller_auto_postage_charge,
)

ROOT=Path(__file__).resolve().parents[1]
POLICY_SQL=(ROOT/"database/migrations/20261011005033_shopify_net_shipping_accounts.sql").read_text()
PIPELINE=(ROOT/"backend/app/shopify_pipeline.py").read_text()
FINANCE=(ROOT/"backend/app/finance.py").read_text()
OWNER=(ROOT/"backend/app/owner_fulfillment.py").read_text()
WIZARD=(ROOT/"backend/app/static/owner-fulfill-wizard.js").read_text()


def sample_shipping(*,service="Royal Mail Tracked 48",paid="3.95",country="GB",
                    detailed=True,original=None):
    line={"title":service,"discounted_price_set":{"shop_money":{
        "amount":paid,"currency_code":"GBP"}}}
    return {
        "shipping_address":{"country_code":country},
        "shipping_lines":[line] if detailed else [],
        "total_shipping_price_set":{"shop_money":{
            "amount":original or paid,"currency_code":"GBP"}},
        "currency":"GBP",
    }


def test_paid_uk_standard_customer_funded_no_owner_postage():
    result=classify_shopify_shipping(sample_shipping(),merchandise_minor=2500)
    assert result.customer_shipping_paid_minor==395
    assert result.charge_policy==CUSTOMER_PAID
    assert seller_auto_postage_charge(result.charge_policy,295)==0
    assert result.evidence_status=="VERIFIED_SHIPPING_LINES"


def test_free_uk_tracked48_at_exact_50_autocharges_actual_invoice_not_estimate():
    snapshot=classify_shopify_shipping(
        sample_shipping(paid="0.00",original="3.95"),merchandise_minor=5000,
    )
    assert snapshot.customer_shipping_paid_minor==0
    assert snapshot.charge_policy==FREE_UK_TRACKED48
    assert seller_auto_postage_charge(snapshot.charge_policy,377)==377
    assert seller_auto_postage_charge(snapshot.charge_policy,0)==0


def test_free_uk_below_50_promo_is_not_seller_debit():
    snap=classify_shopify_shipping(sample_shipping(paid="0.00"),merchandise_minor=4999)
    assert snap.charge_policy==OTHER_REVIEW
    assert seller_auto_postage_charge(snap.charge_policy,699)==0


def test_paid_tracked24_over_50_still_no_seller_postage():
    snap=classify_shopify_shipping(
        sample_shipping(service="Royal Mail Tracked 24",paid="4.95"),
        merchandise_minor=22000,
    )
    assert snap.customer_shipping_paid_minor==495
    assert snap.charge_policy==CUSTOMER_PAID
    assert seller_auto_postage_charge(snap.charge_policy,577)==0


@pytest.mark.parametrize("service,amount,country",[
    ("Royal Mail International Tracked","14.99","FR"),
    ("Royal Mail International Tracked","23.99","US"),
    ("Royal Mail Tracked 48","3.95","GB"),
])
def test_customer_paid_country_and_service_never_charge_seller(service,amount,country):
    snap=classify_shopify_shipping(
        sample_shipping(service=service,paid=amount,country=country),
        merchandise_minor=9999,
    )
    assert snap.charge_policy==CUSTOMER_PAID
    assert seller_auto_postage_charge(snap.charge_policy,1999)==0


@pytest.mark.parametrize("service,country,total",[
    ("Royal Mail International Tracked","GB",8500),
    ("Royal Mail Tracked 24","GB",8500),
    ("Royal Mail Tracked 48","FR",8500),
    ("Royal Mail Tracked 48","GB",4999),
])
def test_free_other_country_method_or_low_basket_is_platform_review_not_owner_charge(service,country,total):
    snap=classify_shopify_shipping(
        sample_shipping(service=service,paid="0.00",country=country),
        merchandise_minor=total,
    )
    assert snap.charge_policy==OTHER_REVIEW
    assert seller_auto_postage_charge(snap.charge_policy,800)==0


def test_missing_country_or_unverified_delivery_line_fails_closed():
    data=sample_shipping(paid="0.00",detailed=False,original="3.95")
    data.pop("shipping_address")
    snap=classify_shopify_shipping(data,merchandise_minor=12000)
    assert snap.evidence_status=="NEEDS_REVIEW"
    assert snap.charge_policy==OTHER_REVIEW
    assert snap.destination_country=="ZZ"
    assert seller_auto_postage_charge(snap.charge_policy,295)==0


def test_free_shipping_discount_uses_actual_discounted_zero_not_395_original():
    snap=classify_shopify_shipping(sample_shipping(
        paid="0.00",original="3.95"
    ),merchandise_minor=5100)
    assert snap.customer_shipping_paid_minor==0
    assert snap.charge_policy==FREE_UK_TRACKED48


@pytest.mark.parametrize("value",[-1,1.237,True,None])
def test_invalid_actual_carrier_invoice_will_not_silently_debit_owner(value):
    with pytest.raises(ValueError):
        seller_auto_postage_charge(FREE_UK_TRACKED48,value)


def test_single_checkout_paid_shipping_money_is_platform_only_new_orders():
    paid=PIPELINE[PIPELINE.index("async def _process_paid_order("):
        PIPELINE.index("async def _process_cancelled_order(")]
    assert "classify_shopify_shipping(" in paid
    assert "insert into tcg.shopify_delivery_accounts" in paid
    assert "shipping_snapshot.customer_shipping_paid_minor" in paid
    assert "shipping_allocations" not in paid
    assert "'SHIPPING_REVENUE'" not in paid
    assert "shopify_order_reference" in paid


def test_shipping_refund_is_platform_only_for_new_orders_but_legacy_unchanged():
    refund=PIPELINE[PIPELINE.index("async def _process_refund("):]
    assert "select customer_shipping_paid_minor" in refund
    assert "insert into tcg.shopify_delivery_refunds" in refund
    assert "shipping_refund_minor and platform_delivery is None" in refund
    assert "'SHIPPING_REFUND'" in refund
    assert "SHIPPING_REFUND_EXCEEDS_REVENUE" in refund
    assert "SHIPPING_REFUND_ID_CONFLICT" in refund


def test_verified_actual_postage_creates_one_private_receipt_and_only_net_owner_ledger():
    source=FINANCE[FINANCE.index("async def reconcile_shopify_postage("):
        FINANCE.index('@router.post("/finance/manual-sales"')]
    assert "seller_auto_postage_charge(" in source
    assert "insert into tcg.shopify_postage_actual_costs" in source
    assert "owner_postage_charge" in source
    assert "postage_allocations = allocate_minor(" in source
    assert "carrier_label_reference" in source
    assert "target_owner_id" in source
    assert "UniqueViolationError" in source
    assert "shipping_cost_reconciled_at" in source
    assert "replayed" in source


def test_platform_postage_finance_data_hidden_by_rls_and_immutable():
    for name in (
        "tcg.shopify_delivery_accounts",
        "tcg.shopify_delivery_refunds",
        "tcg.shopify_postage_actual_costs",
    ):
        assert f"create table {name}" in POLICY_SQL
        assert f"alter table {name} enable row level security" in POLICY_SQL
    assert POLICY_SQL.count("using (tcg.is_platform_admin())") >= 3
    assert POLICY_SQL.count("with check (tcg.is_platform_admin())") >= 3
    assert POLICY_SQL.count("tcg.prevent_finance_mutation()") >= 3
    assert "owner_net_shopify_postage(uuid)" in POLICY_SQL
    assert "language plpgsql" in POLICY_SQL
    assert "security definer" in POLICY_SQL
    assert "m.user_id=tcg.current_user_id()" in POLICY_SQL
    assert "oi.id=p_order_item_id" in POLICY_SQL
    assert "o.status='PAID'" in POLICY_SQL


def test_seller_can_only_see_single_net_shipping_charge_without_customer_or_carrier_amounts():
    assert "select charge_policy,net_shipping_charge_minor,policy_status" in OWNER
    route=OWNER[OWNER.index('@router.get("/to-ship/{order_item_id}/shipping-cost")'):]
    assert "OWNER_NET_POSTAGE_POLICY" in route
    assert '"net_shipping_charge_minor"' in route
    for forbidden in (
        '"buyer_shipping_retained_minor":',
        '"verified_postage_cost_minor":',
        '"seller_additional_shipping_charge_minor":',
        '"owner_allocated_shipping_minor":',
    ):
        assert forbidden not in route
    assert "buyer_shipping_retained_minor" not in WIZARD
    assert "owner_allocated_shipping_minor" not in WIZARD
    assert "verified_postage_cost_minor" not in WIZARD
    assert "Customer paid for shipping" not in WIZARD
    assert '"Net shipping charge"' in WIZARD
    assert "Pending automatic charge" in WIZARD
    assert "shippingLabelPurchase" not in WIZARD


def test_checkout_sales_refund_and_owner_payout_immutable_pre_release():
    assert "No per-seller approval" not in POLICY_SQL
    assert "seller_auto_postage_charge" not in OWNER
    assert "purchase_allowed" in OWNER
    assert "shopify_postage_actual_costs" not in WIZARD
