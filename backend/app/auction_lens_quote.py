"""UK auction quote projection from a server-verified exact-print result.

Do not accept a client-supplied Market Value. The only admissible valuation
is the existing _eligible_uk_value output from the authenticated pilot route.
No quote, provider call, image or frame is stored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .auction_lens_uk import AuctionLot, MarketEvidence, compare_uk_auction


def _evidence_time(value: Any) -> datetime | None:
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, ValueError, OSError):
        return None


def compare_verified_quote(
    *,
    quote: Any,
    identity_key: str,
    scene_generation: int,
    verified_uk_value: Mapping[str, Any] | None,
    display_rights_approved: bool,
    now: datetime,
) -> dict[str, Any]:
    """One deterministic, abstaining result for one current observed bid.

    quote is an already validated PilotAuctionQuote, not arbitrary client
    pricing evidence. All amounts are integer pence; unknown costs remain None.
    """
    evidence = verified_uk_value or {}
    market = MarketEvidence(
        identity_key=identity_key,
        scene_generation=scene_generation,
        exact_match=True,
        market_value_minor=evidence.get("marketValueMinor")
        if type(evidence.get("marketValueMinor")) is int else None,
        evidence_at=_evidence_time(evidence.get("evidenceAtMs")),
        expires_at=_evidence_time(evidence.get("expiresAtMs")),
        source=str(evidence.get("source") or ""),
        status="AVAILABLE" if verified_uk_value is not None else "UNAVAILABLE",
        kind="MARKET_VALUE",
        currency=str(evidence.get("currency") or ""),
        market_region="GB",
        valuation_eligible=evidence.get("valuationEligible") is True,
        display_permitted=display_rights_approved,
    )
    lot = AuctionLot(
        listing_id=quote.lot_ref,
        identity_key=identity_key,
        scene_generation=scene_generation,
        identity_confirmed=True,
        bid_minor=quote.bid_minor,
        shipping_minor=quote.shipping_minor,
        buyer_fees_minor=quote.buyer_fees_minor,
        import_tax_minor=quote.import_tax_minor,
        additional_costs_minor=quote.additional_costs_minor,
        bid_observed_at=quote.bid_observed_at,
        status=quote.status,
        currency=quote.currency,
    )
    comparison = compare_uk_auction(
        lot,
        market,
        now=now,
        around_basis_points=300,  # ±3%, explicit conservative presentation policy.
        max_bid_age_seconds=30,  # Quotes must be re-observed, never silently reused.
    )
    output: dict[str, Any] = {"status": comparison.status}
    # A quote is not a current UK Market Value. Only disclose the comparison
    # when price rights, the identity, quote age, and ALL costs pass together.
    if (comparison.status in {"UNDER_MARKET", "AROUND_MARKET", "OVER_MARKET"}
            and comparison.all_in_minor is not None
            and comparison.market_value_minor is not None
            and comparison.saving_vs_market_minor is not None):
        output.update({
            "allInMinor": comparison.all_in_minor,
            "marketValueMinor": comparison.market_value_minor,
            "differenceMinor": comparison.saving_vs_market_minor,
            "evidenceAtMs": (
                int(comparison.evidence_at.timestamp() * 1000)
                if comparison.evidence_at else None
            ),
            "source": comparison.source,
        })
    return output
