from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "app" / "owner_portal_api.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_owner_safe_router_is_registered_separately() -> None:
    main = MAIN.read_text()

    assert "from .owner_portal_api import router as owner_portal_api_router" in main
    assert "app.include_router(owner_portal_api_router)" in main


def test_owner_safe_routes_require_owner_portal_role() -> None:
    source = SOURCE.read_text()

    assert 'router = APIRouter(prefix="/api/v1/owner"' in source
    assert source.count("Depends(require_owner_portal_request)") >= 2
    assert '@router.get("/overview")' in source
    assert '@router.get("/inventory")' in source


def test_owner_inventory_is_defence_in_depth_scoped_to_authenticated_owner() -> None:
    source = SOURCE.read_text()

    assert 'owner_id = access["owner_id"]' in source
    assert 'filters = ["i.owner_id=$1"]' in source
    assert "where owner_id=$1" in source


def test_owner_inventory_response_is_an_explicit_safe_allowlist() -> None:
    source = SOURCE.read_text()
    start = source.index("rows = await connection.fetch(")
    end = source.index("return jsonable_encoder(", start)
    query = source[start:end]

    allowed = (
        "i.inventory_code",
        "p.product_type",
        "p.game",
        "p.name",
        "p.set_name",
        "p.card_number",
        "p.variant",
        "p.rarity",
        "i.language",
        "p.language",
        "i.condition",
        "i.grading_company",
        "i.grade",
        "i.status",
        "i.market_value_minor",
        "i.store_price_minor",
        "i.pricing_updated_at",
        "i.created_at",
        "i.updated_at",
    )
    for field in allowed:
        assert field in query

    assert "as image_url" in query
    assert "m.scope='INVENTORY_ITEM'" in query
    assert "m.scope='CANONICAL_CARD'" in query
    assert "m.approval_status='APPROVED'" in query
    assert "m.rights_status='VERIFIED'" in query
    assert "m.rights_tier='STOREFRONT_ALLOWED'" in query
    assert "m.source_status='ACTIVE'" in query
    assert "m.revoked_at is null" in query

    forbidden = (
        "acquisition_cost_minor",
        "acquisition_date",
        "certificate_number",
        "storage_location_id",
        "storage_location_code",
        "storage_location_label",
        "purchase_lot_id",
        "purchase_lot_code",
        "i.notes",
        "i.version",
        "shopify_product_id",
        "ebay_listing_id",
        "ebay_offer_id",
        "last_error_code",
        "identity_confirmed",
    )
    for field in forbidden:
        assert field not in query


def test_owner_overview_contains_no_company_wide_finance_or_admin_data() -> None:
    source = SOURCE.read_text()
    start = source.index('@router.get("/overview")')
    end = source.index('@router.get("/inventory")', start)
    overview = source[start:end]

    assert "where owner_id=$1" in overview
    assert "total_inventory_count" in overview
    assert "active_market_value_minor" in overview
    assert "active_store_price_minor" in overview

    for forbidden in (
        "financial_ledger_entries",
        "platform_fee",
        "payment_fee",
        "commission_bps",
        "stripe_account_id",
        "shopify",
        "ebay",
        "storage_location",
        "audit_events",
    ):
        assert forbidden not in overview.lower()


def test_invalid_owner_inventory_status_fails_closed() -> None:
    source = SOURCE.read_text()

    assert "if status_value not in VISIBLE_STATUSES" in source
    assert 'filters.append("false")' in source
