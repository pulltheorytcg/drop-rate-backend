"""Real card scanner -> exact-copy photo transport, using synthetic local data.

Actual capture canvas, scanner review, photo helper, apiRequest and browser fetch
run against an ephemeral localhost HTTP server. Only camera frames, recognition
results and API persistence are fixtures. No account, provider or live writes.
"""
import base64
import hashlib
import json
import mimetypes
import os
import re
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "backend/app/static"
IMAGE = REPO / "tests/fixtures/scanner/card-photo-synthetic.svg"
OUT = Path(os.getenv("SCAN_PHOTO_LAYOUT_DIR", "/tmp/collection-confirmation/scan-photos"))
TOKEN = "synthetic-card-scan-token"
RUN = "20000000-0000-4000-8000-000000000111"
CATALOGUE = "30000000-0000-4000-8000-000000000111"
COPY = "40000000-0000-4000-8000-000000000111"
PREVIEW = "https://cdn.shopify.com/s/files/1/0000/0001/files/synthetic-owned-scan.jpg"


@contextmanager
def fixture_server():
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", (STATIC / "owner.html").read_text(), flags=re.S)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def json_reply(self, data, status=200):
            self.reply(json.dumps(data).encode(), "application/json", status)

        def handle_api(self):
            state = self.server.fixture
            target = urlsplit(self.path)
            try:
                assert state is not None, "No synthetic session has been configured"
                assert self.headers.get("Authorization") == "Bearer " + TOKEN, "Wrong account authorization"
                size = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(size) if size else b""
                state["requests"].append({"path": target.path, "method": self.command})
                if self.command == "GET" and target.path.endswith("/image"):
                    self.reply(b"No catalogue artwork in this synthetic fixture", "text/plain", 404)
                    return
                assert self.command == "POST", "Unexpected read or write"
                if target.path == "/api/v1/recognition/resolve":
                    assert self.headers.get("Content-Type") == "application/json"
                    payload = json.loads(body)
                    assert payload["force_refresh"] is True
                    prefix, encoded = payload["image_data_url"].split(",", 1)
                    assert prefix == "data:image/jpeg;base64"
                    state["captured"] = base64.b64decode(encoded, validate=True)
                    assert state["captured"].startswith(b"\xff\xd8")
                    self.json_reply({"run": {"id": RUN, "decision": "EXACT_CANDIDATE", "top_catalogue_id": CATALOGUE},
                        "candidates": [{"id": "candidate-synthetic", "catalogue_id": CATALOGUE, "rank": 1,
                            "source_kind": "CATALOGUE", "market_value_minor": 1000,
                            "candidate_snapshot": {"name": "Synthetic card · exact copy photo test",
                                "game": "One Piece", "set_name": "Synthetic browser fixture", "card_number": "001/001",
                                "variant": "Normal", "language": "English", "product_type": "CARD"}}]})
                    return
                if target.path == f"/api/v1/recognition/runs/{RUN}/feedback":
                    payload = json.loads(body)
                    assert payload["selected_catalogue_id"] == CATALOGUE and payload["outcome"] == "CONFIRMED_TOP"
                    state["feedback"] += 1
                    self.json_reply({"saved": True})
                    return
                if target.path == "/api/v1/owner/recognition-intake":
                    payload = json.loads(body)
                    assert payload["recognition_run_id"] == RUN and payload["selected_catalogue_id"] == CATALOGUE
                    assert payload["language"] == "English" and payload["condition"] is None
                    assert "acquisition_cost_minor" not in payload, "Optional cost must not be invented"
                    key = self.headers.get("Idempotency-Key")
                    assert re.fullmatch(r"[0-9a-f-]{36}", key or "", re.I), "Missing inventory retry key"
                    assert key not in state["intake_keys"], "Photo retry repeated inventory intake"
                    state["intake_keys"].append(key)
                    number = len(state["intake_keys"])
                    inventory = {"id": COPY if number == 1 else f"40000000-0000-4000-8000-{111+number:012d}",
                        "inventory_code": "INV-SYNTHETIC-" + str(number), "version": 7,
                        "status": "DRAFT", "sale_intent": "PERSONAL_COLLECTION", "acquisition_cost_minor": None}
                    state["inventory"].append(inventory)
                    self.json_reply({"inventory": inventory}, 201)
                    return
                assert target.path == f"/api/v1/owner/inventory/{COPY}/photo/upload", "Photo must belong only to the first exact copy"
                assert len(state["inventory"]) == state["quantity"], "Photo arrived before inventory committed"
                query = parse_qs(target.query)
                assert query["side"] == [state["side"]] and query["rights_confirmed"] == ["true"]
                assert query["version"] == ["7"], "Photo must use the intake's inventory version"
                assert query["filename"] == ["scan-" + state["side"].lower() + ".jpg"]
                assert self.headers.get("Content-Type") == "image/jpeg", "Photo must be a raw image body"
                assert body == state["captured"], "Upload bytes differ from the actual scanner capture"
                key = query["request_key"][0]
                assert re.fullmatch(r"[0-9a-f-]{36}", key, re.I), "Missing per-photo retry key"
                state["uploads"].append({"side": query["side"][0], "version": 7, "key": key,
                    "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
                if state["fail_first"] and len(state["uploads"]) == 1:
                    self.json_reply({"detail": "Synthetic photo transfer interrupted. Retry this photo."}, 503)
                    return
                state["saved_photos"] += 1
                asset = {"id": "synthetic-physical-photo", "side": state["side"], "version": 1,
                    "approval_status": "PENDING", "rights_status": "PENDING", "shopify_file_status": "READY", "photo_url": PREVIEW}
                self.json_reply({"asset": asset, "inventory_version": 7, "message": "Photo received for review."}, 201)
            except Exception as error:
                self.server.errors.append(str(error) or type(error).__name__)
                self.json_reply({"detail": "Synthetic receiver rejected request: " + str(error)}, 422)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                self.handle_api()
            elif path == "/":
                self.reply(html.encode(), "text/html")
            elif path == "/__fixture__/card.svg":
                self.reply(IMAGE.read_bytes(), "image/svg+xml")
            elif path.startswith("/assets/"):
                asset = (STATIC / path.removeprefix("/assets/")).resolve()
                if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                    self.reply(asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                else:
                    self.reply(b"Not found", "text/plain", 404)
            else:
                self.reply(b"Not found", "text/plain", 404)

        do_POST = handle_api
        do_PATCH = handle_api
        do_DELETE = handle_api

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.origin = f"http://127.0.0.1:{server.server_port}"
    server.fixture = None
    server.errors = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


SETUP = """async token => {
  state.session={access_token:token,user:{id:'synthetic-owner'}};
  document.body.classList.remove('hub-restoring');document.querySelector('.hub-loading')?.remove();
  byId('owner-auth-view').classList.add('hidden');byId('owner-portal-view').classList.remove('hidden');
  window.cspViolations=[];document.addEventListener('securitypolicyviolation',event=>cspViolations.push(event.violatedDirective));
  window.afterSaves=0;window.viewedCollection=0;window.cameraStops=0;
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>({
    getTracks:()=>[{stop(){cameraStops++;}}],getVideoTracks:()=>[]})}});
  window.scanner=new DropRateScanner.Scanner({role:'seller',session:()=>state.session,request:apiRequest,
    afterSave:async()=>{afterSaves++;},viewInventory:()=>{viewedCollection++;}});
  const image=new Image();image.src='/__fixture__/card.svg';await image.decode();
  Object.defineProperty(scanner.video,'srcObject',{configurable:true,writable:true,value:null});
  Object.defineProperty(scanner.video,'videoWidth',{value:image.width});
  Object.defineProperty(scanner.video,'videoHeight',{value:image.height});scanner.video.play=async()=>{};
  scanner.frame=()=>({present:false,fingerprint:new Uint8Array(560)});
  const draw=CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage=function(source,...args){
    return draw.call(this,source===scanner.video?image:source,...args);
  };
  await scanner.open('RAW');scanner.auto=false;
}"""


def layout(page, width):
    for selector in (".dr-scanner", ".dr-scan-review", ".dr-scan-review-list"):
        assert page.locator(selector).evaluate("node=>node.scrollWidth<=node.clientWidth+1"), f"{width}: horizontal overflow in {selector}"
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
    small = []
    for control in page.locator(".dr-scan-review button:visible,.dr-scan-review select:visible").all():
        box = control.bounding_box()
        if not box or box["width"] < 44 or box["height"] < 44:
            small.append({"control": control.inner_text(), "box": box})
    assert not small, {"width": width, "small_controls": small}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    cases = (("front", "FRONT", False, 1), ("retry-back", "BACK", True, 1),
             ("identification-only", "IDENTIFICATION_ONLY", False, 1), ("three-copies", "FRONT", False, 3))
    with fixture_server() as server, sync_playwright() as playwright:
        for engine in os.getenv("BROWSER_ENGINES", "chromium,webkit").split(","):
            browser = getattr(playwright, engine).launch(headless=True)
            try:
                for width in (390, 1440):
                    for case, side, failed, quantity in cases:
                        print(f"Card scan photo: {engine} {width} {case}", flush=True)
                        server.fixture = {"requests": [], "captured": None, "feedback": 0, "intake_keys": [],
                            "inventory": [], "uploads": [], "saved_photos": 0, "fail_first": failed, "side": side, "quantity": quantity}
                        page = browser.new_page(viewport={"width": width, "height": 844 if width == 390 else 1000})
                        page.set_default_timeout(10000)
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        preview_requests = []

                        def route_request(route):
                            if route.request.url == PREVIEW:
                                headers = route.request.all_headers()
                                assert not any(name in headers for name in ("authorization", "cookie", "referer")), headers
                                assert TOKEN not in json.dumps(headers) + route.request.url
                                preview_requests.append(route.request.url)
                                route.fulfill(body=server.fixture["captured"], content_type="image/jpeg",
                                    headers={"Access-Control-Allow-Origin": "*"})
                            elif route.request.url.startswith(server.origin + "/"):
                                route.continue_()
                            else:
                                route.abort()

                        page.route("**/*", route_request)
                        page.goto(server.origin + "/")
                        for name in ("hub-session.js", "reference-value-display.js", "owner-portal.js", "scan-photos.js", "scanner-flow.js"):
                            source = (STATIC / name).read_text()
                            page.add_script_tag(content=re.sub(r"\ninitialise\(\);\s*$", "", source))
                        page.evaluate(SETUP, TOKEN)
                        assert page.evaluate("scanner.dialog.open && scanner.view==='camera' && !!scanner.stream"), {
                            "errors": errors, "camera": page.evaluate("({open:scanner.dialog.open,view:scanner.view,stream:!!scanner.stream,status:scanner.find('.dr-scan-status').textContent})")}
                        page.screenshot(path=str(OUT / f"{engine}-{width}-{case}-camera.png"))
                        page.get_by_role("button", name="Scan card or book", exact=True).click()
                        page.wait_for_function("scanner.items[0]?.status==='matched'")
                        assert server.fixture["captured"] and len(server.fixture["inventory"]) == 0
                        assert page.evaluate("scanner.items[0].photo.startsWith('data:image/jpeg;base64,')")
                        page.get_by_role("button", name="Next →", exact=True).click()
                        if quantity > 1:
                            # A synthetic batch quantity exercises the existing save path,
                            # while all review and transport behavior remains production JS.
                            page.evaluate("n=>{scanner.items[0].quantity=n;scanner.renderReview();}", quantity)
                        choice = page.get_by_role("combobox", name="Save scan as", exact=True)
                        assert choice.locator("option").evaluate_all("options=>options.map(option=>option.value)") == ["FRONT", "BACK", "IDENTIFICATION_ONLY"]
                        choice.select_option(side)
                        disclosure = page.locator(".dr-scan-review .dr-scan-photo-note").inner_text()
                        assert ("first copy" in disclosure and "own photos" in disclosure) if quantity > 1 else "confirms you can use this photo for selling" in disclosure
                        prefix = f"{engine}-{width}-{case}"
                        page.screenshot(path=str(OUT / f"{prefix}-review.png"))
                        layout(page, width)
                        page.locator('.dr-scan-review-footer [data-action="save"]').click()
                        page.wait_for_function("scanner.items[0]?.status==='added' && !scanner.saving")
                        assert not server.errors, server.errors
                        assert len(server.fixture["inventory"]) == quantity and server.fixture["feedback"] == 1
                        assert all(item["status"] == "DRAFT" and item["acquisition_cost_minor"] is None for item in server.fixture["inventory"])
                        if failed:
                            assert page.evaluate("scanner.items[0].photoPending && !!scanner.items[0].photo")
                            assert "Item added." in page.locator(".dr-scan-item-error").inner_text()
                            retry = page.get_by_role("button", name="Retry photo", exact=True)
                            retry.scroll_into_view_if_needed();layout(page, width)
                            page.screenshot(path=str(OUT / f"{prefix}-retry.png"))
                            retry.click()
                            page.wait_for_function("!scanner.saving && !scanner.items[0].photoPending")
                            footer = page.locator(".dr-scan-save-message").inner_text()
                            assert "Photo saved for review" in footer and "needs retrying" not in footer
                            assert len(server.fixture["uploads"]) == 2
                            assert server.fixture["uploads"][0] == server.fixture["uploads"][1], "Retry changed the captured bytes, exact copy, side or request key"
                            assert len(server.fixture["inventory"]) == quantity and server.fixture["feedback"] == 1
                        expected_photos = 0 if side == "IDENTIFICATION_ONLY" else 1
                        assert server.fixture["saved_photos"] == expected_photos
                        assert len(server.fixture["uploads"]) == (2 if failed else expected_photos)
                        assert page.evaluate("scanner.items[0].status==='added' && scanner.items[0].photo===null && scanner.items[0].photoDraft.dataUrl===null")
                        if expected_photos:
                            assert page.evaluate("scanner.items[0].photoDraft.asset.approval_status==='PENDING'")
                            assert "Scan photo saved · awaiting selling review" in page.locator(".dr-scan-review").inner_text()
                            page.wait_for_function("url=>{const image=document.querySelector('.dr-scan-review-thumb img');return image && !image.hidden && image.src===url && image.naturalWidth>0;}", arg=PREVIEW)
                            assert preview_requests
                            assert page.locator(".dr-scan-review-thumb .dr-scan-capture-label").is_visible()
                            assert page.locator(".dr-scan-review-thumb .dr-scan-capture-label").inner_text() == "Scan photo"
                            assert "not verified catalogue artwork" in page.locator(".dr-scan-review-thumb img").get_attribute("title")
                        assert "data:image" not in page.evaluate("JSON.stringify({local:{...localStorage},session:{...sessionStorage}})")
                        assert page.evaluate("afterSaves") == 1
                        layout(page, width)
                        page.screenshot(path=str(OUT / f"{prefix}-saved.png"))
                        page.locator('.dr-scan-review-footer [data-action="save"]').click()
                        assert page.evaluate("viewedCollection===1 && !scanner.dialog.open")
                        assert not errors and not server.errors and page.evaluate("cspViolations") == [], (errors, server.errors)
                        results.append({"engine": engine, "width": width, "case": case,
                            "intakes": quantity, "photos": expected_photos, "upload_attempts": len(server.fixture["uploads"]),
                            "capture_sha256": hashlib.sha256(server.fixture["captured"]).hexdigest(), "passed": True})
                        page.close()
            finally:
                browser.close()
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"PASS: {len(results)} real-browser card capture/photo handoffs; exact raw bytes, copy/side/version, photo-only retry, nullable cost and responsive controls")


if __name__ == "__main__":
    main()
