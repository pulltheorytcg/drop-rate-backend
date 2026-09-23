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
    for view in ("dashboard", "inventory", "sales", "reports", "balance", "settings"):
        assert f'["{view}",' in js
    assert 'apiRequest("/api/v1/pricing/adapters")' in js
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
