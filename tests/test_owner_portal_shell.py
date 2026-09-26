from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
HTML = ROOT / "backend" / "app" / "static" / "owner.html"
JS = ROOT / "backend" / "app" / "static" / "owner-portal.js"


def test_owner_portal_is_served_separately_from_founder_hq() -> None:
    main = MAIN.read_text()
    html = HTML.read_text()

    assert '@app.get("/owner", include_in_schema=False)' in main
    assert 'STATIC_DIR / "owner.html"' in main
    assert '<script src="/assets/owner-portal.js" defer></script>' in html

    for founder_script in (
        "dashboard-shell.js",
        "founder-finance.js",
        "inventory-imports.js",
        "shopify-settings.js",
        "identity-review.js",
    ):
        assert founder_script not in html


def test_owner_portal_requires_owner_role_and_redirects_platform_admin() -> None:
    js = JS.read_text()

    assert 'apiRequest("/api/v1/access/me")' in js
    assert 'access.access_role === "PLATFORM_ADMIN"' in js
    assert 'window.location.replace("/")' in js
    assert 'access.access_role !== "OWNER"' in js
    assert 'access.portal !== "OWNER_PORTAL"' in js
    assert "OWNER_PORTAL_ACCESS_DENIED" in js


def test_owner_portal_supports_enabled_google_and_apple_identity_providers() -> None:
    html = HTML.read_text()
    js = JS.read_text()

    assert 'id="owner-google"' in html
    assert 'id="owner-apple"' in html
    assert 'authRequest("/settings")' in js
    assert "external.google" in js
    assert "external.apple" in js
    assert '/auth/v1/authorize' in js
    assert 'authorizeUrl.searchParams.set("redirect_to", `${window.location.origin}/owner`)' in js


def test_owner_portal_has_no_privileged_control_plane_calls() -> None:
    js = JS.read_text()

    forbidden = (
        "/api/v1/shopify",
        "/api/v1/ebay",
        "/api/v1/pricing",
        "/api/v1/market",
        "/api/v1/identity-review",
        "/api/v1/condition-review",
        "/api/v1/purchase-lots",
        "/api/v1/storage-locations",
        "/api/v1/stripe/payouts/queue",
    )
    for path in forbidden:
        assert path not in js


def test_owner_portal_is_access_only_until_owner_safe_contracts_are_verified() -> None:
    html = HTML.read_text()
    js = JS.read_text()

    assert "Portal foundation" in html
    assert "owner-safe API contracts pass isolation tests" in html
    assert "/api/v1/inventory" not in js
    assert "/api/v1/finance/" not in js
