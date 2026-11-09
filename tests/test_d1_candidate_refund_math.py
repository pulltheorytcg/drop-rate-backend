"""Penny-exact refund plan tests: zero production database or payment access."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.d1_candidate_refund_math import (
    CandidateRefundGuard,OriginalSale,RefundProgress,RequestedRefund,
    calculate_refund_ledger_delta,
)


def original(*,net=2000,shipping=499,rate=1000,commission=200):
    return OriginalSale(
        net_sale_minor=net,shipping_revenue_minor=shipping,
        commission_bps_snapshot=rate,original_commission_minor=commission,
    )


def progress(*,card=0,shipping=0,reversed=0,
             already_returned=False,inventory_status="SOLD"):
    return RefundProgress(
        card_refunded_minor=card,
        shipping_refunded_minor=shipping,
        commission_reversed_minor=reversed,
        already_returned=already_returned,
        inventory_status=inventory_status,
    )


def test_consignor_partial_then_full_refund_reverses_commission_cumulatively():
    one=calculate_refund_ledger_delta(
        original(),progress(),RequestedRefund(card_refund_minor=500))
    assert one.card_refund_debit_minor==-500
    assert one.shipping_refund_debit_minor==0
    assert one.commission_reversal_credit_minor==50
    assert one.cumulative_card_refunded_minor==500
    two=calculate_refund_ledger_delta(
        original(),progress(card=500,reversed=50),
        RequestedRefund(card_refund_minor=700,shipping_refund_minor=199))
    assert two.card_refund_debit_minor==-700
    assert two.shipping_refund_debit_minor==-199
    assert two.commission_reversal_credit_minor==70
    assert two.cumulative_commission_reversed_minor==120
    final=calculate_refund_ledger_delta(
        original(),progress(card=1200,shipping=199,reversed=120),
        RequestedRefund(card_refund_minor=800,shipping_refund_minor=300,
                        return_to_inspection=True))
    assert final.card_refund_debit_minor==-800
    assert final.shipping_refund_debit_minor==-300
    assert final.commission_reversal_credit_minor==80
    assert final.cumulative_card_refunded_minor==2000
    assert final.cumulative_shipping_refunded_minor==499
    assert final.cumulative_commission_reversed_minor==200
    assert final.return_to_inspection is True


def test_shipping_only_refund_never_reverses_marketplace_commission():
    result=calculate_refund_ledger_delta(
        original(),progress(),RequestedRefund(card_refund_minor=0,
                                             shipping_refund_minor=499))
    assert result.card_refund_debit_minor==0
    assert result.shipping_refund_debit_minor==-499
    assert result.commission_reversal_credit_minor==0
    assert result.cumulative_commission_reversed_minor==0


def test_founder_has_zero_marketplace_fee_and_can_return_stock_after_full_card_refund():
    x=OriginalSale(net_sale_minor=1000,shipping_revenue_minor=0,
                   commission_bps_snapshot=0,original_commission_minor=0)
    result=calculate_refund_ledger_delta(
        x,progress(),RequestedRefund(card_refund_minor=1000,
                                    return_to_inspection=True))
    assert result.card_refund_debit_minor==-1000
    assert result.commission_reversal_credit_minor==0
    assert result.return_to_inspection


def test_malformed_original_founder_commission_fails_closed():
    x=OriginalSale(net_sale_minor=1000,shipping_revenue_minor=499,
                   commission_bps_snapshot=0,original_commission_minor=100)
    with pytest.raises(CandidateRefundGuard,match="Original commission"):
        calculate_refund_ledger_delta(x,progress(),
            RequestedRefund(card_refund_minor=500))


def test_rounding_is_on_cumulative_remaining_card_value_not_each_refund():
    x=OriginalSale(net_sale_minor=5,shipping_revenue_minor=0,
                   commission_bps_snapshot=1000,original_commission_minor=1)
    first=calculate_refund_ledger_delta(x,progress(),
              RequestedRefund(card_refund_minor=1))
    assert first.commission_reversal_credit_minor==1
    second=calculate_refund_ledger_delta(
        x,progress(card=1,reversed=1),RequestedRefund(card_refund_minor=1))
    assert second.commission_reversal_credit_minor==0
    assert second.cumulative_commission_reversed_minor==1


@pytest.mark.parametrize("before,request",[
    (progress(card=2100),RequestedRefund(card_refund_minor=1)),
    (progress(shipping=500),RequestedRefund(card_refund_minor=1)),
    (progress(card=1900,reversed=190),RequestedRefund(card_refund_minor=101)),
    (progress(shipping=400),RequestedRefund(shipping_refund_minor=100,card_refund_minor=0)),
    (progress(reversed=1),RequestedRefund(card_refund_minor=1)),
    (progress(card=500,reversed=40),RequestedRefund(card_refund_minor=1)),
])
def test_over_refund_and_inconsistent_historical_ledger_are_denied(before,request):
    with pytest.raises(CandidateRefundGuard):
        calculate_refund_ledger_delta(original(),before,request)


@pytest.mark.parametrize("before,request",[
    (progress(),RequestedRefund(card_refund_minor=0)),
    (progress(),RequestedRefund(card_refund_minor=500,return_to_inspection=True)),
    (progress(inventory_status="APPROVED"),
     RequestedRefund(card_refund_minor=2000,return_to_inspection=True)),
    (progress(already_returned=True),
     RequestedRefund(card_refund_minor=2000,return_to_inspection=True)),
    (progress(already_returned=True),RequestedRefund(card_refund_minor=1)),
])
def test_restocks_require_full_original_card_refund_and_no_prior_return(before,request):
    with pytest.raises(CandidateRefundGuard):
        calculate_refund_ledger_delta(original(),before,request)


@pytest.mark.parametrize("bad",[
    RequestedRefund(card_refund_minor=True),
    RequestedRefund(card_refund_minor=-1),
    RequestedRefund(card_refund_minor=100_000_000_000_001),
    RequestedRefund(card_refund_minor=1,shipping_refund_minor=True),
    RequestedRefund(card_refund_minor=1,return_to_inspection=1),
])
def test_invalid_money_or_flags_cannot_be_coerced(bad):
    with pytest.raises(CandidateRefundGuard):
        calculate_refund_ledger_delta(original(),progress(),bad)


def test_non_gbp_and_invalid_prior_return_boolean_are_denied():
    with pytest.raises(CandidateRefundGuard):
        calculate_refund_ledger_delta(
            replace(original(),currency="USD"),progress(),
            RequestedRefund(card_refund_minor=1))
    with pytest.raises(CandidateRefundGuard):
        calculate_refund_ledger_delta(
            original(),replace(progress(),already_returned=1),
            RequestedRefund(card_refund_minor=1))


def test_stored_shipping_refund_may_follow_stock_return_without_second_card_refund():
    result=calculate_refund_ledger_delta(
        original(),progress(card=2000,reversed=200,already_returned=True),
        RequestedRefund(card_refund_minor=0,shipping_refund_minor=499))
    assert result.shipping_refund_debit_minor==-499
    assert result.card_refund_debit_minor==0
    assert result.commission_reversal_credit_minor==0
    assert result.return_to_inspection is False
