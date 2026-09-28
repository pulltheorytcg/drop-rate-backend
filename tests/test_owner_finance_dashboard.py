from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "backend" / "app" / "static" / "owner.html"
JS = ROOT / "backend" / "app" / "static" / "owner-portal.js"


def test_owner_portal_has_separate_inventory_sales_balance_and_settlement_views() -> None:
    html = HTML.read_text()

    for view in ("inventory", "sales", "balance", "settlements"):
        assert f'data-owner-view="{view}"' in html
        assert f'data-owner-view-panel="{view}"' in html

    assert ">Payouts</span>" in html
    assert "Order-by-order allocation" in html


def test_owner_finance_ui_uses_only_owner_safe_finance_endpoints() -> None:
    js = JS.read_text()

    for path in (
        "/api/v1/owner/finance/summary",
        "/api/v1/owner/finance/sales?",
        "/api/v1/owner/finance/settlements?",
        "/api/v1/owner/finance/payouts",
    ):
        assert path in js

    for founder_path in (
        "/api/v1/finance/summary",
        "/api/v1/finance/sales",
        "/api/v1/finance/settlements",
        "/api/v1/finance/payouts",
        "/api/v1/stripe/payouts/queue",
    ):
        assert founder_path not in js


def test_owner_finance_ui_exposes_transparency_without_internal_profit_or_cost() -> None:
    html = HTML.read_text()

    for visible in (
        "Sales revenue",
        "Commission",
        "Owner proceeds",
        "Available to withdraw",
        "Pending",
        "Reserved payouts",
        "Paid out",
        "Your proceeds",
        "Other deductions",
        "Reconciled",
    ):
        assert visible in html

    for forbidden in (
        "Acquisition cost",
        "Cost basis",
        "Gross profit",
        "Net profit",
        "Internal notes",
        "Payment policy",
        "Platform admin",
    ):
        assert forbidden not in html


def test_owner_payout_schedule_is_only_business_mutation_in_finance_dashboard() -> None:
    js = JS.read_text()

    assert 'apiRequest("/api/v1/payout-preferences", {' in js
    assert 'method: "PUT"' in js
    assert "Save payout schedule" in HTML.read_text()

    # No seller-side manual sale/refund, reconciliation, payout approval or provider changes.
    for forbidden in (
        "manual-sales",
        "reconcile-fees",
        "reconcile-pending-fees",
        "/refunds",
        "/approve",
        "/reject",
        "/webhooks/register",
        "/ebay/oauth/configuration",
    ):
        assert forbidden not in js


def test_owner_portal_does_not_reference_removed_owner_type_element() -> None:
    js = JS.read_text()
    html = HTML.read_text()

    assert 'byId("owner-portal-type")' not in js
    assert 'id="owner-portal-type"' not in html


def test_owner_finance_incomplete_reconciliation_is_visible_not_silently_final() -> None:
    js = JS.read_text()

    assert 'data.financials_complete ? "COMPLETE"' in js
    assert 'item.financials_complete ? "Complete" : "Reconciling"' in js


def test_owner_portal_payout_preference_matches_supported_cadences() -> None:
    html = HTML.read_text()

    for cadence in ("MANUAL", "DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"):
        assert f'value="{cadence}"' in html
