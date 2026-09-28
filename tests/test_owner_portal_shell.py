from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
HTML = ROOT / "backend" / "app" / "static" / "owner.html"
JS = ROOT / "backend" / "app" / "static" / "owner-portal.js"
CSS = ROOT / "backend" / "app" / "static" / "owner-portal.css"
RECOGNITION_JS = ROOT / "backend" / "app" / "static" / "owner-recognition.js"


def test_owner_portal_is_served_separately_from_founder_hq() -> None:
    main = MAIN.read_text()
    html = HTML.read_text()

    assert '@app.get("/owner", include_in_schema=False)' in main
    assert 'STATIC_DIR / "owner.html"' in main
    assert '<script src="/assets/owner-portal.js?v=owner-v3" defer></script>' in html
    assert '<script src="/assets/owner-recognition.js?v=owner-v3" defer></script>' in html

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


def test_owner_portal_uses_only_dedicated_owner_safe_read_contracts() -> None:
    html = HTML.read_text()
    js = JS.read_text()

    assert "Inventory" in html
    assert "/api/v1/owner/overview" in js
    assert "/api/v1/owner/inventory" in js
    assert "/api/v1/inventory" not in js
    assert "/api/v1/finance/" not in js

    assert 'apiRequest("/api/v1/owner/overview")' in js
    assert 'apiRequest(`/api/v1/owner/inventory?${params.toString()}`)' in js
    assert '/api/v1/owner/overview", {' not in js
    assert '/api/v1/owner/inventory?", {' not in js


def test_owner_inventory_ui_does_not_expose_internal_fields_or_actions() -> None:
    html = HTML.read_text()

    for label in (
        "Acquisition cost",
        "Storage location",
        "Purchase lot",
        "Internal notes",
        "Shopify Product ID",
        "eBay",
        'type="button">Approve',
        'type="button">Edit cost',
        'type="button">Reassign owner',
    ):
        assert label not in html

    for required in (
        "Total inventory",
        "Active market value",
        "Store / recommended value",
        "Sold",
        "Market value",
        "Recommended retail",
    ):
        assert required in html


def test_new_owner_onboarding_redirect_has_a_guided_welcome_checklist() -> None:
    html = HTML.read_text()
    js = JS.read_text()

    assert 'params.get("welcome") !== "1"' in js
    assert 'id="owner-onboarding-welcome"' in html
    assert "You're all set." in html
    assert "Set up payouts" in html
    assert 'activateOwnerView("balance")' in js
    assert 'byId("owner-stripe-connect-panel")' in js
    assert 'history.replaceState({}, document.title, "/owner")' in js


def test_owner_portal_v2_isolated_design_system_and_responsive_navigation() -> None:
    html = HTML.read_text()
    css = CSS.read_text()
    js = JS.read_text()

    assert 'href="/assets/owner-portal.css?v=owner-v2"' in html
    assert 'class="owner-portal-page"' in html
    assert 'data-owner-view="overview"' in html
    assert 'class="owner-sidebar"' in html
    assert 'id="owner-inventory-grid"' in html
    assert 'data-owner-inventory-layout="grid"' in html
    assert 'data-owner-inventory-layout="list"' in html
    assert ".owner-portal-page .owner-sidebar" in css
    assert "@media(max-width:900px)" in css
    assert "bottom:0" in css
    assert "renderInventoryCards(items)" in js
    assert "renderOverviewLatestInventory(items)" in js
    assert 'addEventListener("input"' in js


def test_owner_portal_scan_workspace_uses_shared_recognition_safely() -> None:
    html = HTML.read_text()
    js = RECOGNITION_JS.read_text()
    css = CSS.read_text()

    assert 'data-owner-view="scan"' in html
    assert 'data-owner-view-panel="scan"' in html
    assert 'id="owner-scan-file"' in html
    assert 'capture="environment"' in html
    assert 'id="owner-scan-video"' in html
    assert "Scan & add a card" in html

    for path in (
        "/api/v1/recognition/status",
        "/api/v1/recognition/resolve",
        "/api/v1/recognition/runs/",
        "/api/v1/owner/recognition-intake",
    ):
        assert path in js

    assert "/api/v1/inventory/intake" not in js
    assert "/api/v1/pricing" not in js
    assert "/api/v1/shopify" not in js
    assert "/api/v1/storage-locations" not in js
    assert 'headers: {"Idempotency-Key": state.ownerRecognition.intakeKey}' in js
    assert "crypto.randomUUID()" in js
    assert ".owner-scan-camera-viewport" in css
    assert "grid-template-columns:repeat(6,1fr)" in css


def test_owner_scan_requires_confirmation_before_intake() -> None:
    js = RECOGNITION_JS.read_text()

    feedback_call = "apiRequest(`/api/v1/recognition/runs/${run.id}/feedback`"
    intake_call = 'apiRequest("/api/v1/owner/recognition-intake"'
    assert feedback_call in js
    assert intake_call in js
    assert js.index(feedback_call) < js.index(intake_call)
    assert '"CONFIRMED_TOP"' in js
    assert '"CORRECTED_TO_CANDIDATE"' in js
