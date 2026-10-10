"""Seller Hub To Ship panel never pretends labels or customer details exist."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "backend/app/static/owner.html"
JS = ROOT / "backend/app/static/owner-fulfillment.js"
CSS = ROOT / "backend/app/static/owner-fulfillment.css"


def test_dispatch_is_inside_existing_sales_tab():
    html = HTML.read_text()
    assert 'id="owner-view-sales"' in html
    sales = html.split('id="owner-view-sales"', 1)[1].split('id="owner-view-balance"', 1)[0]
    assert 'id="owner-dispatch-review"' in sales
    assert 'id="owner-dispatch-list"' in sales
    assert 'id="owner-sales-body"' in sales
    assert sales.index('id="owner-dispatch-review"') < sales.index('id="owner-sales-body"')
    assert '<script src="/assets/owner-fulfillment.js?v=1" defer></script>' in html
    assert '<link rel="stylesheet" href="/assets/owner-fulfillment.css?v=1">' in html
    assert 'data-owner-view="fulfilment"' not in html


def test_dispatch_frontend_has_no_buyer_address_or_fake_provider_actions():
    js = JS.read_text()
    assert '"/api/v1/fulfilment/to-ship?' in js
    assert 'document.addEventListener("hub-ready"' in js
    assert 'document.addEventListener("owner-view-changed"' in js
    assert 'element("owner-logout-button")' in js
    assert ".textContent" in js
    assert "innerHTML" not in js
    for string in ("shipping_address", "customer_email", "buy-label", "createFulfillment", "markAsFulfilled"):
        assert string not in js
    assert "carrier_label_purchase" in js
    assert "shopify_tracking_sync" in js


def test_dispatch_layout_is_mobile_friendly_and_not_bright_lime():
    css = CSS.read_text()
    assert "@media(max-width:750px)" in css
    assert "grid-template-columns:1fr" in css
    assert "neon" not in css.lower()
    assert "#ccff00" not in css.lower()
