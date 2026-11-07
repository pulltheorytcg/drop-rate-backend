"""Comic listing photo recovery with real controls and synthetic same-origin APIs.

Replays the two-photo/consent failure reported in the 3 November phone recording.
No customer photograph, account, hosted upload or publication request is used.
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

ROOT = Path(__file__).resolve().parents[2] / "backend/app/static"
OUT = Path(os.getenv("COMIC_RECOVERY_LAYOUT_DIR", "/tmp/comic-listing-recovery"))
FIRST = "00000000-0000-4000-8000-000000000111"

FIXTURE = r"""
async () => {
  window.realApiRequest=apiRequest;
  state.session={access_token:'synthetic-only',user:{id:'seller-a'}};
  loadOwnerInventory=loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=async()=>{};
  window.calls=[];window.uploads=[];window.uploadMode='fail-first';window.failedOnce=false;
  window.photoReceipts=new Map();
  window.baseItem={id:'00000000-0000-4000-8000-000000000111',catalogue_id:'fixture-printing-2',
    inventory_code:'INV-COMIC-FIXTURE',version:1,status:'INSPECTION',sale_intent:'FOR_SALE',
    product_type:'COMIC',game:'Marvel Comics',language:'English',name:'Deadpool / Batman #1',
    set_name:'Deadpool / Batman',card_number:'1',variant:'Printing 2',condition:'Mint',
    market_value_minor:null,store_price_minor:1000,seller_approval_available:false,shopify_sync_enabled:true,
    comic_listing_preparation:{},comic_photos:[],comic_acquisition_cost_minor:null,
    comic_printing:{system_code:'MARVEL_COMICS',printing_number:2,issue_number:'1',attributes:{publisher:'Marvel'}},
    approval_blockers:['Drop Rate selling review: confirm the exact printing before publication',
      'Storage / dispatch location needs recording by Drop Rate',
      'Shopify media: approved first-party physical front image',
      'Drop Rate must configure shipping profile COMIC_BOOK']};
  window.currentItem=structuredClone(baseItem);
  const receive=async(url,options)=>{
    const target=new URL(url,location.origin),side=target.searchParams.get('side'),key=target.searchParams.get('request_key');
    if(!['FRONT','BACK'].includes(side))throw new Error('Fixture: invalid photo side');
    if(!/^[0-9a-f-]{36}$/i.test(key||''))throw new Error('Fixture: missing per-photo request key');
    if(target.searchParams.get('rights_confirmed')!=='true')throw new Error('Fixture: consent was not submitted');
    if(!(options.body instanceof File))throw new Error('Fixture: photo must use the raw File body');
    const bytes=await options.body.arrayBuffer();
    const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    const headers=new Headers(options.headers||{});
    const sent={url,side,key,version:Number(target.searchParams.get('version')),
      filename:target.searchParams.get('filename'),name:options.body.name,size:bytes.byteLength,digest,
      type:options.body.type,contentType:headers.get('Content-Type'),actor:state.session.user.id};
    uploads.push(sent);
    if(sent.filename!==options.body.name || sent.contentType!==options.body.type)throw new Error('Fixture: filename/content type mismatch');
    if(uploadMode==='fail-first'&&!failedOnce){failedOnce=true;throw new TypeError('Load failed');}
    if(photoReceipts.has(key))return {...photoReceipts.get(key),replayed:true};
    if(sent.version!==currentItem.version)throw new Error('Fixture: stale inventory version');
    const asset={id:'fixture-'+side.toLowerCase(),version:1,side,approval_status:'PENDING',
      rights_status:'PENDING',shopify_file_status:'READY'};
    currentItem={...currentItem,version:currentItem.version+1,comic_photos:[...currentItem.comic_photos,asset]};
    const result={asset,replayed:false,message:'Photo received for staff review.'};photoReceipts.set(key,result);
    if(uploadMode==='commit-then-lost'){uploadMode='success';throw new TypeError('Load failed');}
    return result;
  };
  apiRequest=async(url,options={})=>{
    const target=new URL(url,location.origin),path=target.pathname;
    calls.push({url,method:options.method||'GET',body:options.body instanceof Blob?'[raw photograph]':options.body,
      actor:state.session.user.id});
    if(options.method==='POST'&&path.endsWith('/comic-photo/upload'))return receive(url,options);
    if(options.method==='PATCH'&&path.endsWith('/comic-preparation')){
      const body=JSON.parse(options.body);if(body.version!==currentItem.version)throw new Error('Fixture: stale preparation version');
      currentItem={...currentItem,version:currentItem.version+1,comic_listing_preparation:body};
      return {message:'Preparation details saved for review.'};
    }
    if(options.method==='PATCH'&&path.endsWith('/selling-price')){
      const body=JSON.parse(options.body);if(body.version!==currentItem.version)throw new Error('Fixture: stale selling-price version');
      currentItem={...currentItem,version:currentItem.version+1,store_price_minor:body.store_price_minor};
      return {message:'Selling price saved.'};
    }
    if(options.method==='POST'&&path.endsWith('/approval-request')){
      const body=JSON.parse(options.body);if(body.version!==currentItem.version)throw new Error('Fixture: stale review version');
      currentItem={...currentItem,version:currentItem.version+1,status:'INSPECTION',sale_intent:'FOR_SALE',
        store_price_minor:body.store_price_minor,condition:body.condition};
      return {message:'Listing review requested.'};
    }
    if(!options.method&&path==='/api/v1/owner/inventory/'+currentItem.id)return {item:structuredClone(currentItem),copies:[structuredClone(currentItem)]};
    throw new Error('Unexpected fixture API call: '+(options.method||'GET')+' '+path);
  };
  window.freshComic=async(id=baseItem.id)=>{
    DropRateInventory.reset();currentItem={...structuredClone(baseItem),id};
    uploadMode='success';failedOnce=false;photoReceipts.clear();
    await DropRateInventory.open(currentItem,{selling:true,step:'preparation'});
  };
  await DropRateInventory.open(currentItem,{selling:true,step:'preparation'});
}
"""


@contextmanager
def fixture_server():
    """Receive real browser File bytes; WebKit's debug protocol omits them."""
    html = re.sub(r"<script[^>]*>.*?</script>", "", (ROOT / "owner.html").read_text(), flags=re.S)

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
            transport = self.server.transport
            try:
                assert transport is not None, "Unexpected API request before wire verification"
                url = urlsplit(self.path)
                transport["requests"].append({"path": url.path, "method": self.command})
                assert self.headers.get("Authorization") == "Bearer " + transport["token"], "Wrong account Authorization on the wire"
                if self.command == "GET" and url.path == f"/api/v1/owner/inventory/{FIRST}":
                    self.json_reply({"item": transport["item"], "copies": [transport["item"]]})
                    return
                assert self.command == "POST" and url.path == f"/api/v1/owner/inventory/{FIRST}/comic-photo/upload", "Unexpected write or publication request"
                query = parse_qs(url.query)
                side = query["side"][0]
                assert side in transport["expected"] and query["rights_confirmed"] == ["true"], "Missing side or consent"
                expected = transport["expected"][side]
                assert int(query["version"][0]) == transport["item"]["version"], "Stale inventory version on the wire"
                assert query["filename"] == [expected["name"]], "Wrong filename on the wire"
                assert re.fullmatch(r"[0-9a-f-]{36}", query["request_key"][0], re.I), "Missing upload request key"
                assert self.headers.get("Content-Type") == "image/png", "Wrong photo MIME type on the wire"
                length = int(self.headers.get("Content-Length", "0"))
                assert length == len(expected["buffer"]), "Wrong photo length on the wire"
                received = self.rfile.read(length)
                assert received == expected["buffer"], "Received photograph bytes differ from the selected File"
                digest = hashlib.sha256(received).hexdigest()
                assert digest == hashlib.sha256(expected["buffer"]).hexdigest()
                transport["transfers"].append({"side": side, "key": query["request_key"][0], "sha256": digest, "bytes": len(received)})
                asset = {"id": "real-transport-" + side.lower(), "version": 1, "side": side,
                         "approval_status": "PENDING", "rights_status": "PENDING", "shopify_file_status": "READY"}
                transport["item"]["comic_photos"].append(asset)
                transport["item"]["version"] += 1
                self.json_reply({"asset": asset, "replayed": False, "message": "Photo received for staff review."}, 201)
            except Exception as error:
                self.server.errors.append(str(error) or type(error).__name__)
                self.json_reply({"detail": "Synthetic receiver rejected the request: " + str(error)}, 422)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                self.handle_api()
            elif path == "/":
                self.reply(html.encode(), "text/html")
            elif path.startswith("/assets/"):
                asset = (ROOT / path.removeprefix("/assets/")).resolve()
                if asset.is_relative_to(ROOT.resolve()) and asset.is_file():
                    self.reply(asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                else:
                    self.reply(b"Not found", "text/plain", 404)
            else:
                self.reply(b"Not found", "text/plain", 404)

        def do_POST(self):
            self.handle_api()

        do_PATCH = do_POST
        do_PUT = do_POST
        do_DELETE = do_POST
        do_OPTIONS = do_POST

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.origin = f"http://127.0.0.1:{server.server_port}"
    server.transport = None
    server.errors = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def photo(page, filename, color):
    encoded = page.evaluate("""color=>{const canvas=document.createElement('canvas');canvas.width=240;canvas.height=360;
      const ctx=canvas.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,240,360);
      ctx.fillStyle='#ffffff';ctx.fillRect(30,40,180,280);ctx.fillStyle=color;ctx.fillRect(50,65,140,230);
      return canvas.toDataURL('image/png').split(',')[1];}""", color)
    return {"name": filename, "mimeType": "image/png", "buffer": base64.b64decode(encoded)}


def side_row(page, side):
    return page.locator(".owner-comic-photo-row").filter(has_text=re.compile(r"^" + side.capitalize() + r" cover"))


def choose_photos(page, front, back):
    for side, chosen in (("front", front), ("back", back)):
        page.get_by_label(f"Choose {side} comic photo", exact=True).set_input_files(chosen)
        side_row(page, side).locator('input[type="checkbox"]').check()


def selected_photo(page, side, filename):
    row = side_row(page, side)
    assert filename in row.locator(".owner-comic-file-selection").inner_text()
    assert row.locator('input[type="checkbox"]').is_checked()


def no_staged_photos(page, front, back):
    text = page.locator(".owner-comic-preparation").inner_text()
    assert front["name"] not in text and back["name"] not in text
    assert page.locator('.owner-comic-rights input:checked').count() == 0


def no_photo_storage(page, front, back):
    saved = page.evaluate("JSON.stringify({local:{...localStorage},session:{...sessionStorage}})")
    assert front["name"] not in saved and back["name"] not in saved
    assert "data:image" not in saved and "blob:" not in saved
    assert "Synthetic dispatch note" not in saved


def real_transport(page, front, back, server):
    """Exercise actual apiRequest + fetch under connect-src 'self'."""
    page.evaluate("freshComic()")
    transport_requests = []
    account_token = page.evaluate("state.session.access_token")
    server.transport = {"item": page.evaluate("structuredClone(currentItem)"), "token": account_token,
                        "expected": {"FRONT": front, "BACK": back}, "requests": [], "transfers": []}

    def capture(request):
        if request.resource_type in ("fetch", "xhr"):
            transport_requests.append({"url": request.url, "method": request.method})

    page.on("request", capture)
    page.evaluate("() => {apiRequest=realApiRequest;}")
    choose_photos(page, front, back)
    for side in ("front", "back"):
        page.get_by_role("button", name=f"Submit {side} photo for review", exact=True).click()
        try:
            side_row(page, side).get_by_text("Photo submitted — awaiting staff review.", exact=True).wait_for()
        except Exception:
            assert not server.errors, server.errors
            raise
    transfers = server.transport["transfers"]
    assert not server.errors, server.errors
    assert len(transfers) == 2 and len({record["key"] for record in transfers}) == 2
    assert [record["side"] for record in transfers] == ["FRONT", "BACK"]
    assert len(transport_requests) == 4, transport_requests  # two POSTs + two owner-scoped rereads
    assert all(request["url"].startswith(server.origin + "/api/v1/owner/inventory/") for request in transport_requests)
    assert all(request["method"] in ("POST", "GET") for request in transport_requests)
    assert [request["method"] for request in server.transport["requests"]] == ["POST", "GET", "POST", "GET"]
    assert page.evaluate("cspViolations") == []
    server_item = server.transport["item"]
    assert server_item["status"] == "INSPECTION" and all(asset["approval_status"] == "PENDING" for asset in server_item["comic_photos"])
    no_photo_storage(page, front, back)
    page.remove_listener("request", capture)
    return transfers


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with fixture_server() as server, sync_playwright() as p:
        for engine in os.getenv("BROWSER_ENGINES", "chromium,webkit").split(","):
            launch = {"headless": True}
            if engine == "chromium" and os.getenv("CHROMIUM_EXECUTABLE"):
                launch["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
            browser = getattr(p, engine).launch(**launch)
            for width in (390, 1440):
                print(f"Comic listing recovery: {engine} {width}", flush=True)
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.set_default_timeout(10000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                # Do not intercept loopback traffic: the receiver checks the
                # wire bytes, even when WebKit omits File bodies in its debug
                # protocol. Only external HTTP(S) requests are blocked; blob
                # previews stay entirely inside the browser.
                page.route(re.compile(r"^(?!" + re.escape(server.origin) + r"/)https?://"), lambda route: route.abort())
                page.goto(server.origin + "/")
                assert page.evaluate("isSecureContext && !!crypto.subtle && !!crypto.randomUUID")
                # Use the deployed stylesheet order, including dark overrides.
                page.add_script_tag(content=(ROOT / "hub-session.js").read_text())
                page.add_script_tag(content=(ROOT / "reference-value-display.js").read_text())
                page.add_script_tag(content=(ROOT / "owner-inventory.js").read_text())
                page.add_script_tag(content=re.sub(r"\ninitialise\(\);\s*$", "", (ROOT / "owner-portal.js").read_text()))
                page.evaluate("window.cspViolations=[];document.addEventListener('securitypolicyviolation',e=>{if(e.violatedDirective==='connect-src')cspViolations.push(e.blockedURI);});")
                page.evaluate(FIXTURE)
                front = photo(page, "front-cover-original.png", "#a93049")
                back = photo(page, "back-cover-original.png", "#245a9e")
                expected_digests = {"FRONT": hashlib.sha256(front["buffer"]).hexdigest(), "BACK": hashlib.sha256(back["buffer"]).hexdigest()}
                choose_photos(page, front, back)
                prep = {"holding": "SELLER_HELD", "dispatch_note": "Synthetic dispatch note", "cost": "12.50",
                        "weight": "250", "length": "330", "width": "240", "height": "12"}
                for key, value in prep.items():
                    control = page.locator(f'[data-comic-field="{key}"]')
                    control.select_option(value) if key == "holding" else control.fill(value)
                no_photo_storage(page, front, back)

                # Same failure text seen on the phone, with both local choices
                # already present. Retrying must not require choosing them again.
                page.get_by_role("button", name="Submit front photo for review", exact=True).click()
                side_row(page, "front").locator(".owner-comic-upload-error").wait_for(state="visible")
                message = page.locator(".owner-item-message").inner_text()
                assert message.strip() != "Load failed" and re.search(r"retry|try again", message, re.I), message
                assert page.locator('[data-listing-step="preparation"]').is_visible()
                selected_photo(page, "front", front["name"])
                selected_photo(page, "back", back["name"])
                for key, value in prep.items():
                    assert page.locator(f'[data-comic-field="{key}"]').input_value() == value
                assert page.evaluate("currentItem.comic_photos.length") == 0
                assert page.evaluate("calls.filter(c=>c.method!=='GET').length") == 1
                assert page.locator(".owner-item-dialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1")
                no_photo_storage(page, front, back)
                page.screenshot(path=str(OUT / f"{engine}-{width}-comic-photo-retry.png"))

                page.get_by_role("button", name="Submit front photo for review", exact=True).click()
                page.wait_for_function("currentItem.comic_photos.length===1")
                page.wait_for_function("!document.querySelector('[data-comic-upload=BACK]').disabled")
                assert "awaiting staff review" in side_row(page, "front").inner_text()
                selected_photo(page, "back", back["name"])
                assert page.locator('[data-comic-field="dispatch_note"]').input_value() == prep["dispatch_note"]
                uploads = page.evaluate("uploads")
                assert len(uploads) == 2
                assert uploads[0]["key"] == uploads[1]["key"] and uploads[0]["digest"] == uploads[1]["digest"] == expected_digests["FRONT"]
                assert uploads[0]["filename"] == uploads[1]["filename"] == front["name"]
                assert uploads[0]["version"] == uploads[1]["version"] == 1
                page.get_by_role("button", name="Submit back photo for review", exact=True).click()
                page.wait_for_function("currentItem.comic_photos.length===2")
                page.get_by_role("button", name="Save preparation details", exact=True).wait_for(state="visible")
                page.wait_for_function("document.querySelectorAll('.owner-comic-photo-row input[type=file]').length===0")
                assert all("awaiting staff review" in side_row(page, side).inner_text() for side in ("front", "back"))
                uploads = page.evaluate("uploads")
                assert len(uploads) == 3 and len({item["key"] for item in uploads}) == 2
                assert uploads[2]["side"] == "BACK" and uploads[2]["version"] == 2
                assert uploads[2]["digest"] == expected_digests["BACK"]
                assert page.evaluate("currentItem.status") == "INSPECTION"
                assert page.evaluate(r"calls.some(c=>/upload-target|comic-photo\/complete|\/sync|approval-request/.test(c.url))") is False
                page.screenshot(path=str(OUT / f"{engine}-{width}-comic-photos-pending.png"))

                # Save reported preparation, price, then explicitly request
                # review for this same physical copy and its current version.
                page.get_by_role("button", name="Save preparation details", exact=True).click()
                page.wait_for_function("currentItem.version===4")
                page.wait_for_function("!document.querySelector('.owner-item-dialog header button').disabled")
                writes = page.evaluate("calls.filter(c=>c.method!=='GET')")
                prepared = json.loads(next(call["body"] for call in writes if call["url"].endswith("/comic-preparation")))
                assert prepared == {"version": 3, "holding": "SELLER_HELD", "dispatch_note": prep["dispatch_note"],
                                    "acquisition_cost_minor": 1250, "parcel_weight_grams": 250,
                                    "parcel_length_mm": 330, "parcel_width_mm": 240, "parcel_height_mm": 12}
                page.get_by_role("button", name="3. Price", exact=True).click()
                page.get_by_label("Your selling price in pounds", exact=True).fill("15.00")
                page.get_by_role("button", name="Save selling price", exact=True).click()
                page.wait_for_function("currentItem.version===5")
                page.wait_for_function("!document.querySelector('.owner-item-dialog header button').disabled")
                page.get_by_role("button", name="4. Review", exact=True).click()
                assert "INV-COMIC-FIXTURE" in page.locator(".owner-listing-review-facts").inner_text()
                assert "15.00" in page.locator(".owner-listing-review-facts").inner_text()
                review_status = page.locator(".owner-comic-review-status").inner_text()
                assert "Your required preparation details and photos are saved for review." in review_status
                assert "Drop Rate checks" in review_status
                assert "Awaiting Drop Rate review — not live yet" in page.locator(".owner-item-channel-shopify").inner_text()
                assert "In review" in page.locator(".owner-item-channel-shopify").inner_text()
                assert not page.evaluate("calls.some(c=>c.url.endsWith('/approval-request'))")
                page.get_by_role("button", name="Update listing request", exact=True).click()
                page.wait_for_function("currentItem.version===6")
                requests = page.evaluate("calls.filter(c=>c.url.endsWith('/approval-request'))")
                assert len(requests) == 1 and FIRST in requests[0]["url"]
                assert json.loads(requests[0]["body"]) == {"version": 5, "store_price_minor": 1500, "condition": "Mint"}
                assert not page.evaluate(r"calls.some(c=>/\/sync|\/intake/.test(c.url))")
                assert page.evaluate("currentItem.status==='INSPECTION'&&currentItem.comic_photos.every(p=>p.approval_status==='PENDING')")

                # A lost HTTP response after receipt must reconcile the saved
                # side from GET, without asking for a duplicate upload.
                page.evaluate("freshComic()")
                choose_photos(page, front, back)
                page.locator('[data-comic-field="dispatch_note"]').fill(prep["dispatch_note"])
                previous_uploads = page.evaluate("uploads.length")
                page.evaluate("uploadMode='commit-then-lost'")
                page.get_by_role("button", name="Submit front photo for review", exact=True).click()
                side_row(page, "front").get_by_text("Photo submitted — awaiting staff review.", exact=True).wait_for()
                assert "photo received" in page.locator(".owner-item-message").inner_text().lower()
                assert page.get_by_role("button", name="Submit front photo for review", exact=True).count() == 0
                assert page.locator(".owner-item-message.error").count() == 0
                assert page.evaluate("uploads.length") == previous_uploads + 1
                assert page.evaluate("currentItem.version===2&&currentItem.comic_photos.length===1")
                selected_photo(page, "back", back["name"])
                assert page.locator('[data-comic-field="dispatch_note"]').input_value() == prep["dispatch_note"]

                # Selected evidence and changed preparation cannot disappear
                # behind a successful-looking review request.
                before_review = page.evaluate("calls.filter(c=>c.url.endsWith('/approval-request')).length")
                page.get_by_role("button", name="4. Review", exact=True).click()
                assert "Your next steps" in page.locator(".owner-comic-review-status").inner_text()
                assert "Drop Rate checks" in page.locator(".owner-comic-review-status").inner_text()
                page.get_by_role("button", name="Update listing request", exact=True).click()
                assert page.locator('[data-listing-step="preparation"]').is_visible()
                assert "Submit your selected photos" in page.locator(".owner-item-message").inner_text()
                selected_photo(page, "back", back["name"])
                assert page.evaluate("calls.filter(c=>c.url.endsWith('/approval-request')).length") == before_review
                page.evaluate("freshComic()")
                page.locator('[data-comic-field="dispatch_note"]').fill(prep["dispatch_note"])
                page.get_by_role("button", name="4. Review", exact=True).click()
                page.get_by_role("button", name="Update listing request", exact=True).click()
                assert page.locator('[data-listing-step="preparation"]').is_visible()
                assert "Save your preparation details" in page.locator(".owner-item-message").inner_text()
                assert page.locator('[data-comic-field="dispatch_note"]').input_value() == prep["dispatch_note"]
                assert page.evaluate("calls.filter(c=>c.url.endsWith('/approval-request')).length") == before_review

                # Buffers live only in this open, account/identity-scoped dialog.
                page.evaluate("freshComic()")
                choose_photos(page, front, back)
                page.get_by_role("button", name="Close item details", exact=True).click()
                page.evaluate("DropRateInventory.open(currentItem,{selling:true,step:'preparation'})")
                no_staged_photos(page, front, back)
                choose_photos(page, front, back)
                page.evaluate("""async()=>{currentItem={...currentItem,id:'00000000-0000-4000-8000-000000000112'};
                  await DropRateInventory.open(currentItem,{selling:true,step:'preparation'});} """)
                no_staged_photos(page, front, back)
                choose_photos(page, front, back)
                page.evaluate("""async()=>{currentItem={...currentItem,catalogue_id:'a-different-printing',version:2};
                  await DropRateInventory.open(currentItem,{selling:true,step:'preparation'});} """)
                no_staged_photos(page, front, back)
                choose_photos(page, front, back)
                page.evaluate("""async()=>{state.session={access_token:'another-synthetic-account',user:{id:'seller-b'}};
                  await DropRateInventory.open(currentItem,{selling:true,step:'preparation'});} """)
                no_staged_photos(page, front, back)
                no_photo_storage(page, front, back)
                wire_transfers = real_transport(page, front, back, server)
                assert not errors, errors
                results.append({"engine": engine, "width": width, "passed": True,
                                "scenarios": ["failure before receipt retains both files, consents and preparation",
                                              "byte-identical retry retains key; other side uses current version",
                                              "preparation, price and explicit review target the same copy",
                                              "lost response reconciles received photo without duplicate upload",
                                              "unsent photos and unsaved preparation block review with recovery",
                                              "close, item, printing and account changes discard photo buffers",
                                              "actual authenticated raw File transport obeys same-origin CSP"],
                                "wire_transfers": wire_transfers,
                                "publication_requests": 0, "photo_storage_writes": 0, "javascript_errors": 0})
                page.close()
            browser.close()
    (OUT / "comic-listing-recovery-results.json").write_text(json.dumps(results, indent=2))
    print(f"PASS: {len(results)} comic recovery browser cases; before/after-receipt recovery, byte-identical retry, review guards, memory-only isolation, actual same-origin raw File transport and no publication writes.")


if __name__ == "__main__":
    main()
