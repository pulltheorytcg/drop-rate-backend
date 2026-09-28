from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "owner_portal_api.py"
FINANCE = ROOT / "backend" / "app" / "owner_portal_finance.py"
HTML = ROOT / "backend" / "app" / "static" / "owner.html"
JS = ROOT / "backend" / "app" / "static" / "owner-portal.js"
CSS = ROOT / "backend" / "app" / "static" / "owner-portal.css"


def _route(source: str, marker: str, next_marker: str | None = None) -> str:
    start = source.index(marker)
    if next_marker is None:
        return source[start:]
    end = source.index(next_marker, start)
    return source[start:end]


def test_next_payout_tracker_prefers_real_scheduled_request_then_estimates_cleared_balance() -> None:
    source = FINANCE.read_text()
    summary = _route(source, '@router.get("/summary")', '@router.get("/sales")')

    assert "from .payout_preferences import next_scheduled_at" in source
    assert "where owner_id=$1" in summary
    assert "status in ('REQUESTED','APPROVED')" in summary
    assert "scheduled_for >= clock_timestamp()" in summary
    assert "next_scheduled_at(" in summary
    assert '"amount_basis": "SCHEDULED_REQUEST"' in summary
    assert '"amount_basis": "CURRENT_AVAILABLE_BALANCE"' in summary
    assert 'int(balances["available_to_withdraw_minor"])' in summary
    assert '"next_payout": next_payout' in summary


def test_owner_insights_are_owner_scoped_and_use_real_pricing_history() -> None:
    source = API.read_text()
    block = _route(source, '@router.get("/insights")', '@router.get("/channels")')

    assert 'owner_id = access["owner_id"]' in block
    assert "i.owner_id=$1" in block
    assert "ps.owner_id=$1" in block
    assert "tcg.pricing_snapshots" in block
    assert "latest.current_at - interval '6 days'" in block
    assert "latest.current_at - interval '14 days'" in block
    assert "baseline.market_value_minor > 0" in block
    assert "limit 6" in block
    assert '"weekly_window_days": 7' in block

    for forbidden in (
        "acquisition_cost_minor",
        "storage_location_id",
        "purchase_lot_id",
        "notes",
        "created_by_user_id",
    ):
        assert forbidden not in block


def test_owner_insights_media_is_rights_cleared() -> None:
    source = API.read_text()
    block = _route(source, '@router.get("/insights")', '@router.get("/channels")')

    for requirement in (
        "m.approval_status='APPROVED'",
        "m.rights_status='VERIFIED'",
        "m.rights_tier='STOREFRONT_ALLOWED'",
        "m.source_status='ACTIVE'",
        "m.revoked_at is null",
    ):
        assert block.count(requirement) >= 2


def test_channels_api_is_owner_scoped_and_never_returns_ebay_credentials() -> None:
    source = API.read_text()
    block = _route(source, '@router.get("/channels")', '@router.get("/catalogue-search")')

    assert 'owner_id = access["owner_id"]' in block
    assert 'filters = ["i.owner_id=$1"]' in block
    assert block.count("where owner_id=$1") >= 3
    assert block.count("l.owner_id=$1 and l.inventory_id=i.id") >= 4
    assert "where {where}" in block
    assert "where ${where}" not in block
    assert "limit {len(page_params)-1} offset {len(page_params)}" in block
    assert '"source_of_truth": "DROP_RATE"' in block

    for forbidden in (
        "refresh_token_ciphertext",
        "granted_scopes",
        "payment_policy_id",
        "fulfillment_policy_id",
        "return_policy_id",
        "merchant_location_key",
        "notification_destination_id",
        "notification_subscription_id",
        "acquisition_cost_minor",
        "storage_location_id",
        "purchase_lot_id",
    ):
        assert forbidden not in block


def test_channels_api_keeps_whatnot_as_adapter_ready_not_fake_connected_state() -> None:
    block = _route(
        API.read_text(),
        '@router.get("/channels")',
        '@router.get("/catalogue-search")',
    )

    assert '"code": "SHOPIFY"' in block
    assert '"code": "EBAY"' in block
    assert '"code": "WHATNOT"' in block
    assert '"available": False' in block
    assert '"connection_status": "PLANNED"' in block


def test_owner_dashboard_renders_payout_top_cards_movers_and_channels() -> None:
    html = HTML.read_text()
    js = JS.read_text()
    css = CSS.read_text()

    for element_id in (
        "owner-next-payout-date",
        "owner-next-payout-amount",
        "owner-top-valued-cards",
        "owner-weekly-movers",
        "owner-channel-shopify-status",
        "owner-channel-ebay-status",
        "owner-channels-body",
        "owner-channels-search",
        "owner-channels-filter",
    ):
        assert f'id="{element_id}"' in html

    assert 'data-owner-view="channels"' in html
    assert 'data-owner-view-panel="channels"' in html
    assert 'apiRequest("/api/v1/owner/insights")' in js
    assert 'apiRequest("/api/v1/owner/channels?" + params.toString())' in js
    assert "renderOwnerPayoutTracker(data)" in js
    assert "owner-movement" in js
    assert ".owner-payout-tracker" in css
    assert ".owner-insights-grid" in css
    assert ".owner-channel-grid" in css
    assert "grid-template-columns:repeat(7,1fr)" in css


def test_channel_manager_does_not_call_provider_control_planes_directly() -> None:
    js = JS.read_text()

    assert "/api/v1/owner/channels" in js
    assert "/api/v1/shopify" not in js
    assert "/api/v1/ebay" not in js
    assert "refresh_token" not in js
