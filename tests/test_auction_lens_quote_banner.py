"""Auction Lens approved banner is a read-only projection of source-gated API data."""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STATIC = BASE / "backend/app/static"
API = (BASE / "backend/app/auction_lens_api.py").read_text()
HTML = (STATIC / "auction-lens-lab.html").read_text()
JS = (STATIC / "auction-lens-lab.js").read_text()
CSS = (STATIC / "auction-lens-lab.css").read_text()


def test_banner_uses_real_approved_stored_logo_and_card_crop_on_left():
    assert (STATIC / "brand-assets/storefront-logo.png").is_file()
    assert 'src="/assets/brand-assets/storefront-logo.png"' in HTML
    assert 'id="auction-banner-thumb"' in HTML
    assert 'class="banner-card"' in HTML
    assert HTML.index('id="auction-banner-thumb"') < HTML.index('id="auction-banner-title"')
    assert 'class="auction-banner"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'AUCTION LENS' in HTML and "VIDEO LAB" in HTML
    # No invented orange-D emblem or generated logo asset.
    assert "fake-logo" not in HTML and "logo-placeholder" not in HTML


def test_banner_requires_explicit_verified_market_quote_and_unknown_cost_gate():
    assert "const verified=Boolean(value&&value.currency===" in JS
    assert 'value.valuationEligible===true' in JS
    assert 'Date.now()<value.expiresAtMs' in JS
    assert 'comparison.marketValueMinor===value.marketValueMinor' in JS
    assert 'comparison.differenceMinor===value.marketValueMinor-comparison.allInMinor' in JS
    assert 'comparison.allInMinor' in JS
    assert '"CHARGES_UNKNOWN"' in JS
    assert 'badge.textContent="FEES UNKNOWN"' in JS
    assert 'badge.textContent="BID TOO OLD"' in JS
    assert "bannerEvidenceExpiresAt" in JS and "bannerBidExpiresAt" in JS
    assert "comparison.bidExpiresAtMs>Date.now()" in JS
    assert 'resetBanner(label || "Scanning for a card…")' in JS
    assert 'thumb.hidden=true; thumb.removeAttribute("src")' in JS
    assert 'if(!$("rights-affirmed").checked&&running)stop()' in JS
    # Browser is not trusted with calculating market value or bidder fees.
    assert "TCGPlayer" not in JS and "fetch('https://" not in JS


def test_quote_is_only_optional_manual_data_and_api_uses_server_eligible_value():
    for name in ("bid-manual", "ship-manual", "fee-manual", "tax-manual", "other-manual"):
        assert f'id="{name}"' in HTML
    assert 'bid_observed_at:new Date(bidObservedAtMs || 0).toISOString()' in JS
    assert 'shipping_minor:parsePence("ship-manual")' in JS
    assert 'additional_costs_minor:parsePence("other-manual")' in JS
    assert 'quote: PilotAuctionQuote | None' in API
    assert 'compare_verified_quote(' in API
    assert 'verified_uk_value=response.get("value")' in API
    assert '"TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED"' in API
    assert 'readonly_snapshot=True' in API
    assert "INSERT INTO" not in API and "UPDATE tcg." not in API


def test_readable_compact_approved_brand_treatment_is_stable():
    assert '#071b3f' in CSS
    assert '#ff9a52' in CSS
    assert '[data-state="UNDER_MARKET"]' in CSS
    assert '[data-state="OVER_MARKET"]' in CSS
    assert '@media(max-width:510px)' in CSS
    assert '@media(prefers-reduced-motion:reduce)' in CSS
