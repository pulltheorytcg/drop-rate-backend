from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "backend" / "app" / "static"
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
    assert '<script src="/assets/owner-portal.js?v=owner-v8" defer></script>' in html
    assert '<script src="/assets/owner-recognition.js?v=owner-v8" defer></script>' in html

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
    start = html.index('data-owner-view-panel="inventory"')
    end = html.index('data-owner-view-panel="sales"', start)
    inventory = html[start:end]

    for label in (
        "Acquisition cost",
        "Storage location",
        "Purchase lot",
        "Internal notes",
        "Shopify Product ID",
        'type="button">Approve',
        'type="button">Edit cost',
        'type="button">Reassign owner',
    ):
        assert label not in inventory

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
    assert "Your Seller Hub is ready." in html
    assert "Set up payouts" in html
    assert 'activateOwnerView("balance")' in js
    assert 'byId("owner-stripe-connect-panel")' in js
    assert 'history.replaceState({}, document.title, "/owner")' in js


def test_owner_portal_v2_isolated_design_system_and_responsive_navigation() -> None:
    html = HTML.read_text()
    css = CSS.read_text()
    js = JS.read_text()

    assert 'href="/assets/owner-portal.css?v=owner-v11"' in html
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
    assert "grid-template-columns:repeat(7,1fr)" in css


def test_owner_scan_requires_confirmation_before_intake() -> None:
    js = RECOGNITION_JS.read_text()

    feedback_call = "apiRequest(`/api/v1/recognition/runs/${run.id}/feedback`"
    intake_call = 'apiRequest("/api/v1/owner/recognition-intake"'
    assert feedback_call in js
    assert intake_call in js
    assert js.index(feedback_call) < js.index(intake_call)
    assert '"CONFIRMED_TOP"' in js
    assert '"CORRECTED_TO_CANDIDATE"' in js


def test_mobile_batch_scanner_is_camera_first_and_locally_gated() -> None:
    html = HTML.read_text()
    js = RECOGNITION_JS.read_text()
    css = CSS.read_text()

    for element_id in (
        "owner-batch-camera-state",
        "owner-batch-count",
        "owner-batch-total",
        "owner-batch-unresolved",
        "owner-batch-strip",
        "owner-batch-review-button",
        "owner-batch-review-list",
        "owner-batch-search-input",
        "owner-batch-search-results",
    ):
        assert f'id="{element_id}"' in html

    assert "ownerBatchFrameFingerprint" in js
    assert "ownerBatchFingerprintDelta" in js
    assert "stableFrames >= 3" in js
    assert "changed >= 0.11" in js
    assert "window.setInterval(ownerBatchTick, 420)" in js
    assert "MediaRecorder" not in js
    assert "RTCPeerConnection" not in js
    assert "getUserMedia" in js
    assert "force_refresh: true" in js

    assert ".owner-portal-page .owner-batch-sheet" in css
    assert ".owner-portal-page.owner-batch-camera-open" in css
    assert "position:fixed;inset:0;z-index:1000" in css
    assert "height:100dvh" in css


def test_mobile_batch_scanner_keeps_unresolved_cards_and_supports_search_correction() -> None:
    js = RECOGNITION_JS.read_text()

    assert 'status: autoRecognised ? "recognised" : "unresolved"' in js
    assert 'outcome: "CORRECTED_BY_SEARCH"' in js
    assert "/api/v1/owner/catalogue-search" in js
    assert "ownerBatchOpenCorrection" in js
    assert "ownerBatchUnresolvedCount" in js
    assert "ownerBatchReferenceTotal" in js
    assert "Fix match" in js
    assert 'headers: {"Idempotency-Key": item.intakeKey}' in js
    assert 'item.status = "added"' in js


def test_mobile_batch_scan_only_commits_confirmed_items_as_draft_inventory() -> None:
    js = RECOGNITION_JS.read_text()

    feedback_index = js.index("await ownerBatchEnsureFeedback(item)")
    intake_index = js.index('apiRequest("/api/v1/owner/recognition-intake"', feedback_index)
    assert feedback_index < intake_index
    assert 'selected_catalogue_id: item.selected.catalogue_id' in js
    assert "ownerBatchUnresolvedCount()" in js


def test_mobile_batch_scanner_has_manual_capture_fallback() -> None:
    html = HTML.read_text()
    js = RECOGNITION_JS.read_text()
    css = CSS.read_text()

    assert 'id="owner-batch-capture-now"' in html
    assert "Capture now" in html
    assert "Use this if auto-scan has not fired" in html
    assert "async function ownerBatchCaptureNow()" in js
    assert 'byId("owner-batch-capture-now").addEventListener("click", ownerBatchCaptureNow)' in js
    assert "ownerBatchCaptureDataUrl(video)" in js
    assert "await ownerBatchRecognise(dataUrl)" in js
    assert 'ownerBatchSetCameraState("Auto-scan on · tap Capture now any time")' in js
    assert ".owner-portal-page .owner-batch-capture-now{display:none}" in css
    assert "display:grid;grid-template-columns:auto auto 1fr" in css


