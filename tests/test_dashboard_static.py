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
    for view in ("dashboard", "inventory", "verification", "sales", "reports", "balance", "settings"):
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
