"""Pure, inactive shipping allocation/refund/payment-fee posting contract.

Amounts are *verified per item* externally; no fee percentage, shipping split,
owner identity, payment fee, or refund is guessed by this module. No external
credentials, HTTP route, cloud connection, payouts or live database access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .d1_candidate_sale import (
    CandidateSaleGuard, HEX64, PreparedStatement, _external, _money,
    _statement, _time, _uuid,
)

Kind=Literal["SHIPPING_ALLOCATION","SHIPPING_REFUND","PAYMENT_FEE"]


@dataclass(frozen=True, slots=True)
class CandidateFinancialEvidence:
    id: str
    kind: Kind
    source: Literal["SHOPIFY","EBAY"]
    source_reference: str
    order_id: str
    order_item_id: str
    owner_id: str
    amount_minor: int
    payload_sha256: str
    occurred_at: str


_SQL={
    "SHIPPING_ALLOCATION": (
        "INSERT INTO candidate_shipping_allocations "
        "(id,source,source_reference,order_id,order_item_id,owner_id,"
        "amount_minor,currency,payload_sha256,occurred_at) "
        "VALUES(?,?,?,?,?,?,?,'GBP',?,?)"
    ),
    "SHIPPING_REFUND": (
        "INSERT INTO candidate_shipping_refunds "
        "(id,source,source_reference,order_id,order_item_id,owner_id,"
        "amount_minor,currency,payload_sha256,occurred_at) "
        "VALUES(?,?,?,?,?,?,?,'GBP',?,?)"
    ),
    "PAYMENT_FEE": (
        "INSERT INTO candidate_payment_fees "
        "(id,source,source_reference,order_id,order_item_id,owner_id,"
        "amount_minor,currency,payload_sha256,occurred_at) "
        "VALUES(?,?,?,?,?,?,?,'GBP',?,?)"
    ),
}


def build_financial_evidence_batch(
    event: CandidateFinancialEvidence,
) -> tuple[PreparedStatement, ...]:
    """Prepare one guarded source event; SQLite trigger owns ledger + outbox."""
    if (not isinstance(event,CandidateFinancialEvidence)
            or event.kind not in _SQL
            or event.source not in ("SHOPIFY","EBAY")
            or not isinstance(event.payload_sha256,str)
            or HEX64.fullmatch(event.payload_sha256) is None):
        raise CandidateSaleGuard("Invalid verified financial source event")
    values=(
        _uuid(event.id),
        event.source,
        _external(event.source_reference),
        _uuid(event.order_id),
        _uuid(event.order_item_id),
        _uuid(event.owner_id),
        _money(event.amount_minor,can_be_zero=False),
        event.payload_sha256,
        _time(event.occurred_at),
    )
    return (_statement(_SQL[event.kind],*values),)


def classify_financial_evidence_replay(
    existing: dict, event: CandidateFinancialEvidence,
) -> Literal["REPLAY","CONFLICT"]:
    """Require original source event identity, amount and payload proof."""
    if not isinstance(existing,dict) or not isinstance(event,CandidateFinancialEvidence):
        raise CandidateSaleGuard("Missing verified financial replay evidence")
    return ("REPLAY" if (
        existing.get("id")==event.id
        and existing.get("source")==event.source
        and existing.get("source_reference")==event.source_reference
        and existing.get("order_id")==event.order_id
        and existing.get("order_item_id")==event.order_item_id
        and existing.get("owner_id")==event.owner_id
        and existing.get("amount_minor")==event.amount_minor
        and existing.get("currency")=="GBP"
        and existing.get("payload_sha256")==event.payload_sha256
    ) else "CONFLICT")
