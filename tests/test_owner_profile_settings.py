from pathlib import Path

import pytest
from pydantic import ValidationError

from app.owner_portal_api import OwnerProfileUpdate


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260930230500_owner_profile_settings.sql"
API = ROOT / "backend" / "app" / "owner_portal_api.py"
HTML = ROOT / "backend" / "app" / "static" / "owner.html"
JS = ROOT / "backend" / "app" / "static" / "owner-portal.js"
CSS = ROOT / "backend" / "app" / "static" / "owner-portal.css"


def test_owner_profile_username_is_database_owned_and_unique() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "add column if not exists username text" in lower
    assert "owners_username_format_check" in lower
    assert "owners_username_lower_uidx" in lower
    assert "on tcg.owners (lower(username))" in lower
    assert "security definer" in lower
    assert "tcg.current_user_id()" in sql
    assert "m.role = 'OWNER'" in sql
    assert "m.user_id = v_user_id" in sql
    assert "for update of o" in lower
    assert "OWNER_PROFILE_UPDATED" in sql
    assert "tcg.audit_events" in sql
    assert "revoke all on function tcg.update_owner_profile(text, text) from public" in lower
    assert "grant execute on function tcg.update_owner_profile(text, text) to tcg_api" in lower


def test_owner_profile_payload_normalises_username_and_rejects_invalid_values() -> None:
    payload = OwnerProfileUpdate(display_name="  Seller One  ", username="  My_Handle  ")
    assert payload.display_name == "Seller One"
    assert payload.username == "my_handle"

    with pytest.raises(ValidationError):
        OwnerProfileUpdate(display_name="Seller", username="ab")

    with pytest.raises(ValidationError):
        OwnerProfileUpdate(display_name="Seller", username="_starts_wrong")

    with pytest.raises(ValidationError):
        OwnerProfileUpdate(display_name="Seller", username="bad-name")


def test_owner_profile_api_is_owner_scoped_and_audited_through_database_function() -> None:
    source = API.read_text()

    get_start = source.index('@router.get("/profile")')
    patch_start = source.index('@router.patch("/profile")')
    overview_start = source.index('@router.get("/overview")')
    get_route = source[get_start:patch_start]
    patch_route = source[patch_start:overview_start]

    assert "Depends(require_owner_portal_request)" in get_route
    assert 'owner_id = access["owner_id"]' in get_route
    assert "where o.id=$1" in get_route
    assert "m.user_id=tcg.current_user_id()" in get_route
    assert "commission_bps" in get_route

    assert "Depends(require_owner_portal_request)" in patch_route
    assert "select * from tcg.update_owner_profile($1,$2)" in patch_route
    assert "UniqueViolationError" in patch_route
    assert 'status_code=409' in patch_route
    assert "That username is already taken" in patch_route


def test_seller_hub_profile_ui_supports_identity_email_and_password_changes() -> None:
    html = HTML.read_text()
    js = JS.read_text()

    assert 'data-owner-view="profile"' in html
    assert 'data-owner-jump="profile"' in html
    assert 'data-owner-view-panel="profile"' in html
    assert 'id="owner-profile-display-name"' in html
    assert 'id="owner-profile-username"' in html
    assert 'id="owner-profile-new-email"' in html
    assert 'id="owner-profile-current-password"' in html
    assert 'id="owner-profile-new-password"' in html

    assert 'apiRequest("/api/v1/owner/profile")' in js
    assert 'apiRequest("/api/v1/owner/profile", {' in js
    assert 'method: "PATCH"' in js
    assert 'authRequest("/token?grant_type=password"' in js
    assert 'body: JSON.stringify({email, password: currentPassword})' in js
    assert 'body: JSON.stringify({password: newPassword})' in js
    assert '/user?redirect_to=' in js
    assert 'body: JSON.stringify({email: newEmail})' in js

    assert "service_role" not in js.lower()
    assert "password" not in str(ROOT / "BUILD_STATUS.md").lower()


def test_profile_is_reachable_on_mobile_without_overcrowding_fixed_tabs() -> None:
    css = CSS.read_text()
    html = HTML.read_text()

    assert 'data-owner-view="profile"' in html
    assert "overflow-x:auto" in css
    assert "flex:0 0 76px" in css
    assert ".owner-nav::-webkit-scrollbar{display:none}" in css
    assert ".owner-profile-grid{grid-template-columns:1fr}" in css
