from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "backend/app/owner_portal_api.py").read_text()
ITEM = (ROOT / "backend/app/static/owner-inventory.js").read_text()
HTML = (ROOT / "backend/app/static/owner.html").read_text()


def test_whatnot_readiness_is_not_false_company_shopify_install():
    # Sellers need Whatnot-approved owner-specific OAuth, not the native
    # Shopify Whatnot app on Drop Rate's company-owned single storefront.
    assert '"connection_status": "DEVELOPER_ACCESS_REQUIRED"' in API
    assert '"connection_mode": "SELLER_OAUTH"' in API
    assert '"developer_access_required": True' in API
    assert '"sync_enabled": False' in API

    assert 'code:"WHATNOT",label:"Whatnot"' in ITEM
    assert 'state:"Personal seller connection awaiting Whatnot API access"' in ITEM
    assert 'action:null' in ITEM
    assert 'https://apps.shopify.com/whatnot' not in ITEM
    assert 'https://apps.shopify.com/whatnot' not in HTML
    assert 'Personal seller connection' in ITEM
    assert 'Your own Whatnot account' in HTML
    assert 'seller-specific Whatnot connection' not in HTML or 'Whatnot' in HTML


def test_whatnot_pending_status_does_not_expose_secrets_or_fake_oauth():
    section = API.split('"code": "WHATNOT"', 1)[1].split('"states": [],', 1)[0]
    for phrase in ('"connected": False', '"available": False',
                   '"connection_mode": "SELLER_OAUTH"',
                   '"sync_enabled": False'):
        assert phrase in section
    for unsafe in ('oauth_client_secret', 'access_token', 'refresh_token',
                   'shopify_install_url', 'auth_code'):
        assert unsafe not in section
