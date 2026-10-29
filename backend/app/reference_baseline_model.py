"""Deterministic, non-authoritative price estimates for exact card printings.

Only matching, permitted market observations are used. All outputs are
provisional catalogue guides; never inventory valuations or Shopify prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

ACTIVE_SOURCES = frozenset({
    "EBAY_OFFICIAL_BROWSE", "CARDTRADER_OFFICIAL_API",
    "CARDMARKET_PERMITTED_API",
})
CONFIRMED_IDENTITY = frozenset({"EXACT_SOURCE_PRODUCT", "EXACT_ARTWORK"})
ORDINARY_VARIANTS = frozenset({"STANDARD"})
ORDINARY_RARITIES = frozenset({"C", "COMMON", "UC", "UNCOMMON"})


@dataclass(frozen=True)
class Printing:
    provider: str
    system_code: str
    set_id: str
    provider_id: str
    language: str
    variant: str
    rarity: str

    def valid(self) -> bool:
        return all(isinstance(value, str) and bool(value.strip())
                   for value in (self.provider, self.system_code, self.set_id,
                                 self.provider_id, self.language, self.variant, self.rarity))


@dataclass(frozen=True)
class AskingOffer:
    printing: Printing
    source: str
    source_product_id: str
    listing_id: str
    seller_id: str
    identity_proof: str
    price_gbp_minor: int
    observed_at: datetime
    condition: str = "Near Mint"
    item_type: str = "SINGLE_RAW"
    shipping_gbp_minor: int | None = None


@dataclass(frozen=True)
class PeerGuide:
    printing: Printing
    price_gbp_minor: int
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class ProvisionalEstimate:
    printing: Printing
    estimate_minor: int
    low_minor: int
    high_minor: int
    confidence: str
    method: str
    evidence_count: int
    source_listing_ids: tuple[str, ...]
    physical_valuation_eligible: bool = False
    sold_comparable: bool = False


def _fresh(value: datetime, now: datetime, *, days: int = 7) -> bool:
    return (isinstance(value, datetime) and value.tzinfo is not None
            and now - timedelta(days=days) <= value <= now)


def _quantile(sorted_values: list[int], percentile: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile
    i = int(position)
    fraction = position - i
    return sorted_values[i] * (1 - fraction) + sorted_values[min(i + 1, len(sorted_values) - 1)] * fraction


def exact_listing_baseline(
    printing: Printing, observations: list[AskingOffer], *, now: datetime | None = None
) -> ProvisionalEstimate | None:
    """Price exact artwork/printing only. Unmatched offers have zero influence.

    One seller is a low-confidence asking indication, never a market valuation.
    Outliers are removed relative to the median; a lower-half robust median
    prevents inflated asks from driving the estimate.
    """
    now = now or datetime.now(timezone.utc)
    if not printing.valid():
        return None
    per_seller: dict[tuple[str, str], tuple[int, str]] = {}
    for offer in observations:
        if (offer.printing != printing or offer.source not in ACTIVE_SOURCES
                or offer.identity_proof not in CONFIRMED_IDENTITY
                or not offer.source_product_id or not offer.listing_id or not offer.seller_id
                or offer.condition != "Near Mint" or offer.item_type != "SINGLE_RAW"
                or type(offer.price_gbp_minor) is not int or offer.price_gbp_minor <= 0
                or offer.shipping_gbp_minor is not None
                    and (type(offer.shipping_gbp_minor) is not int or offer.shipping_gbp_minor < 0)
                or not _fresh(offer.observed_at, now)):
            continue
        # A product value excludes unreported shipping rather than guessing it.
        price = offer.price_gbp_minor
        key = (offer.source, offer.seller_id)
        if key not in per_seller or price < per_seller[key][0]:
            per_seller[key] = (price, f"{offer.source}:{offer.listing_id}")
    if not per_seller:
        return None
    all_rows = sorted(per_seller.values())
    centre = median(value for value, _ in all_rows)
    # Do not allow a single absurd high or low asking price to dominate.
    trimmed = [(price, identifier) for price, identifier in all_rows
               if len(all_rows) < 3 or centre / 5 <= price <= centre * 3]
    if not trimmed:
        return None
    prices = sorted(price for price, _ in trimmed)
    # Select the lower end of credible prices, not the mean of all advertisements.
    count = len(prices)
    lower = prices[:max(1, (count + 1) // 2)]
    estimate = max(1, int(median(lower)))
    low = prices[0]
    high = max(estimate, int(_quantile(prices, .75)))
    return ProvisionalEstimate(
        printing=printing, estimate_minor=estimate, low_minor=low,
        high_minor=high, confidence="HIGH" if count >= 5 else "MEDIUM" if count >= 3 else "LOW",
        method="EXACT_ACTIVE_ASKING_LOWER_MEDIAN", evidence_count=count,
        source_listing_ids=tuple(identifier for _, identifier in trimmed),
    )


def ordinary_peer_baseline(
    printing: Printing, peers: list[PeerGuide], *, now: datetime | None = None
) -> ProvisionalEstimate | None:
    """Conservative low-confidence fallback ONLY for standard C/UC cards.

    The result never represents a looked-up price for this exact printing.
    Parallel, alternate-art, SP, SR, SEC, promotional and other rarities
    cannot borrow a set/rarity peer price.
    """
    now = now or datetime.now(timezone.utc)
    if (not printing.valid() or printing.variant.upper() not in ORDINARY_VARIANTS
            or printing.rarity.upper() not in ORDINARY_RARITIES):
        return None
    current: dict[str, int] = {}
    for peer in peers:
        p = peer.printing
        if (p.provider_id == printing.provider_id or
                (p.provider, p.system_code, p.set_id, p.language, p.rarity.upper(), p.variant.upper())
                != (printing.provider, printing.system_code, printing.set_id, printing.language,
                    printing.rarity.upper(), "STANDARD")
                or not _fresh(peer.observed_at, now)
                or type(peer.price_gbp_minor) is not int or peer.price_gbp_minor <= 0
                or not peer.source or peer.source.startswith("MODEL_")):
            continue
        current[p.provider_id] = peer.price_gbp_minor
    values = sorted(current.values())
    if len(values) < 5:
        return None
    q25, q75 = _quantile(values, .25), _quantile(values, .75)
    if q25 <= 0 or q75 > q25 * 3:
        return None
    # Store real pennies: a pound floor would inflate common-card values.
    estimate = max(1, int(q25))
    return ProvisionalEstimate(
        printing, estimate, max(1, int(values[0])), max(estimate, int(q75)),
        "LOW", "MODEL_SAME_SET_STANDARD_RARITY_P25", len(values), (),
    )
