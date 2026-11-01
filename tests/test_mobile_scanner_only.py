"""Mobile scanner-only navigation and desktop upload compatibility contracts.

These checks verify the authored markup, responsive policy and event wiring.
The JavaScript interaction suite separately simulates close, cancellation,
camera permission and preservation of pending scanned items.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app" / "static"


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_mobile_owner_scan_has_single_camera_entry_but_keeps_desktop_upload():
    html = source("owner.html")
    assert 'id="owner-view-scan"' in html
    assert 'id="owner-mobile-scan-open"' in html
    assert 'class="dr-mobile-scan-entry"' in html
    assert 'id="owner-scan-file"' in html  # Desktop compatibility
    assert 'href="/assets/scanner-flow.css?v=book-auto-v6"' in html
    css = source("scanner-flow.css")
    assert "#owner-view-scan > :not(.dr-mobile-scan-entry)" in css
    assert ".owner-portal-page #owner-view-scan > .dr-mobile-scan-entry" in css
    assert "@media (max-width:900px)" in css


def test_founder_mobile_scan_hides_legacy_upload_and_opens_camera_directly():
    html = source("recognition-scanner.js")
    assert 'id="recognition-mobile-scan-open"' in html
    assert 'id="recognition-file"' in html  # Desktop still supported
    assert 'byId("recognition-mobile-scan-open").addEventListener("click", openRecognitionCamera)' in html
    assert 'if (updateHash && window.matchMedia?.("(max-width: 900px)").matches' in html
    assert 'void openRecognitionCamera();' in html
    css = source("scanner-flow.css")
    assert ".recognition-scanner-panel > :not(.dr-mobile-scan-entry)" in css
    assert ".recognition-scanner-panel > .dr-mobile-scan-entry" in css


def test_shared_mobile_scanner_close_goes_home_but_programmatic_close_does_not():
    scanner = source("scanner-flow.js")
    assert 'close({userExit: true})' in scanner
    assert 'if (userExit && this.mobileOnly()) this.options.onExit?.();' in scanner
    assert 'if (userExit && this.mobileOnly()) this.options.onExit?.();' in scanner
    assert 'this.find(\'[data-action="gallery"]\').disabled = mobile;' in scanner
    assert 'this.find(".dr-scan-file").disabled = mobile;' in scanner
    owner = source("owner-recognition.js")
    founder = source("recognition-scanner.js")
    assert 'activateOwnerView("overview");' in owner
    assert 'activateSellerView("dashboard", true);' in founder
    assert 'byId("owner-mobile-scan-open")?.addEventListener("click", ownerRecognitionLaunchCamera);' in owner
    assert 'window.ownerRecognitionLeave?.();' in source("owner-portal.js")


def test_desktop_upload_and_account_security_are_not_replaced():
    scanner = source("scanner-flow.js")
    css = source("scanner-flow.css")
    assert 'const mobile = this.mobileOnly();' in scanner
    assert 'this.find(\'[data-action="gallery"]\').hidden = mobile;' in scanner
    assert '.dr-scanner .dr-scan-gallery{display:none!important}' in css
    assert '.dr-scanner .dr-scan-shutter{grid-column:2}' in css
    assert "if (userExit && this.mobileOnly())" in scanner
    assert 'role: "seller"' in source("owner-recognition.js")
    assert 'role: "founder"' in source("recognition-scanner.js")
