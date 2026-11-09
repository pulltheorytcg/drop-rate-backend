"""INACTIVE Cloudflare D1 atomic paid-sale candidate. NO production entry point.

This module produces *only parameterized* SQL statements for a single
Cloudflare Workers D1Database.batch(...) transaction. It has no D1 token,
Shopify authentication, Supabase client, HTTP route, payout or payment method.

A trusted FastAPI backend must separately authenticate the source webhook,
resolve exact physical inventory IDs and verified owner membership, and apply
a reviewed write-freeze/replay cutover before any live caller can use this.
Do not execute individual statements as separate HTTP requests: atomicity and
all-or-nothing owner/ledger posting are mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Literal
from uuid import UUID

Source = Literal["SHOPIFY", "EBAY"]
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
EXTERNAL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9:._/-]{0,254}\Z")
DOMAIN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}[a-zA-Z0-9]\Z")
MAX_LINES = 100
MAX_MONEY = 1_000_000_000_000


class CandidateSaleGuard(ValueError):
    """A deterministically refused candidate sale; contains no user data."""


@dataclass(frozen=True, slots=True)
class SaleLine:
    id: str
    inventory_id: str
    owner_id: str
    expected_inventory_version: int
    sale_price_minor: int
    discount_minor: int
    cost_basis_minor: int | None
    commission_bps_snapshot: int


@dataclass(frozen=True, slots=True)
class SaleEvent:
    order_id: str
    source: Source
    source_reference: str
    webhook_id: str
    shop_domain: str
    payload_sha256: str
    placed_at: str
    lines: tuple[SaleLine, ...]


@dataclass(frozen=True, slots=True)
class PreparedStatement:
    sql: str
    params: tuple


def _uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (TypeError, AttributeError, ValueError):
        raise CandidateSaleGuard("A canonical, stable UUID is required") from None
    if canonical != value:
        raise CandidateSaleGuard("Noncanonical identifier; refuse ambiguous identity")
    return canonical


def _external(value: str) -> str:
    if not isinstance(value, str) or EXTERNAL.fullmatch(value) is None:
        raise CandidateSaleGuard("Invalid external reference syntax")
    return value


def _time(value: str) -> str:
    if not isinstance(value, str):
        raise CandidateSaleGuard("Missing UTC sale timestamp")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CandidateSaleGuard("Invalid sale timestamp") from None
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise CandidateSaleGuard("Sale timestamp must have an explicit UTC offset")
    instant = instant.astimezone(timezone.utc)
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _money(value: int, *, can_be_zero: bool = True) -> int:
    if (type(value) is not int or value < (0 if can_be_zero else 1)
            or value > MAX_MONEY):
        raise CandidateSaleGuard("Invalid GBP penny amount")
    return value


def commission_minor(net_sale_minor: int, basis_points: int) -> int:
    """Match PostgreSQL round(numeric) for nonnegative GBP minor units."""
    _money(net_sale_minor)
    if type(basis_points) is not int or not 0 <= basis_points <= 10_000:
        raise CandidateSaleGuard("Invalid owner commission basis points")
    # Safe under SQLite 64-bit INT: MAX_MONEY * 10,000 = 1e16.
    return (net_sale_minor * basis_points + 5000) // 10_000


def _statement(sql: str, *params) -> PreparedStatement:
    if sql.count("?") != len(params) or len(params) > 100:
        raise CandidateSaleGuard("Unbound or overbudgeted SQL parameters")
    if any(isinstance(param, bool) for param in params):
        raise CandidateSaleGuard("Boolean values cannot substitute financial integers")
    return PreparedStatement(sql, params)


def build_paid_sale_batch(event: SaleEvent) -> tuple[PreparedStatement, ...]:
    """Build a *single* atomic transaction with two-owner support.

    DB checks: owner, condition/status, sale intent, version CAS, cost-basis
    snapshot, commission rate, exactly one sale per physical item and
    external source/webhook idempotency. DB triggers create pending ledger
    entries; caller cannot omit the commission debit.

    A successful batch means the SALE_REVENUE exists in PENDING funds, not
    that payment/provider fees or settlement/payout are reconciled.
    """
    if not isinstance(event, SaleEvent) or event.source not in ("SHOPIFY", "EBAY"):
        raise CandidateSaleGuard("Unsupported authenticated sale source")
    order_id = _uuid(event.order_id)
    source_reference = _external(event.source_reference)
    webhook_id = _external(event.webhook_id)
    shop_domain = event.shop_domain
    if (not isinstance(shop_domain, str) or DOMAIN.fullmatch(shop_domain) is None
            or shop_domain.lower() != shop_domain):
        raise CandidateSaleGuard("Invalid merchant domain")
    if (not isinstance(event.payload_sha256, str)
            or HEX64.fullmatch(event.payload_sha256) is None):
        raise CandidateSaleGuard("Invalid original webhook payload hash")
    placed_at = _time(event.placed_at)
    if not isinstance(event.lines, tuple) or not 1 <= len(event.lines) <= MAX_LINES:
        raise CandidateSaleGuard("Sale requires between 1 and 100 physical items")

    lines = []
    seen_items, seen_inventory = set(), set()
    for item in event.lines:
        if not isinstance(item, SaleLine):
            raise CandidateSaleGuard("Malformed physical sale line")
        item_id = _uuid(item.id)
        inventory_id = _uuid(item.inventory_id)
        owner_id = _uuid(item.owner_id)
        if item_id in seen_items or inventory_id in seen_inventory:
            raise CandidateSaleGuard("Duplicate order item or physical inventory ID")
        seen_items.add(item_id)
        seen_inventory.add(inventory_id)
        version = item.expected_inventory_version
        if type(version) is not int or version < 1:
            raise CandidateSaleGuard("Missing inventory compare-and-swap version")
        price = _money(item.sale_price_minor, can_be_zero=False)
        discount = _money(item.discount_minor)
        if discount >= price:
            raise CandidateSaleGuard("Discount must be less than physical sale price")
        net = price - discount
        cost = (None if item.cost_basis_minor is None
                else _money(item.cost_basis_minor))
        fee = commission_minor(net, item.commission_bps_snapshot)
        lines.append((item_id, order_id, inventory_id, owner_id, version, price,
                      discount, net, cost, item.commission_bps_snapshot, fee, placed_at))

    result = [
        _statement(
            "INSERT INTO candidate_orders "
            "(id,source,source_reference,currency,status,placed_at) "
            "VALUES(?,?,?,'GBP','RECONCILIATION_REQUIRED',?)",
            order_id, event.source, source_reference, placed_at,
        ),
        _statement(
            "INSERT INTO candidate_webhook_inbox "
            "(webhook_id,source,shop_domain,payload_sha256,order_id,received_at) "
            "VALUES(?,?,?,?,?,?)",
            webhook_id, event.source, shop_domain, event.payload_sha256,
            order_id, placed_at,
        ),
    ]
    for values in lines:
        result.append(_statement(
            "INSERT INTO candidate_order_items "
            "(id,order_id,inventory_id,owner_id,expected_inventory_version,"
            "sale_price_minor,discount_minor,net_sale_minor,cost_basis_minor,"
            "commission_bps_snapshot,commission_minor,sold_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", *values,
        ))
    # Emitted only after every line succeeds, inside the same transaction.
    # A separate guarded publisher will deliver this after verified cutover.
    result.append(_statement(
        "INSERT INTO candidate_outbox "
        "(id,order_id,event_type,payload_sha256,status,created_at) "
        "VALUES(?,?,'ORDER_POSTED',?,'PENDING',?)",
        "order:" + order_id, order_id, event.payload_sha256, placed_at,
    ))
    return tuple(result)


def classify_webhook_replay(existing: dict, event: SaleEvent) -> Literal["REPLAY", "CONFLICT"]:
    """Compare a fetched immutable inbox row after a UNIQUE constraint error.

    This never silently treats one webhook ID with a different body/source or
    different order as an idempotent replay. It does not mutate either DB.
    """
    if not isinstance(existing, dict):
        raise CandidateSaleGuard("Missing existing webhook verification record")
    return ("REPLAY" if (
        existing.get("webhook_id") == event.webhook_id
        and existing.get("source") == event.source
        and existing.get("shop_domain") == event.shop_domain
        and existing.get("payload_sha256") == event.payload_sha256
        and existing.get("order_id") == event.order_id
    ) else "CONFLICT")
