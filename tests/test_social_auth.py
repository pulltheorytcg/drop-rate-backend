from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "backend" / "app" / "static" / "index.html"
APP = ROOT / "backend" / "app" / "static" / "app.js"
JOIN = ROOT / "backend" / "app" / "static" / "join.html"
JOIN_JS = ROOT / "backend" / "app" / "static" / "join.js"


def test_founder_login_exposes_enabled_social_providers_only() -> None:
    html = INDEX.read_text()
    js = APP.read_text()

    assert 'id="login-google"' in html
    assert 'id="login-apple"' in html
    assert 'id="login-social-auth"' in html

    assert 'authRequest("/settings")' in js
    assert "external.google" in js
    assert "external.apple" in js
    assert '/auth/v1/authorize' in js
    assert 'authorizeUrl.searchParams.set("provider", provider)' in js
    assert 'authorizeUrl.searchParams.set("redirect_to", `${window.location.origin}/`)' in js


def test_social_login_does_not_bypass_founder_hq_role_check() -> None:
    js = APP.read_text()

    assert 'apiRequest("/api/v1/access/me")' in js
    assert "founder_hq_allowed" in js
    assert "FOUNDER_HQ_ACCESS_DENIED" in js
    assert "This account is not authorised for Founder HQ." in js


def test_oauth_callback_is_converted_to_existing_drop_rate_session() -> None:
    js = APP.read_text()

    assert "function parseOAuthSession()" in js
    assert 'params.get("access_token")' in js
    assert "saveSession({" in js
    assert "hydrateSessionUser" in js


def test_invite_onboarding_supports_google_and_apple_without_dropping_invite() -> None:
    html = JOIN.read_text()
    js = JOIN_JS.read_text()

    for element_id in (
        "join-google",
        "join-apple",
        "existing-google",
        "existing-apple",
    ):
        assert f'id="{element_id}"' in html

    assert 'authRequest("/settings")' in js
    assert "localStorage.setItem(PENDING_INVITE_KEY, state.token)" in js
    assert '/auth/v1/authorize' in js
    assert "/join?invite=" in js
    assert "finishAuthenticatedOnboarding(session)" in js


def test_new_password_ui_matches_current_security_policy() -> None:
    index = INDEX.read_text()
    join = JOIN.read_text()

    assert 'id="new-password" type="password" autocomplete="new-password" required minlength="12"' in index
    assert 'id="confirm-password" type="password" autocomplete="new-password" required minlength="12"' in index
    assert 'id="join-password" type="password" autocomplete="new-password" required minlength="12"' in join
    assert 'id="join-confirm-password" type="password" autocomplete="new-password" required minlength="12"' in join

    # Existing credentials must remain usable even if they predate the new policy.
    assert 'id="login-password" type="password" autocomplete="current-password" required minlength="12"' not in index
