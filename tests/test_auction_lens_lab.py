"""UK auction lab is local-video-only, disabled by default, and source-safe."""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STATIC = BASE / "backend" / "app" / "static"
MAIN = (BASE / "backend" / "app" / "main.py").read_text()
API = (BASE / "backend" / "app" / "auction_lens_api.py").read_text()


def test_lab_only_exposed_when_feature_explicitly_enabled():
    assert '@app.get("/auction-lens-lab", include_in_schema=False)' in MAIN
    block = MAIN[MAIN.index('@app.get("/auction-lens-lab"'):
                 MAIN.index('@app.get("/seller-hub"')]
    assert 'TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED' in block
    assert 'raise HTTPException(status_code=404' in block
    assert 'auction-lens-lab.html' in block


def test_only_lab_gets_local_blob_video_permission():
    assert 'local_video_media = "media-src' in MAIN
    assert 'if request.url.path == "/auction-lens-lab" else ""' in MAIN
    assert 'response.headers["Content-Security-Policy"]' in MAIN


def test_video_lab_has_no_external_live_source_or_recording_upload():
    script = (STATIC / "auction-lens-lab.js").read_text()
    for forbidden in (
        "whatnot.com", "www.ebay", "i.ebayimg", "navigator.mediaDevices",
        "getDisplayMedia(", "MediaRecorder(", "document.cookie",
        "localStorage.setItem", "sessionStorage.setItem",
    ):
        assert forbidden not in script, forbidden
    assert 'URL.createObjectURL(file)' in script
    assert 'URL.revokeObjectURL(objectURL)' in script
    assert '"/api/v1/auction-lens/pilot/resolve"' in script
    assert '"Authorization":"Bearer "+token' in script
    assert 'currentRequest.abort()' in script
    assert 'result.generation!==ownGeneration' in script
    assert 'video.currentTime' in script


def test_video_page_uses_external_csp_compatible_assets_and_explicit_consent():
    page = (STATIC / "auction-lens-lab.html").read_text()
    assert '<script src="/assets/auction-lens-lab.js" defer></script>' in page
    assert '<link rel="stylesheet" href="/assets/auction-lens-lab.css">' in page
    assert 'id="rights-affirmed"' in page
    assert 'id="crop-preview"' in page
    assert 'id="stop-scan"' in page
    assert '<video' in page and 'muted' in page and 'playsinline' in page
    assert '<style' not in page and '<script>' not in page


def test_auction_api_does_not_create_inventory_or_query_market_providers():
    for forbidden in ("CardTraderClient(", "TcgDexClient(", "OpenAIRecognitionVisionClient(",
                      "INSERT INTO", "UPDATE tcg.", "DELETE FROM tcg."):
        assert forbidden not in API
    assert "readonly_snapshot=True" in API
    assert "current_owner(connection)" in API
    assert "TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED" in API
    assert "confirmed_raw_condition" in API
