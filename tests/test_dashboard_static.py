from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"
JS_ASSETS = (
    "app.js",
    "purchase-lots.js",
    "inventory-state.js",
    "purchase-lot-management.js",
    "storage-locations.js",
    "inventory-intake.js",
    "inventory-imports.js",
    "founder-finance.js",
    "dashboard-shell.js",
    "identity-review.js",
    "shopify-settings.js",
    "media-condition.js",
    "founder-workspace.js",
)


def test_dashboard_assets_exist() -> None:
    for name in ("index.html", "styles.css", *JS_ASSETS):
        path = STATIC / name
        assert path.is_file()
        assert path.stat().st_size > 100


def test_dashboard_has_auth_inventory_and_purchase_lot_controls() -> None:
    html = (STATIC / "index.html").read_text()
    for element_id in (
        "login-form",
        "request-reset-form",
        "new-password-form",
        "dashboard-view",
        "inventory-body",
        "editor-dialog",
        "bulk-dialog",
        "purchase-lot-dialog",
        "purchase-lot-form",
        "purchase-lots-list",
        "new-lot-button",
        "issue-buttons",
        "logout-button",
    ):
        assert f'id="{element_id}"' in html


def test_client_does_not_contain_privileged_credentials() -> None:
    combined = "\n".join(
        (STATIC / name).read_text()
        for name in ("index.html", "styles.css", *JS_ASSETS)
    )
    assert "service_role" not in combined
    assert "TCG_DATABASE_URL" not in combined
    assert "postgresql://" not in combined


def test_unknown_bulk_cost_is_not_forced_to_zero_in_purchase_lot_flow() -> None:
    js = (STATIC / "purchase-lots.js").read_text()
    assert 'placeholder = "Unknown"' in js
    assert 'row.querySelector("input").value = ""' in js


def test_manual_intake_only_requires_new_identity_fields_in_new_identity_mode() -> None:
    js = (STATIC / "inventory-intake.js").read_text()
    assert '["intake-game", "intake-name", "intake-set"]' in js
    assert "byId(id).required = intakeNewCatalogueMode" in js
    assert "byId(\"intake-card-number\").required = isCard && intakeNewCatalogueMode" in js


def test_dashboard_shell_has_expected_seller_views() -> None:
    js = (STATIC / "dashboard-shell.js").read_text()
    for view in ("dashboard", "inventory", "verification", "media", "sales", "reports", "balance", "settings"):
        assert f'["{view}",' in js
    assert 'apiRequest("/api/v1/market/status")' in js
    assert 'apiRequest("/api/v1/pricing/inventory?limit=8&offset=0")' in js
    assert "history.replaceState" in js


def test_dashboard_shell_preserves_working_component_ids() -> None:
    js = (STATIC / "dashboard-shell.js").read_text()
    for element_id in (
        "founder-finance-panel",
        "finance-sales-body",
        "finance-payouts-body",
        "finance-settlement-section",
        "storage-locations-section",
        "purchase-lots-list",
    ):
        assert element_id in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_dashboard_javascript_has_valid_syntax() -> None:
    for name in JS_ASSETS:
        subprocess.run(["node", "--check", str(STATIC / name)], check=True)


def test_dashboard_has_brand_filter_and_dynamic_brand_counts() -> None:
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()
    assert 'id="brand-filter"' in html
    assert "All brands / TCGs" in html
    assert "/api/v1/inventory/brands" in js
    assert 'params.set("brand", state.brand)' in js
    assert 'item.game !== item.brand' in js


def test_identity_verification_ui_is_audited_and_not_generic_editable() -> None:
    html = (STATIC / "index.html").read_text()
    app = (STATIC / "app.js").read_text()
    intake = (STATIC / "inventory-intake.js").read_text()
    review = (STATIC / "identity-review.js").read_text()
    storage = (STATIC / "storage-locations.js").read_text()

    assert "Identity verification is managed in the Verify tab" in html
    assert 'identity_confirmed: byId("edit-identity").checked' not in app
    assert 'identity_confirmed: byId("intake-identity-confirmed").checked' not in intake
    assert "/api/v1/identity-review/" in review
    assert "Select all unconfirmed" in review
    assert "storage_location_id" in review
    assert 'params.set("brand", state.brand)' in storage


