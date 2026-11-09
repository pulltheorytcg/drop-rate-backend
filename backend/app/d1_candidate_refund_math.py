"""Inactive D1 refund/commission reversal mathematics, UK pennies only.

This is a pure, deterministic preparation step, NOT a live finance writer.
Its output must eventually be committed in the SAME D1 transaction as a
signed, idempotent refund event, inventory return-to-inspection update and
append-only ledger rows. It never contacts PostgreSQL, Shopify or Cloudflare.

Card sale refunds and shipping refunds MUST be independently distinguished.
The present PostgreSQL manual refund handler permits a combined upper bound,
while its commission trigger checks original *card* net sale; this migration
candidate refuses that ambiguous allocation rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .d1_candidate_sale import MAX_MONEY, CandidateSaleGuard, commission_minor


class CandidateRefundGuard(CandidateSaleGuard):
    """An invalid refund financial state; never disclose financial source values."""


@dataclass(frozen=True, slots=True)
class OriginalSale:
    net_sale_minor: int
    shipping_revenue_minor: int
    commission_bps_snapshot: int
    original_commission_minor: int
    currency: str = "GBP"


@dataclass(frozen=True, slots=True)
class RefundProgress:
    card_refunded_minor: int
    shipping_refunded_minor: int
    commission_reversed_minor: int
    already_returned: bool = False
    inventory_status: str = "SOLD"


@dataclass(frozen=True, slots=True)
class RequestedRefund:
    card_refund_minor: int
    shipping_refund_minor: int = 0
    return_to_inspection: bool = False


@dataclass(frozen=True, slots=True)
class RefundLedgerDelta:
    card_refund_debit_minor: int
    shipping_refund_debit_minor: int
    commission_reversal_credit_minor: int
    total_refund_minor: int
    cumulative_card_refunded_minor: int
    cumulative_shipping_refunded_minor: int
    cumulative_commission_reversed_minor: int
    return_to_inspection: bool


def _pennies(value: object, *, allow_zero: bool = True) -> int:
    if (type(value) is not int or value < (0 if allow_zero else 1)
            or value > MAX_MONEY):
        raise CandidateRefundGuard("Invalid nonnegative GBP minor units")
    return value


def calculate_refund_ledger_delta(
    original: OriginalSale, prior: RefundProgress, requested: RequestedRefund,
) -> RefundLedgerDelta:
    """Calculate a valid next append-only ledger adjustment in minor units.

    Must be called *under* a database-enforced unique refund source key and
    single transaction. Prior totals must be re-read and checked within that
    transaction, not trusted from a JWT, browser or stale FastAPI read.
    """
    if (not isinstance(original,OriginalSale)
            or not isinstance(prior,RefundProgress)
            or not isinstance(requested,RequestedRefund)
            or original.currency!="GBP"
            or type(prior.already_returned) is not bool
            or type(requested.return_to_inspection) is not bool):
        raise CandidateRefundGuard("Unsupported refund shape, flags or currency")

    net=_pennies(original.net_sale_minor,allow_zero=False)
    shipping=_pennies(original.shipping_revenue_minor)
    prior_card=_pennies(prior.card_refunded_minor)
    prior_ship=_pennies(prior.shipping_refunded_minor)
    prior_reversal=_pennies(prior.commission_reversed_minor)
    original_fee=_pennies(original.original_commission_minor)
    new_card=_pennies(requested.card_refund_minor)
    new_ship=_pennies(requested.shipping_refund_minor)

    if not new_card and not new_ship:
        raise CandidateRefundGuard("Refund event has no money movement")
    if prior_card>net or prior_ship>shipping:
        raise CandidateRefundGuard("Historical refund exceeds source sale or shipping")
    if new_card>net-prior_card or new_ship>shipping-prior_ship:
        raise CandidateRefundGuard("Refund exceeds remaining line or shipping amount")
    if original_fee!=commission_minor(net,original.commission_bps_snapshot):
        raise CandidateRefundGuard("Original commission snapshot does not match sale")
    expected_before=original_fee-commission_minor(
        net-prior_card,original.commission_bps_snapshot)
    if prior_reversal!=expected_before:
        raise CandidateRefundGuard("Existing commission reversal ledger is inconsistent")

    cumulative_card=prior_card+new_card
    cumulative_shipping=prior_ship+new_ship
    target_fee=commission_minor(net-cumulative_card,
                                original.commission_bps_snapshot)
    cumulative_reversal=original_fee-target_fee
    new_reversal=cumulative_reversal-prior_reversal
    if not 0<=new_reversal<=original_fee:
        raise CandidateRefundGuard("Commission reversal would be negative or excessive")

    if requested.return_to_inspection:
        if (prior.already_returned or prior.inventory_status!="SOLD"
                or cumulative_card!=net):
            raise CandidateRefundGuard("Only fully card-refunded SOLD stock can return to inspection")
    elif prior.already_returned and new_card:
        raise CandidateRefundGuard("Cannot refund a physical card already returned to inspection")

    return RefundLedgerDelta(
        card_refund_debit_minor=-new_card,
        shipping_refund_debit_minor=-new_ship,
        commission_reversal_credit_minor=new_reversal,
        total_refund_minor=new_card+new_ship,
        cumulative_card_refunded_minor=cumulative_card,
        cumulative_shipping_refunded_minor=cumulative_shipping,
        cumulative_commission_reversed_minor=cumulative_reversal,
        return_to_inspection=requested.return_to_inspection,
    )
