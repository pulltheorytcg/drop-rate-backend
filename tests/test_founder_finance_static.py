from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"


def test_founder_finance_asset_exists() -> None:
    path = STATIC / "founder-finance.js"
    assert path.is_file()
    assert path.stat().st_size > 1000


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_founder_finance_javascript_has_valid_syntax() -> None:
    subprocess.run(["node", "--check", str(STATIC / "founder-finance.js")], check=True)


def test_finance_sales_ui_labels_pending_costs_and_provisional_profit() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    css = (STATIC / "styles.css").read_text()
    assert "Fees + postage" in js
    assert '"Pending"' in js
    assert "Provisional" in js
    assert "shipping paid" in js
    assert "finance-item-meta" in js
    assert "finance-item-code" in js
    assert "finance-money-cell" in css
    assert "Founder finance sales table" in css


def test_finance_reconciliation_controls_are_available_for_shopify_sales() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    css = (STATIC / "styles.css").read_text()
    assert "Sync fees" in js
    assert "Set postage" in js
    assert "reconcileShopifyFees" in js
    assert "reconcileShopifyPostage" in js
    assert "/reconcile-fees" in js
    assert "/postage" in js
    assert "financeNonnegativeMinorFromInput" in js
    assert ".finance-reconcile-actions" in css


def test_owner_settlement_report_is_rendered_in_reports_ui() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    shell = (STATIC / "dashboard-shell.js").read_text()
    assert "Settlement report" in js
    assert "Net owner proceeds" in js
    assert "Owner profit" in js
    assert "/api/v1/finance/settlements?limit=50&offset=0" in js
    assert "renderFinanceSettlements" in js
    assert 'byId("finance-settlement-section")' in shell
    assert "reports.append(settlementSection)" in shell


def test_main_serves_finance_asset_and_router() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    assert 'from .finance import router as finance_router' in main
    assert 'founder-finance.js' in main
    assert 'app.include_router(finance_router)' in main
