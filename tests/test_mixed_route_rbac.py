from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"


def _source(name: str) -> str:
    return (APP / name).read_text()


def test_inventory_reads_remain_owner_scoped_but_mutations_are_admin_only() -> None:
    source = _source("api.py")

    for route in (
        '@router.get("/inventory/readiness")',
        '@router.get("/inventory/brands")',
        '@router.get("/inventory")',
    ):
        assert route in source

    for route in (
        '@router.patch("/inventory/{inventory_id}", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/inventory/{inventory_id}/approve", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/inventory/bulk-cost", dependencies=[Depends(require_platform_admin_request)])',
        '@router.get("/purchase-lots", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/purchase-lots", status_code=201, dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/purchase-lots/{lot_id}/allocate", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/automation/inventory-review", dependencies=[Depends(require_platform_admin_request)])',
    ):
        assert route in source


def test_owner_finance_reads_and_payout_requests_remain_owner_safe() -> None:
    source = _source("finance.py")

    for route in (
        '@router.get("/finance/summary")',
        '@router.get("/finance/sales")',
        '@router.get("/finance/sales-analytics")',
        '@router.get("/finance/settlements")',
        '@router.get("/finance/payouts")',
        '@router.post("/finance/payouts", status_code=201)',
        '@router.post("/finance/payouts/{payout_id}/cancel")',
    ):
        assert route in source


def test_finance_mutations_are_platform_admin_only() -> None:
    source = _source("finance.py")

    for fragment in (
        'reconcile-fees", dependencies=[Depends(require_platform_admin_request)]',
        'reconcile-pending-fees", dependencies=[Depends(require_platform_admin_request)]',
        '/fees", dependencies=[Depends(require_platform_admin_request)]',
        '/postage", dependencies=[Depends(require_platform_admin_request)]',
        'status_code=201, dependencies=[Depends(require_platform_admin_request)]',
    ):
        assert fragment in source


def test_refund_visibility_is_owner_scoped_but_creation_is_admin_only() -> None:
    source = _source("refunds.py")

    assert '@router.get("/finance/refunds")' in source
    assert (
        '@router.post("/finance/order-items/{order_item_id}/refunds", '
        'status_code=201, dependencies=[Depends(require_platform_admin_request)])'
    ) in source


def test_shopify_admin_controls_are_guarded_but_webhook_stays_external() -> None:
    source = _source("shopify.py")

    assert '@router.get("/status", dependencies=[Depends(require_platform_admin_request)])' in source
    assert '@router.post("/probe", dependencies=[Depends(require_platform_admin_request)])' in source
    assert '@router.post("/webhooks/register", dependencies=[Depends(require_platform_admin_request)])' in source
    assert '@router.post("/webhooks")\nasync def shopify_webhook' in source


def test_ebay_controls_are_guarded_but_provider_callbacks_remain_external() -> None:
    sales = _source("ebay_sales.py")
    oauth = _source("ebay_oauth.py")

    assert '@router.get("/seller-status", dependencies=[Depends(require_platform_admin_request)])' in sales
    assert '@router.post("/listings/{inventory_id}", dependencies=[Depends(require_platform_admin_request)])' in sales
    assert '@router.get("/order-notifications")\nasync def verify_ebay_order_notification_endpoint' in sales
    assert '@router.post("/order-notifications", status_code=204)\nasync def ebay_order_notification' in sales

    for route in (
        '@router.get("/status", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/start", dependencies=[Depends(require_platform_admin_request)])',
        '@router.get("/options", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/complete-setup", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/configuration", dependencies=[Depends(require_platform_admin_request)])',
    ):
        assert route in oauth

    assert '@router.get("/callback", response_class=HTMLResponse)\nasync def ebay_oauth_callback' in oauth
