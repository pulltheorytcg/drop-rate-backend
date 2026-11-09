"""INACTIVE D1 candidate card-refund posting plan: one bound insert + DB triggers.

The source webhook must already be authenticated by FastAPI. All owner, order,
stock-version and prior-ledger validation occurs in the database trigger inside
one D1 transaction. This plan cannot post shipping refunds, move payouts,
change Store Prices or send payment requests. No production HTTP route exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .d1_candidate_sale import (
    HEX64, CandidateSaleGuard, PreparedStatement, _external, _money,
    _statement, _time, _uuid,
)


@dataclass(frozen=True, slots=True)
class CandidateCardRefundEvent:
    id: str
    source: Literal["SHOPIFY", "EBAY"]
    source_reference: str
    order_id: str
    order_item_id: str
    inventory_id: str
    owner_id: str
    card_amount_minor: int
    return_to_inspection: bool
    payload_sha256: str
    occurred_at: str


def build_card_refund_batch(event: CandidateCardRefundEvent) -> tuple[PreparedStatement, ...]:
    """Fail closed on malformed identity; ledger/stock/outbox are trigger-owned.

    D1 Worker must run the returned batch atomically. A duplicate source
    event is a UNIQUE constraint error, never a second ledger adjustment.
    A genuine replay may be acknowledged ONLY after comparing its private
    immutable event row to the original verified source.
    """
    if (not isinstance(event,CandidateCardRefundEvent)
        or event.source not in ("SHOPIFY","EBAY")
        or type(event.return_to_inspection) is not bool
        or not isinstance(event.payload_sha256,str)
        or HEX64.fullmatch(event.payload_sha256) is None):
        raise CandidateSaleGuard("Unverified candidate card refund")
    values=(
        _uuid(event.id),
        event.source,
        _external(event.source_reference),
        _uuid(event.order_id),
        _uuid(event.order_item_id),
        _uuid(event.inventory_id),
        _uuid(event.owner_id),
        _money(event.card_amount_minor,can_be_zero=False),
        int(event.return_to_inspection),
        event.payload_sha256,
        _time(event.occurred_at),
    )
    return (_statement(
        "INSERT INTO candidate_card_refunds "
        "(id,source,source_reference,order_id,order_item_id,inventory_id,"
        "owner_id,card_amount_minor,currency,return_to_inspection,payload_sha256,"
        "occurred_at) VALUES(?,?,?,?,?,?,?,?,'GBP',?,?,?)",
        *values,
    ),)


def classify_card_refund_replay(
    existing: dict, event: CandidateCardRefundEvent,
) -> Literal["REPLAY","CONFLICT"]:
    """Compare original signed source facts, never guessing by refund ID."""
    if not isinstance(existing,dict) or not isinstance(event,CandidateCardRefundEvent):
        raise CandidateSaleGuard("Cannot verify refund source replay")
    return ("REPLAY" if (
        existing.get("id")==event.id
        and existing.get("source")==event.source
        and existing.get("source_reference")==event.source_reference
        and existing.get("order_id")==event.order_id
        and existing.get("order_item_id")==event.order_item_id
        and existing.get("inventory_id")==event.inventory_id
        and existing.get("owner_id")==event.owner_id
        and existing.get("card_amount_minor")==event.card_amount_minor
        and existing.get("return_to_inspection")==int(event.return_to_inspection)
        and existing.get("currency")=="GBP"
        and existing.get("payload_sha256")==event.payload_sha256
    ) else "CONFLICT")
