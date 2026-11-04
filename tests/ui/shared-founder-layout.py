"""Render the shared founder dashboard with local fixtures, never production data."""
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/app/static"
OUT = Path("/tmp/drop-rate-business-layout/shared-founder")
SIZES = [(320, 680), (390, 844), (768, 900), (1440, 1000)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = (STATIC / "owner.html").read_text()
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", source, flags=re.S | re.I)
    scripts = re.findall(r'<script src="/assets/([^"?]+)[^"]*"', source)
    records = []
    with sync_playwright() as p:
        for engine in ("chromium", "webkit"):
            browser = getattr(p, engine).launch()
            for width, height in SIZES:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.set_default_timeout(10000)

                def serve(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != "shared-founder.test":
                        return route.abort()
                    if url.path == "/owner":
                        return route.fulfill(content_type="text/html", body=html)
                    file = (STATIC / url.path.removeprefix("/assets/")).resolve()
                    if STATIC.resolve() in file.parents and file.is_file():
                        return route.fulfill(
                            content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                            body=file.read_bytes(),
                        )
                    route.abort()

                try:
                    page.route("**/*", serve)
                    page.goto("http://shared-founder.test/owner", wait_until="load")
                    page.evaluate("window.fetch=async()=>({ok:true,json:async()=>({items:[]})})")
                    for name in scripts:
                        content = (STATIC / name).read_text()
                        if name == "owner-portal.js":
                            content = re.sub(r"\ninitialise\(\);\s*$", "\n", content)
                        page.add_script_tag(content=content)
                    page.evaluate("""async()=>{
                        state.session={access_token:'local-fixture',user:{id:'founder'}};
                        apiRequest=async url=>{
                          if(url==='/api/v1/access/me')return {access:{access_role:'PLATFORM_ADMIN',portal:'FOUNDER_HQ',founder_hq_allowed:true,business_allowed:true,display_name:'Founder'}};
                          if(url==='/api/v1/founder/accounts')return {own_owner_id:'founder',accounts:[{id:'founder',display_name:'Founder',owner_type:'FOUNDER',username:'founder',active_stock_count:10,for_sale_count:7,draft_count:3,unvalued_count:3},{id:'seller',display_name:'Independent seller with a longer account name',owner_type:'CONSIGNOR',username:'seller',active_stock_count:4,draft_count:4,unvalued_count:4}]};
                          if(url.includes('/api/v1/founder/accounts/inventory'))return {items:[{owner_id:'seller',owner_name:'Independent seller',inventory_code:'INV-SYNTHETIC-LONG-000001',name:'An exact card with a longer variant title',game:'One Piece',set_name:'Synthetic set',card_number:'OP01-001',language:'Japanese',grading_company:'BGS',grade:'9.5',variant:'Alternate art',status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',market_value_minor:null,store_price_minor:null}],total:1};
                          return {items:[],total:0,sales:[],payouts:[]};
                        };
                        reloadOwnerDashboard=loadOwnerInventory=loadOwnerChannels=async()=>{};
                        await openOwnerPortal();activateOwnerView('settings');
                    }""")
                    page.locator(".founder-settings-entry").click()
                    page.locator(".business-kpi").first.wait_for()
                    assert page.locator(".founder-control-card").count() == 8
                    assert page.locator(".owner-nav-item:visible").count() == 5
                    for mode in ("overview", "sellers", "inventory", "activity"):
                        if mode != "overview":
                            page.locator(f"#business-tab-{mode}").click()
                        target = {"overview": ".business-kpi", "sellers": ".business-seller-card", "inventory": ".business-table", "activity": ".business-empty"}[mode]
                        page.locator(target).first.wait_for()
                        assert page.locator("#owner-view-founders").evaluate("el=>el.scrollWidth<=el.clientWidth+1"), (engine, width, mode, "panel overflow")
                        for control in page.locator(".founder-control-card,.business-filters input:visible,.business-filters select:visible").all():
                            box = control.bounding_box()
                            assert box and box["x"] >= -1 and box["x"] + box["width"] <= width + 1, (engine, width, mode, box)
                        if width in (390, 1440):
                            page.screenshot(path=str(OUT / f"{engine}-{width}-{mode}.png"), full_page=True)
                    page.locator("#owner-view-founders > .workspace-back").click()
                    assert page.locator(".founder-settings-entry").is_visible()
                    page.evaluate("clearSession()")
                    assert not page.locator(".founder-settings-entry").is_visible()
                    assert not errors, errors
                    records.append({"engine": engine, "width": width, "passed": True})
                except Exception:
                    page.screenshot(path=str(OUT / f"FAIL-{engine}-{width}.png"), full_page=True)
                    (OUT / f"FAIL-{engine}-{width}.html").write_text(page.content())
                    (OUT / f"FAIL-{engine}-{width}-errors.json").write_text(json.dumps(errors))
                    raise
                finally:
                    page.close()
            browser.close()
    (OUT / "results.json").write_text(json.dumps(records, indent=2))
    print(f"PASS: {len(records)} shared-founder Chromium/WebKit layouts, Settings entry, eight links, contained controls, logout. Local fixtures only.")


if __name__ == "__main__":
    main()
