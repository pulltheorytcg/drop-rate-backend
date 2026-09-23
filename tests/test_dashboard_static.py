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
    "dashboard-navigation.js",
)


def test_dashboard_assets_exist() -> None:
    for name in ("index.html", "styles.css", "portal.css", *JS_ASSETS):
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
        for name in ("index.html", "styles.css", "portal.css", *JS_ASSETS)
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


def test_founder_portal_has_expected_views_and_hash_navigation() -> None:
    js = (STATIC / "dashboard-navigation.js").read_text()
    for view in ("dashboard", "inventory", "sales", "reports", "balance", "settings"):
        assert f'"{view}"' in js
        assert f"portal-${{name}}-view" in js or "portal-${name}-view" in js
    assert "hashchange" in js
    assert "showPortalView" in js
    assert "finance-overview-section" in js
    assert "finance-sales-section" in js
    assert "finance-reports-section" in js
    assert "finance-balance-section" in js
    assert "storage-locations-section" in js


def test_finance_module_exposes_sales_refunds_reports_and_balance_sections() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    for element_id in (
        "finance-overview-section",
        "finance-sales-section",
        "finance-refunds-section",
        "finance-reports-section",
        "finance-balance-section",
        "finance-refund-dialog",
        "finance-payout-dialog",
    ):
        assert f'id="{element_id}"' in js
    assert "/api/v1/finance/refunds" in js
    assert "/refunds`" in js
    assert "return_to_stock" in js


def test_portal_assets_are_injected_after_feature_modules() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    intake = main.index('inventory-intake.js')
    imports = main.index('inventory-imports.js')
    finance = main.index('founder-finance.js')
    navigation = main.index('dashboard-navigation.js')
    assert intake < imports < finance < navigation
    assert 'portal.css' in main


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_dashboard_javascript_has_valid_syntax() -> None:
    for name in JS_ASSETS:
        subprocess.run(["node", "--check", str(STATIC / name)], check=True)
