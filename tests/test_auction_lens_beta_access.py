"""Closed-beta account isolation and UI fail-closed deployment checks.

These are policy/contract tests; live signed-in accounts must be verified in a
staging environment before enabling beta users in Railway production.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "backend" / "app" / "static"
API = (ROOT / "backend" / "app" / "auction_lens_api.py").read_text()
LAB = (STATIC / "auction-lens-lab.js").read_text()
HTML = (STATIC / "auction-lens-lab.html").read_text()
MAIN = (ROOT / "backend" / "app" / "main.py").read_text()


def test_disabled_lab_controls_are_not_enabled_until_signed_in_entitlement():
    assert 'id="video-file" type="file" disabled' in HTML
    assert 'id="start-scan" type="button" class="primary" disabled' in HTML
    assert 'id="new-lot" type="button" disabled' in HTML
    assert 'id="beta-access-state"' in HTML
    assert 'role="status"' in HTML
    assert 'let betaAllowed = false' in LAB
    assert 'if(!betaAllowed)' in LAB
    assert '"/api/v1/auction-lens/pilot/access"' in LAB
    assert '"Authorization":"Bearer "+token' in LAB
    assert 'cache:"no-store"' in LAB
    assert 'data.enabled===true' in LAB
    assert 'id!==betaCheckId' in LAB
    assert 'if(previouslyAllowed&&!allowed)stop()' in LAB
    assert 'betaCheckInterval=setInterval' in LAB
    assert 'window.addEventListener("hub-session-cleared"' in LAB
    assert 'window.addEventListener("focus"' in LAB
    assert 'document.addEventListener("visibilitychange"' in LAB


def test_beta_scope_is_account_specific_both_on_access_and_frame_resolve():
    assert 'TCG_AUCTION_LENS_BETA_USER_IDS' in API
    assert 'def _beta_allowed(user_id: UUID)' in API
    assert 'def _require_beta(user: AuthenticatedUser)' in API
    assert 'or not _beta_allowed(user.user_id)' in API
    assert '@router.get("/pilot/access")' in API
    assert '@router.post("/pilot/resolve")' in API
    assert 'readonly_snapshot=True' in API
    assert 'await current_owner(connection)' in API
    after = API.split('async def resolve_authorised_auction_frame', 1)[1]
    assert after.index('_require_beta(user)') < after.index('decode_image_data_url(')
    # Reject before consuming image bytes, DB, rate slots and provider resources.
    assert after.index('_require_beta(user)') < after.index('_LOOKUP_LIMIT.acquire()')


def test_beta_endpoints_have_no_publish_refund_settle_or_auto_bid_actions():
    for forbidden in (
        'INSERT INTO', 'UPDATE tcg.', 'DELETE FROM tcg.',
        'CardTraderClient(', 'TcgDexClient(', 'OpenAIRecognitionVisionClient(',
        'placeBid(', 'createBid(', 'MediaRecorder(',
    ):
        assert forbidden not in API
    assert 'TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED' in API
    # Page itself is not an authentication mechanism: API is independently gated.
    assert 'TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED' in MAIN
    assert 'auction-lens-lab.html' in MAIN
