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
    assert "finance-pending-costs" in js
    assert "Awaiting" in js
    assert "finance-item-meta" in js
    assert "finance-item-code" in js
    assert "finance-money-cell" in css
    assert ".finance-sale-row .finance-pending-costs" in css
    assert "#founder-finance-panel .finance-pending-costs" not in css
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
    assert "Adjustments" in js
    assert "/api/v1/finance/settlements?limit=50&offset=0" in js
    assert "renderFinanceSettlements" in js
    assert 'byId("finance-settlement-section")' in shell
    assert "reports.append(settlementSection)" in shell


def test_main_serves_finance_asset_and_router() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    assert 'from .finance import router as finance_router' in main
    assert 'founder-finance.js' in main
    assert 'app.include_router(finance_router)' in main


def test_sales_dashboard_supports_period_presets_custom_dates_and_backend_analytics() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    css = (STATIC / "styles.css").read_text()
    shell = (STATIC / "dashboard-shell.js").read_text()

    for label in (
        "Total sales",
        "Net revenue",
        "Net profit",
        "Orders",
        "Items sold",
        "All time",
        "Today",
        "Yesterday",
        "Last 7 days",
        "This week",
        "This month",
        "This quarter",
        "This year",
        "Custom dates",
    ):
        assert label in js
    assert "/api/v1/finance/sales-analytics" in js
    assert "start_date" in js
    assert "end_date" in js
    assert "Europe/London" in js
    assert "renderFinanceSalesChart" in js
    assert "gross AOV" in js
    assert "sales-chart single-point" not in js
    assert 'classList.toggle("single-point", series.length === 1)' in js
    assert "aria-label" in js
    assert "financeSalesRange" in js
    assert "salesDashboard" in shell
    assert "sales.append(salesDashboard)" in shell
    assert ".sales-kpi-grid" in css
    assert ".sales-chart" in css
    assert ".sales-chart.single-point" in css


def test_media_page_refresh_and_evidence_registry_are_compact_and_aligned() -> None:
    media = (STATIC / "media-condition.js").read_text()
    shopify = (STATIC / "shopify-settings.js").read_text()
    css = (STATIC / "styles.css").read_text()

    assert 'class="media-refresh-button"' in media
    assert 'aria-label="Refresh media and condition"' in media
    assert "media-evidence-row" in shopify
    assert "media-evidence-states" in shopify
    assert "media-evidence-context" in shopify
    assert ".media-evidence-row" in css
    assert ".media-refresh-button" in css

def test_stripe_connect_controls_are_visible_in_balance_view() -> None:
    shell = (STATIC / "dashboard-shell.js").read_text()
    finance = (STATIC / "founder-finance.js").read_text()

    assert 'byId("stripe-payout-account")' in shell
    assert "balance.append(stripePayoutAccount)" in shell
    assert 'byId("stripe-payout-queue-section")' in shell
    assert "balance.append(stripePayoutQueue)" in shell
    assert 'id="stripe-payout-account"' in finance
    assert 'id="stripe-payout-queue-section"' in finance
    assert "Set up payouts" in finance
    assert "Continue Stripe onboarding" in finance

def test_owner_can_choose_payout_frequency_in_balance_ui() -> None:
    js = (STATIC / "founder-finance.js").read_text()
    main = (ROOT / "backend" / "app" / "main.py").read_text()

    for label in ("Manual", "Daily", "Weekly", "Every 2 weeks", "Monthly"):
        assert label in js
    assert 'id="payout-preference-cadence"' in js
    assert 'id="payout-preference-weekday"' in js
    assert 'id="payout-preference-monthly-day"' in js
    assert "/api/v1/payout-preferences" in js
    assert "Next scheduled payout" in js
    assert "not guaranteed next-day bank arrival" in js
    assert "payout_preferences_router" in main

