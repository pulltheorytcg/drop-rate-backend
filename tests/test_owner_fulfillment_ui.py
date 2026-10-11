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
    assert 'id="owner-dispatch-shopify-check"' in sales
    assert 'id="owner-dispatch-shopify-status"' in sales
    assert 'id="owner-sales-body"' in sales
    assert sales.index('id="owner-dispatch-review"') < sales.index('id="owner-sales-body"')
    assert '<h3 id="owner-dispatch-heading">To ship' in sales
    assert '<h2>Your sold cards</h2>' in sales
    assert '<script src="/assets/owner-fulfill-wizard.js?v=2" defer></script>' in html
    assert 'id="owner-fulfill-dialog"' in html
    assert 'id="owner-fulfill-print-packing"' in html
    assert 'id="owner-fulfill-print-label"' in html
    assert 'id="owner-fulfill-shipping-figures"' in html
    assert 'id="owner-fulfill-shipping-status"' in html
    assert 'id="owner-fulfill-confirm"' in html

    assert '<script src="/assets/owner-fulfillment.js?v=3" defer></script>' in html
    assert '<link rel="stylesheet" href="/assets/owner-fulfillment.css?v=4">' in html
    assert 'data-owner-view="fulfilment"' not in html


def test_dispatch_frontend_has_no_buyer_address_or_fake_provider_actions():
    js = JS.read_text()
    assert "/api/v1/fulfilment/to-ship?" in js
    assert 'document.addEventListener("hub-ready"' in js
    assert 'document.addEventListener("owner-view-changed"' in js
    assert 'element("owner-logout-button")' in js
    assert ".textContent" in js
    assert "innerHTML" not in js
    for string in ("shipping_address", "customer_email", "buy-label", "createFulfillment", "markAsFulfilled"):
        assert string not in js
    assert "carrier_label_purchase" in js
    assert "shopify_tracking_sync" in js
    assert "/api/v1/fulfilment/shopify-status" in js
    assert "/shopify" in js
    assert "Check Shopify" in js


def test_dispatch_layout_is_mobile_friendly_and_not_bright_lime():
    css = CSS.read_text()
    assert "@media(max-width:750px)" in css
    assert "grid-template-columns:1fr" in css
    assert "neon" not in css.lower()
    assert "#ccff00" not in css.lower()


def test_fulfill_button_has_live_shopify_review_and_no_fake_shipping_label():
    portal = JS.read_text()
    wizard = (ROOT / "backend/app/static/owner-fulfill-wizard.js").read_text()
    assert 'owner-dispatch-fulfill' in portal
    assert '"seller-fulfillment-open"' in portal
    assert "Print packing slip" in (ROOT / "backend/app/static/owner.html").read_text()
    assert "shopify-status" in portal
    assert '"/packing-slip"' not in wizard  # exact owner path is assembled
    assert "/packing-slip" in wizard
    assert "shippingLabelPurchase" not in wizard
    assert "Confirm dispatched" in (ROOT / "backend/app/static/owner.html").read_text()
    assert "innerHTML" not in wizard
    assert "buyer_shipping_address" not in wizard
    assert "printLabel.disabled = true" in wizard
    assert "confirm.disabled = true" in wizard


def test_owner_shipping_review_uses_real_checkout_and_does_not_guess_postage():
    wizard = (ROOT / "backend/app/static/owner-fulfill-wizard.js").read_text()
    assert "/shipping-cost" in wizard
    assert "OWNER_NET_POSTAGE_POLICY" in wizard
    assert "Net shipping charge" in wizard
    assert "Pending automatic charge" in wizard
    assert "No seller postage charge applies" in wizard
    assert "AUTO_CHARGE_VERIFIED" in wizard
    assert "NO_SELLER_CHARGE" in wizard
    for forbidden in ("Customer paid for shipping", "Actual postage charged",
                      "owner_allocated_shipping_minor", "buyer_shipping_retained_minor"):
        assert forbidden not in wizard
    assert "shippingLabelPurchase" not in wizard
    assert "innerHTML" not in wizard
    assert "printLabel.disabled = true" in wizard
    assert "confirm.disabled = true" in wizard
