"""Deterministic GBP auction comparison for a future permissioned Auction Lens.

Pure calculation only: no frame capture, platform access, pricing sources, stock
changes, bidding, database writes or third-party requests. The calling FastAPI
session must establish exact identity and legal/price eligibility independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class AuctionLot:
    """One observed auction lot; unknown costs are None, never assumed zero."""

    listing_id: str
    identity_key: str
    scene_generation: int
    identity_confirmed: bool
    bid_minor: int
    shipping_minor: int | None
    buyer_fees_minor: int | None
    import_tax_minor: int | None
    additional_costs_minor: int | None
    bid_observed_at: datetime
    status: str = "ACTIVE"
    currency: str = "GBP"


@dataclass(frozen=True)
class MarketEvidence:
    """Already-authorised, already-normalised UK Market Value evidence."""

    identity_key: str
    scene_generation: int
    exact_match: bool
    market_value_minor: int | None
    evidence_at: datetime | None
    expires_at: datetime | None
    source: str
    status: str = "AVAILABLE"
    kind: str = "MARKET_VALUE"
    currency: str = "GBP"
    market_region: str = "GB"
    valuation_eligible: bool = False
    display_permitted: bool = False


@dataclass(frozen=True)
class AuctionComparison:
    status: str
    all_in_minor: int | None = None
    market_value_minor: int | None = None
    saving_vs_market_minor: int | None = None
    source: str | None = None
    evidence_at: datetime | None = None


def _aware(when: datetime | None) -> bool:
    return isinstance(when, datetime) and when.tzinfo is not None and when.utcoffset() is not None


def _minor(name: str, amount: int | None) -> None:
    if amount is not None and (type(amount) is not int or amount < 0):
        raise ValueError(f"{name} must be a non-negative integer in minor units, or None")


def compare_uk_auction(
    lot: AuctionLot,
    evidence: MarketEvidence,
    *,
    now: datetime,
    around_basis_points: int,
    max_bid_age_seconds: int,
) -> AuctionComparison:
    """Return a safe buyer signal, or an abstention status without a value.

    The calling layer must bind the current scene to a locked, server-verified
    canonical identity and supply UK market evidence. The tolerance and bid
    freshness limits are explicit policy inputs, never guessed in this module.
    """
    if not _aware(now):
        raise ValueError("now must be timezone-aware")
    if type(around_basis_points) is not int or not 0 <= around_basis_points <= 10_000:
        raise ValueError("around_basis_points must be in [0, 10000]")
    if type(max_bid_age_seconds) is not int or max_bid_age_seconds <= 0:
        raise ValueError("max_bid_age_seconds must be a positive integer")
    for name in ("bid_minor", "shipping_minor", "buyer_fees_minor",
                 "import_tax_minor", "additional_costs_minor"):
        _minor(name, getattr(lot, name))
    _minor("market_value_minor", evidence.market_value_minor)

    if lot.currency != "GBP":
        return AuctionComparison("UNSUPPORTED_CURRENCY")
    if lot.status != "ACTIVE" or not lot.listing_id.strip():
        return AuctionComparison("AUCTION_NOT_ACTIVE")
    if (not _aware(lot.bid_observed_at)
            or lot.bid_observed_at > now
            or now - lot.bid_observed_at > timedelta(seconds=max_bid_age_seconds)):
        return AuctionComparison("STALE_BID")
    if (not lot.identity_confirmed or not evidence.exact_match or
            not lot.identity_key or lot.identity_key != evidence.identity_key or
            lot.scene_generation != evidence.scene_generation or
            lot.scene_generation < 0):
        return AuctionComparison("CHECK_VERSION")

    if (evidence.kind != "MARKET_VALUE" or evidence.status != "AVAILABLE" or
            evidence.currency != "GBP" or evidence.market_region != "GB" or
            not evidence.valuation_eligible or not evidence.display_permitted or
            not evidence.source.strip() or not _aware(evidence.evidence_at) or
            not _aware(evidence.expires_at) or
            evidence.evidence_at > now or evidence.expires_at <= now or
            evidence.market_value_minor is None or evidence.market_value_minor == 0):
        return AuctionComparison("NO_CURRENT_MARKET_VALUE")

    charges = (lot.shipping_minor, lot.buyer_fees_minor,
               lot.import_tax_minor, lot.additional_costs_minor)
    if any(charge is None for charge in charges):
        return AuctionComparison("CHARGES_UNKNOWN")

    all_in = lot.bid_minor + sum(charges)
    market_value = evidence.market_value_minor
    difference = market_value - all_in  # positive means all-in cost is lower
    tolerance_minor = (market_value * around_basis_points + 9_999) // 10_000

    if difference > tolerance_minor:
        status = "UNDER_MARKET"
    elif difference < -tolerance_minor:
        status = "OVER_MARKET"
    else:
        status = "AROUND_MARKET"
    return AuctionComparison(
        status=status, all_in_minor=all_in,
        market_value_minor=market_value,
        saving_vs_market_minor=difference,
        source=evidence.source, evidence_at=evidence.evidence_at,
    )
