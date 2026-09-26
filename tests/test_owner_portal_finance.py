from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "app" / "owner_portal_finance.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_owner_finance_router_is_registered_separately() -> None:
    main = MAIN.read_text()
    assert "from .owner_portal_finance import router as owner_portal_finance_router" in main
    assert "app.include_router(owner_portal_finance_router)" in main


def test_owner_finance_surface_is_read_only_and_owner_guarded() -> None:
    source = SOURCE.read_text()

    assert 'router = APIRouter(prefix="/api/v1/owner/finance"' in source
    assert source.count("Depends(require_owner_portal_request)") >= 4
    for mutation in ("@router.post(", "@router.put(", "@router.patch(", "@router.delete("):
        assert mutation not in source


def test_owner_finance_queries_are_explicitly_scoped_to_owner_id() -> None:
    source = SOURCE.read_text()

    assert source.count('owner_id = access["owner_id"]') >= 4
    assert source.count("where owner_id=$1") >= 4
    assert "where oi.owner_id=$1" in source


def test_owner_finance_exposes_transparent_deductions_and_proceeds() -> None:
    source = SOURCE.read_text()

    for field in (
        "sales_revenue_minor",
        "shipping_revenue_minor",
        "platform_fees_minor",
        "payment_fees_minor",
        "shipping_cost_minor",
        "fulfilment_material_cost_minor",
        "commission_minor",
        "refunds_minor",
        "shipping_refunds_minor",
        "lifetime_owner_proceeds_minor",
        "available_to_withdraw_minor",
        "paid_out_minor",
        "owner_proceeds_minor",
        "financials_complete",
        "unreconciled_sales",
    ):
        assert field in source


def test_owner_finance_never_exposes_founder_cost_or_company_profit_fields() -> None:
    source = SOURCE.read_text()

    forbidden = (
        "cost_basis_minor",
        "effective_cost_basis_minor",
        "acquisition_cost_minor",
        "gross_profit_minor",
        "net_profit_minor",
        "customer_email",
        "shipping_address",
        "billing_address",
        "stripe_account_id",
        "shopify_customer",
    )
    for field in forbidden:
        assert field not in source


def test_owner_sales_use_ledger_for_owner_proceeds_not_acquisition_cost() -> None:
    source = SOURCE.read_text()
    start = source.index('@router.get("/sales")')
    end = source.index('@router.get("/settlements")', start)
    sales = source[start:end]

    assert "coalesce(sum(le.amount_minor),0)::bigint as owner_proceeds_minor" in sales
    assert "commission_bps_snapshot" in sales
    assert "cost_basis_minor" not in sales


def test_owner_payout_history_excludes_internal_ids_notes_and_versions() -> None:
    source = SOURCE.read_text()
    start = source.index('@router.get("/payouts")')
    payouts = source[start:]

    for safe_field in (
        "payout_code",
        "amount_minor",
        "currency",
        "status",
        "request_origin",
        "scheduled_for",
        "requested_at",
        "resolved_at",
    ):
        assert safe_field in payouts

    for internal_field in ("notes", "version", "stripe_transfer_id", "last_error"):
        assert internal_field not in payouts