def test_mobile_scanner_v2_keeps_latest_match_in_camera_flow() -> None:
    html = HTML.read_text()
    js = RECOGNITION_JS.read_text()
    css = CSS.read_text()

    for element_id in (
        "owner-batch-latest",
        "owner-batch-latest-thumb",
        "owner-batch-latest-status",
        "owner-batch-latest-name",
        "owner-batch-latest-meta",
        "owner-batch-latest-value",
        "owner-batch-latest-fix",
        "owner-batch-latest-remove",
    ):
        assert f'id="{element_id}"' in html

    assert "function ownerBatchRenderLatest()" in js
    assert "ownerBatchSelectedName(item)" in js
    assert "ownerBatchSelectedMeta(item)" in js
    assert "ownerBatchFormatValue(ownerBatchMarketValue(item))" in js
    assert "ownerBatchRenderLatest();" in js
    assert ".owner-portal-page .owner-batch-latest" in css
    assert ".owner-batch-latest-status.unresolved" in css


def test_mobile_scanner_v2_suppresses_only_immediate_auto_duplicates() -> None:
    js = RECOGNITION_JS.read_text()

    assert "function ownerBatchShouldSuppressAutoCapture(fingerprint)" in js
    assert "Date.now() - batch.lastAutoCaptureAt > 1800" in js
    assert "ownerBatchFingerprintDelta(fingerprint, batch.lastAutoCaptureFingerprint) < 0.012" in js
    assert "ownerBatchShouldSuppressAutoCapture(fingerprint)" in js
    assert 'ownerBatchSetCameraState("Same card just scanned · move to the next card")' in js
    assert "batch.lastAutoCaptureAt = Date.now();" in js


def test_mobile_scanner_v2_pauses_auto_scan_during_match_correction() -> None:
    js = RECOGNITION_JS.read_text()

    open_start = js.index("function ownerBatchOpenCorrection")
    search_start = js.index("function ownerBatchSearchResultCard", open_start)
    open_block = js[open_start:search_start]
    close_start = js.index("function ownerBatchCloseCorrection")
    open_start = js.index("function ownerBatchOpenCorrection", close_start)
    close_block = js[close_start:open_start]

    assert "batch.paused = true" in open_block
    assert "batch.stableFrames = 0" in open_block
    assert "batch.paused = false" in close_block
    assert "batch.previousFingerprint = null" in close_block


def test_mobile_scanner_v2_can_fix_or_remove_latest_match_without_leaving_camera() -> None:
    js = RECOGNITION_JS.read_text()

    assert 'byId("owner-batch-latest-fix").addEventListener("click"' in js
    assert 'byId("owner-batch-latest-remove").addEventListener("click"' in js
    assert "ownerBatchOpenCorrection(item.id)" in js
    assert "ownerBatchRemoveItem(item.id)" in js
    assert "function ownerBatchRemoveItem(itemId)" in js
    assert "batch.latestResultId = batch.items[batch.items.length - 1]?.id || null" in js


def test_seller_hub_branding_is_neutral_and_not_founder_hq() -> None:
    html = HTML.read_text()
    css = CSS.read_text()

    assert "<title>Drop Rate — Seller Hub</title>" in html
    assert "Drop Rate Seller Hub" in html
    assert "Private workspace" not in html
    assert "Seller account" in html
    assert 'https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-seller-hub-approved.png?v=1790808031' in html
    assert 'drop-rate-logo.png?v=seller-hub-1' not in css
    assert 'drop-rate-founder-hq.png' not in css
    assert 'content:"SELLER HUB"' in css

    assert 'https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-seller-hub-approved.png?v=1790808031' in html
    assert '/assets/brand-assets/drop-rate-seller-hub.png' not in html


def test_seller_channels_empty_state_cannot_throw_null_replacechildren() -> None:
    js = JS.read_text()

    start = js.index("function renderOwnerChannelsRows")
    end = js.index("function renderOwnerChannelsPagination", start)
    block = js[start:end]
    helper_start = js.index("function renderEmptyRow")
    helper_end = js.index("\nasync function", helper_start)
    helper = js[helper_start:helper_end]

    assert 'renderEmptyRow("owner-channels-body", 6' in block
    assert "renderEmptyRow(body, 6" not in block
    assert 'typeof bodyId === "string" ? byId(bodyId) : bodyId' in helper
    assert "if (!body) return;" in helper


def test_seller_topbar_brand_is_single_polished_lockup() -> None:
    html = HTML.read_text()
    css = CSS.read_text()

    assert 'class="dr-logo-image owner-topbar-logo"' in html
    assert 'src="https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-seller-hub-approved.png?v=1790808031"' in html
    assert 'alt="Drop Rate Seller Hub"' in html
    assert 'class="owner-topbar-divider"' not in html
    assert 'class="owner-topbar-product"' not in html
    assert "<small>DROP RATE</small>" not in html
    assert "<em>Inventory · Sales · Payouts</em>" not in html
    assert ".owner-portal-page .owner-topbar-logo" in css
    assert "width:220px!important" in css
    assert "width:136px!important" in css
    assert "left:50%" in css
    assert "transform:translateX(-50%)" in css
    assert ".owner-topbar-divider" not in css
    assert ".owner-topbar-product" not in css


def test_owner_portal_uses_integrated_seller_hub_brand_lockup() -> None:
    html = HTML.read_text()
    css = CSS.read_text()
    assert 'src="https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-seller-hub-approved.png?v=1790808031"' in html
    assert 'alt="Drop Rate Seller Hub"' in html
    assert 'class="dr-logo-image owner-topbar-logo"' in html
    assert "object-fit:contain" in css
    assert "background:none!important" in css
    assert "width:254px!important" in css
    assert 'https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-seller-hub-approved.png?v=1790808031' in html
