from pathlib import Path

from app.schemas import InventoryPatch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'backend' / 'app' / 'api.py'
OWNER_API = ROOT / 'backend' / 'app' / 'owner_portal_api.py'
OWNER_FINANCE = ROOT / 'backend' / 'app' / 'owner_portal_finance.py'
PAYOUT_PREFS = ROOT / 'backend' / 'app' / 'payout_preferences.py'
STRIPE = ROOT / 'backend' / 'app' / 'stripe_connect.py'
ACCESS_MIGRATION = ROOT / 'database' / 'migrations' / '20260926213000_access_control_foundation.sql'

def test_inventory_patch_cannot_reassign_owner() -> None:
    assert 'owner_id' not in InventoryPatch.model_fields

def test_founder_inventory_mutations_bind_inventory_to_authenticated_owner() -> None:
    source = API.read_text()
    sections = (
        ('@router.patch("/inventory/{inventory_id}"', '@router.post("/inventory/{inventory_id}/approve"'),
        ('@router.post("/inventory/{inventory_id}/approve"', '@router.post("/inventory/bulk-cost"'),
        ('@router.post("/inventory/bulk-cost"', '@router.get("/purchase-lots"'),
    )
    for start_marker, end_marker in sections:
        section = source[source.index(start_marker):source.index(end_marker)]
        assert 'owner = await _owner(connection)' in section
        assert 'owner["id"]' in section
        assert 'owner_id' in section

def test_cross_owner_inventory_id_is_never_enough_to_authorize_mutation() -> None:
    source = API.read_text()
    patch = source[source.index('@router.patch("/inventory/{inventory_id}"'):source.index('@router.post("/inventory/{inventory_id}/approve"')]
    approve = source[source.index('@router.post("/inventory/{inventory_id}/approve"'):source.index('@router.post("/inventory/bulk-cost"')]
    bulk = source[source.index('@router.post("/inventory/bulk-cost"'):source.index('@router.get("/purchase-lots"')]
    assert 'where i.id = $1 and i.owner_id = $2' in patch
    assert 'where id = $1 and owner_id = $2 and version = $3' in patch
    assert 'where i.id = $1 and i.owner_id = $2' in approve
    assert 'where id = $1 and owner_id = $2 and version = $3' in approve
    assert 'where owner_id = $1 and id = any($2::uuid[])' in bulk
    assert 'where id = $3 and owner_id = $4 and version = $5' in bulk

def test_restricted_owner_surfaces_never_accept_an_owner_selector() -> None:
    for path in (OWNER_API, OWNER_FINANCE):
        source = path.read_text()
        assert 'owner_id: UUID' not in source
        assert 'owner_id: str' not in source
        assert 'owner_id = access["owner_id"]' in source

def test_owner_finance_queries_scope_orders_ledger_and_payouts() -> None:
    source = OWNER_FINANCE.read_text()
    assert source.count('where owner_id=$1') >= 4
    assert 'where oi.owner_id=$1' in source
    assert 'where owner_id=$1 and order_id is not null' in source
    assert 'from tcg.payout_requests' in source

def test_self_service_payout_and_stripe_routes_resolve_owner_from_session() -> None:
    payout_source = PAYOUT_PREFS.read_text()
    stripe_source = STRIPE.read_text()
    model = payout_source.split('class PayoutPreferenceUpdate', 1)[1].split('def _next_weekday', 1)[0]
    assert 'owner_id' not in model
    assert 'owner = await _owner(connection)' in payout_source
    assert 'where owner_id=$1' in payout_source
    for marker in ('@router.get("/connect/status")', '@router.post("/connect/account"', '@router.post("/connect/onboarding-link")', '@router.post("/connect/sync")'):
        section = stripe_source[stripe_source.index(marker):]
        assert 'owner = await _owner(connection)' in section
        assert 'where owner_id=$1' in section

def test_database_rls_keeps_tcg_api_owner_rows_membership_scoped() -> None:
    sql = ACCESS_MIGRATION.read_text().lower()
    assert 'to tcg_api' in sql
    assert 'tcg.current_user_id()' in sql
    assert 'm.user_id=tcg.current_user_id()' in sql
    assert 'm.active' in sql
    assert 'o.active' in sql

def test_founder_hq_mutations_require_platform_admin_dependency() -> None:
    source = API.read_text()
    for route in (
        '@router.patch("/inventory/{inventory_id}", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/inventory/{inventory_id}/approve", dependencies=[Depends(require_platform_admin_request)])',
        '@router.post("/inventory/bulk-cost", dependencies=[Depends(require_platform_admin_request)])',
    ):
        assert route in source
