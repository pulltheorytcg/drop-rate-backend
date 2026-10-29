"""Regression tests: missing-card pricing must not merge art variants."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.reference_baseline_model import (
    AskingOffer, PeerGuide, Printing, exact_listing_baseline, ordinary_peer_baseline,
)

NOW = datetime(2026, 10, 29, 20, tzinfo=timezone.utc)


def card(**changes):
    return replace(Printing(
        "Bandai Official", "ONE_PIECE_CARD_GAME", "OP16", "OP16-001",
        "English", "STANDARD", "C",
    ), **changes)


def offer(seller, amount, printing=None, **changes):
    return replace(AskingOffer(
        printing or card(), "EBAY_OFFICIAL_BROWSE", "exact-product",
        f"listing-{seller}", str(seller), "EXACT_ARTWORK",
        amount, NOW,
    ), **changes)


def peer(i, price, printing=None):
    return PeerGuide(printing or card(provider_id=f"OP16-{i:03}"),
                     price, NOW, "CARDMARKET_PERMITTED_API")


def test_exact_variants_cannot_borrow_each_others_price():
    standard = card()
    alternate = card(provider_id="OP16-001_p1", variant="ALT_ART")
    inputs = [offer(1, 200), offer(2, 230), offer(3, 250),
              offer(4, 9000, alternate), offer(5, 10000, alternate),
              offer(6, 9500, alternate)]
    base = exact_listing_baseline(standard, inputs, now=NOW)
    alt = exact_listing_baseline(alternate, inputs, now=NOW)
    assert base.estimate_minor == 200
    assert alt.estimate_minor == 9000
    assert base.method == alt.method == "EXACT_ACTIVE_ASKING_LOWER_MEDIAN"
    assert not base.physical_valuation_eligible and not alt.sold_comparable


def test_extreme_overpriced_ad_does_not_drive_estimate():
    estimates = [offer(1, 3000), offer(2, 3200), offer(3, 3400),
                 offer(4, 3600), offer(5, 20000)]
    result = exact_listing_baseline(card(), estimates, now=NOW)
    assert result.estimate_minor <= 3400
    assert result.high_minor < 20000
    assert result.evidence_count == 4


def test_single_seller_is_provisional_low_not_sold():
    result = exact_listing_baseline(card(), [offer(1, 1250)], now=NOW)
    assert result.confidence == "LOW"
    assert result.estimate_minor == 1250
    assert result.method == "EXACT_ACTIVE_ASKING_LOWER_MEDIAN"
    assert result.physical_valuation_eligible is False
    assert result.sold_comparable is False


def test_duplicate_seller_not_multiple_independent_evidence():
    entries = [offer(1, 300), replace(offer(1, 350), listing_id="different-listing"),
               offer(2, 325)]
    result = exact_listing_baseline(card(), entries, now=NOW)
    assert result.evidence_count == 2
    assert result.confidence == "LOW"


def test_rejects_wrong_identity_source_unknown_condition_lots_and_stale():
    inputs = [
        offer(1, 900, printing=card(language="Japanese")),
        offer(2, 800, identity_proof="TEXT_ONLY"),
        offer(3, 700, condition="Played"),
        offer(4, 600, item_type="PLAYSET"),
        offer(5, 500, source="UNPERMITTED_SCRAPE"),
        offer(6, 400, observed_at=NOW-timedelta(days=12)),
        offer(7, 300, observed_at=NOW+timedelta(minutes=1)),
    ]
    assert exact_listing_baseline(card(), inputs, now=NOW) is None


def test_standard_low_rarity_peer_estimate_can_be_pennies():
    peers = [peer(i, price) for i, price in enumerate([2, 3, 4, 4, 5, 6, 7], start=2)]
    result = ordinary_peer_baseline(card(), peers, now=NOW)
    assert result.estimate_minor == 4
    assert result.confidence == "LOW"
    assert result.method == "MODEL_SAME_SET_STANDARD_RARITY_P25"
    assert result.physical_valuation_eligible is False


def test_alternate_rare_promo_sr_sec_never_get_peer_price():
    peers = [peer(i, 300) for i in range(2, 12)]
    for changes in (
        {"variant":"ALT_ART"}, {"variant":"SP"}, {"variant":"PARALLEL"},
        {"variant":"STANDARD", "rarity":"SR"},
        {"variant":"STANDARD", "rarity":"SEC"},
        {"variant":"STANDARD", "rarity":"SP"},
        {"variant":"STANDARD", "rarity":"PR"},
    ):
        assert ordinary_peer_baseline(card(**changes), peers, now=NOW) is None


def test_peer_market_must_match_language_set_game_rarity_and_base_printing():
    target = card()
    peers = [
        peer(2, 4),
        peer(3, 100, card(provider_id="J-3", language="Japanese")),
        peer(4, 200, card(provider_id="OP17-4", set_id="OP17")),
        peer(5, 300, card(provider_id="p1-5", variant="ALT_ART")),
        peer(6, 400, card(provider_id="SR-6", rarity="SR")),
        peer(7, 500, card(provider_id="DBS-7", system_code="DRAGON_BALL_SUPER_MASTERS")),
    ]
    assert ordinary_peer_baseline(target, peers, now=NOW) is None


def test_peer_spread_protection_and_stale_peers():
    peers = [peer(i, price) for i, price in enumerate([2, 3, 4, 10, 30, 50], start=2)]
    assert ordinary_peer_baseline(card(), peers, now=NOW) is None
    stale = [replace(peer(i, 4), observed_at=NOW-timedelta(days=9)) for i in range(2, 12)]
    assert ordinary_peer_baseline(card(), stale, now=NOW) is None