def test_shopify_settings_ui_never_collects_server_credentials() -> None:
    js = (STATIC / "shopify-settings.js").read_text()
    assert "/api/v1/shopify/status" in js
    assert "/api/v1/shopify/webhooks/register" in js
    assert "Verify Shopify + Register webhooks" in js
    assert "LOCKED OFF" in js
    assert "TCG_SHOPIFY_ACCESS_TOKEN" not in js
    assert "TCG_SHOPIFY_CLIENT_SECRET" not in js
    assert "shpat_" not in js.casefold()
    assert 'type="password"' not in js.casefold()


def test_shopify_dashboard_exposes_only_guarded_single_item_test_sync() -> None:
    js = (STATIC / "shopify-settings.js").read_text()
    assert "/api/v1/shopify/test-sync" in js
    assert "Sync one test item" in js
    assert "Bulk publishing remains locked off" in js
    assert "shopify-test-candidate" in js
    assert "bulk-sync" not in js


def test_csp_allows_only_trusted_canonical_card_image_hosts() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()

    assert "https://assets.tcgdex.net" in main
    assert "https://onepiece-cardgame.com" in main
    assert "https://www.onepiece-cardgame.com" in main
    assert "https://*.onepiece-cardgame.com" in main
    assert "https://cdn.shopify.com" in main
    assert "https://*.shopifycdn.com" in main
    assert "https://*.shopifycdn.net" in main
    assert "img-src 'self' data: blob:" in main
    assert "img-src *" not in main


def test_inventory_defaults_to_visual_collectr_style_cards() -> None:
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()
    css = (STATIC / "styles.css").read_text()
    api = (ROOT / "backend" / "app" / "api.py").read_text()

    assert 'id="inventory-visual-grid"' in html
    assert 'id="inventory-view-visual"' in html
    assert 'id="inventory-view-table"' in html
    assert 'id="inventory-table-wrap" class="table-wrap hidden"' in html

    assert 'inventoryView: "visual"' in js
    assert "function inventoryVisualCard(item)" in js
    assert "function inventoryImageFigure(item)" in js
    assert "item.card_image_url" in js
    assert "item.card_image_direct_url" in js
    assert "item.card_image_cdn_url" in js
    assert "const directImageUrl = item.card_image_direct_url || item.card_image_cdn_url" in js
    assert "image.src = directImageUrl" in js
    assert 'image.addEventListener("error", loadFromProxy, { once: true })' in js
    assert "apiImageBlob(proxyPath)" in js
    assert "item.market_value_minor" in js
    assert "item.store_price_minor" in js
    assert "item.acquisition_cost_minor" in js
    assert "item.inventory_code" in js
    assert "item.rarity" in js
    assert "item.variant" in js
    assert "item.language || item.catalogue_language" in js

    assert ".inventory-visual-grid" in css
    assert ".inventory-visual-card" in css
    assert ".inventory-card-art img" in css

    assert "card_image_url" in api
    assert "card_image_shopify_cdn_url" in api
    assert "card_image_public_source_url" in api
    assert '"card_image_direct_url"' in api
    assert '"card_image_cdn_url"' in api
    assert "_inventory_image_direct_browser_allowed" in api
    assert "card_image_approval_status" in api
    assert "ma.approval_status in ('PENDING','APPROVED')" in api
    assert "case when ma.scope='INVENTORY_ITEM' then 0 else 1 end" in api


def test_pending_images_are_visible_internally_but_rejected_images_are_not() -> None:
    api = (ROOT / "backend" / "app" / "api.py").read_text()
    assert "ma.approval_status in ('PENDING','APPROVED')" in api
    assert "ma.approval_status in ('PENDING','APPROVED','REJECTED')" not in api
    assert "ma.source_status='ACTIVE'" in api
    assert "ma.rights_status='VERIFIED'" in api


def test_workspace_search_and_clear_filters_include_personal_collection() -> None:
    workspace = (STATIC / "founder-workspace.js").read_text()
    assert "state.saleIntent" in workspace
    assert '"sale-intent-filter"' in workspace
    assert (
        'state.saleIntent && byId("sale-intent-filter").selectedOptions[0]?.textContent'
        in workspace
    )
    assert (
        "state.search = state.brand = state.status = state.saleIntent = state.issue ="
        in workspace
    )
