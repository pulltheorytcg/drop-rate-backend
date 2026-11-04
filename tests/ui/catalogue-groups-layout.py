"""Offline real-CSS/JS catalogue grouping regression with synthetic references.

No account, cloud browser, API or production data is used. All requests are
fulfilled from local assets or aborted. Screenshots are temporary test outputs.
Run: BROWSER_ENGINES=chromium .venv/bin/python tests/ui/catalogue-groups-layout.py
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/app/static"
SIZES = [(320, 800), (390, 844), (768, 900), (1440, 1000)]
GROUPS = {
    "COMICS": ["MARVEL", "DC", "INDIE", "OTHER"],
    "MANGA": ["SHONEN", "SHOJO", "SEINEN", "JOSEI", "KODOMO", "UNKNOWN"],
    "SPORTS": ["PANINI", "TOPPS", "OTHER"],
    "FIGURES": ["FUNKO_POP", "FIGURINES", "OTHER"],
}
SYSTEMS = {"COMICS": "COMICS", "MANGA": "MANGA", "SPORTS": "SPORTS_CARDS", "FIGURES": "FIGURES"}


def main():
    output = Path(os.getenv("CATALOGUE_GROUP_LAYOUT_DIR") or tempfile.mkdtemp(prefix="drop-rate-catalogue-groups-"))
    output.mkdir(parents=True, exist_ok=True)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", (STATIC / "owner.html").read_text(), flags=re.S | re.I)
    results = []
    with sync_playwright() as playwright:
        for engine in os.getenv("BROWSER_ENGINES", "chromium").split(","):
            browser = getattr(playwright, engine).launch(headless=True)
            for width, height in SIZES:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route_request(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != "catalogue-groups.test":
                        route.abort()
                    elif url.path == "/owner":
                        route.fulfill(status=200, content_type="text/html", body=html)
                    elif url.path.startswith("/assets/"):
                        asset = (STATIC / url.path.removeprefix("/assets/")).resolve()
                        if STATIC.resolve() not in asset.parents or not asset.is_file():
                            route.fulfill(status=404, body="")
                        else:
                            route.fulfill(status=200, body=asset.read_bytes(),
                                content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("http://catalogue-groups.test/owner", wait_until="load")
                for name in ("reference-value-display.js", "catalogue-browser.js"):
                    page.add_script_tag(content=(STATIC / name).read_text())
                page.evaluate("""async () => {
                    document.body.classList.remove('hub-restoring');
                    document.body.classList.add('collector-workspace');
                    document.querySelector('.hub-loading')?.remove();
                    document.getElementById('owner-auth-view').classList.add('hidden');
                    document.getElementById('owner-portal-view').classList.remove('hidden');
                    document.querySelectorAll('[data-owner-view-panel]').forEach(panel=>
                        panel.classList.toggle('hidden',panel.dataset.ownerViewPanel!=='search'));
                    window.fixtureCalls=[];
                    window.fixtureLastQuery={};
                    const client={owner:'synthetic-layout-only',active:()=>true,request:async(url,options={})=>{
                        if(options.method && options.method!=='GET')throw new Error('Layout test attempted a write');
                        fixtureCalls.push({url,method:options.method||'GET'});
                        if(url.includes('/saved'))return {keys:[]};
                        if(url.endsWith('/games'))return {items:[
                            {system_code:'POKEMON_TCG',game:'Pokémon',languages:['English']},
                            {system_code:'COMICS',game:'Comics',languages:['English']},
                            {system_code:'MANGA',game:'Manga',languages:['English','Japanese']}]};
                        const query=new URL(url,'http://catalogue-groups.test').searchParams;
                        fixtureLastQuery=Object.fromEntries(query);
                        const category=query.get('category')||'TCG';
                        const system=query.get('system_code')||'POKEMON_TCG';
                        const group=query.get('browse_group')||'All';
                        const type=category==='FIGURES'?'FIGURE':['COMICS','MANGA'].includes(category)?'COMIC':'CARD';
                        return {items:Array.from({length:24},(_,index)=>({
                            key:'c:00000000-0000-4000-8000-'+String(index+1).padStart(12,'0'),
                            catalogue_id:'00000000-0000-4000-8000-'+String(index+1).padStart(12,'0'),
                            name:`Fixture ${category} ${group} item ${index+1}`,
                            system_code:system,product_type:type,source_kind:'CATALOGUE',
                            set_id:'fixture-series',set_name:'Synthetic reference series',card_number:String(index+1),
                            language:type==='FIGURE'?null:'English',variant:'',owned_quantity:0,
                            market_value_minor:null,image_url:null,
                            ...(type==='COMIC'?{book_details:{system_code:system,series_title:'Fixture series',issue_number:String(index+1)}}:{})
                        })),has_more:false,total_count:24};
                    }};
                    window.fixtureBrowser=new DropRateCatalogue.Browser({
                        host:document.getElementById('owner-view-search'),client,
                        navigate:()=>{},scan:()=>{},graded:()=>{},books:()=>{},collectibles:()=>{},afterSave:async()=>{}
                    });
                    await fixtureBrowser.open();
                }""")
                for category, groups in GROUPS.items():
                    page.evaluate("window.scrollTo(0,0)")
                    page.locator(f'.dr-browse-categories [data-category="{category}"]').click()
                    page.wait_for_function("category=>fixtureLastQuery.category===category && !fixtureBrowser.loading", arg=category)
                    assert page.evaluate("fixtureLastQuery.browse_group || ''") == "", (engine, width, category, "stale group")
                    assert page.evaluate("fixtureLastQuery.system_code") == SYSTEMS[category]
                    nav = page.locator(".dr-browse-groups")
                    assert nav.is_visible()
                    assert nav.locator("button").count() == len(groups) + 1
                    assert nav.evaluate("el=>['auto','scroll'].includes(getComputedStyle(el).overflowX)")
                    for button in nav.locator("button").all():
                        assert button.bounding_box()["height"] >= 44, (engine, width, category, button.inner_text())
                    for button in page.locator(".dr-browse-categories button").all():
                        assert button.bounding_box()["height"] >= 44
                    horizontal_overflow = nav.evaluate("el=>el.scrollWidth>el.clientWidth+1")
                    if width <= 390:
                        assert horizontal_overflow, (engine, width, category, "groups should scroll within their row")
                    if horizontal_overflow:
                        nav.evaluate("el=>el.scrollLeft=el.scrollWidth")
                        assert nav.evaluate("el=>el.scrollLeft>0")
                        last = nav.locator("button").last
                        assert last.bounding_box()["x"] + last.bounding_box()["width"] <= nav.bounding_box()["x"] + nav.bounding_box()["width"] + 1
                    for group in groups:
                        control = nav.locator(f'[data-browse-group="{group}"]')
                        control.click()
                        page.wait_for_function("group=>fixtureLastQuery.browse_group===group && !fixtureBrowser.loading", arg=group)
                        assert control.get_attribute("aria-pressed") == "true"
                        assert nav.locator('[aria-pressed="true"]').count() == 1
                        assert page.evaluate("fixtureLastQuery.offset") == "0"
                        assert page.evaluate("fixtureLastQuery.system_code") == SYSTEMS[category]
                    search = page.locator('.dr-browse-searchbar input[type="search"]')
                    search.fill("Fixture")
                    search.press("Enter")
                    page.wait_for_function("fixtureLastQuery.q==='Fixture' && !fixtureBrowser.loading")
                    assert page.evaluate("fixtureLastQuery.browse_group") == groups[-1]
                    assert page.locator(".dr-browse-product").count() == 24
                    page.evaluate("window.scrollTo(0,0)")
                    bounds = page.locator(".dr-browse-scroll").bounding_box()
                    # The real embedded layout scrolls the page, not a tiny
                    # nested pane: at least 100px of results must be visible.
                    bottom = page.locator(".owner-sidebar").bounding_box()
                    visible_bottom = bottom["y"] if width <= 1000 and bottom else height
                    assert visible_bottom - bounds["y"] >= 100, (engine, width, category, bounds, visible_bottom)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), (engine, width, category, "page overflow")
                    assert page.locator(".dr-browser").evaluate("el=>el.scrollWidth<=el.clientWidth+1")
                    assert page.locator(".dr-browse-content").evaluate("el=>el.scrollHeight>200")
                    page.screenshot(path=str(output / f"{engine}-{width}-{category.lower()}.png"))
                    results.append({"engine":engine,"width":width,"category":category,"groups":len(groups),
                        "horizontal_group_scroll":horizontal_overflow,"visible_results_px":round(visible_bottom-bounds["y"]),"passed":True})
                page.locator('.dr-browse-categories [data-category="TCG"]').click()
                page.wait_for_function("fixtureBrowser.categoryId==='TCG' && !fixtureBrowser.loading")
                assert page.locator(".dr-browse-groups").is_hidden()
                assert page.evaluate("fixtureBrowser.filters.browse_group") == ""
                assert page.evaluate("fixtureCalls.every(call=>call.method==='GET')")
                assert not errors, errors
                context.close()
            browser.close()
    print(json.dumps({"checks":results,"screenshots":str(output),"production_requests":0}, indent=2))


if __name__ == "__main__":
    main()
