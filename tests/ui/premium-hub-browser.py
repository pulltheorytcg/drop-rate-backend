"""Offline premium Hub layout checks using real HTML/assets and synthetic data.

This never signs in to production, calls a provider or saves real inventory.
Run with an installed Playwright Chromium browser. PREVIEW_OUTPUT can point to
a scratch evidence directory; all displayed quantities/prices are fixtures.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "backend/app/static"
OUT = Path(os.environ.get("PREVIEW_OUTPUT", "/tmp/drop-rate-premium-hub"))
ORIGIN = "https://premium-hub.test"

ITEMS = [
    {
        "id": f"00000000-0000-4000-8000-{index:012d}",
        "inventory_code": f"INV-PREVIEW-{index:04d}",
        "catalogue_id": f"fixture-reference-{index}",
        "version": 1,
        "status": "DRAFT",
        "sale_intent": "PERSONAL_COLLECTION",
        "product_type": kind,
        "game": game,
        "name": name,
        "set_name": set_name,
        "card_number": number,
        "language": "Japanese" if index == 4 else "English",
        "condition": "Near Mint" if kind == "CARD" else None,
        "seal_status": "SEALED" if kind == "SEALED" else None,
        "market_value_minor": value,
        "store_price_minor": None,
        "reference_image_path": f"/api/v1/owner/inventory/00000000-0000-4000-8000-{index:012d}/reference-image",
        "fixture_art": art,
    }
    for index, name, game, set_name, number, kind, value, art in [
        (1, "Umbreon VMAX", "Pokémon", "Evolving Skies", "215/203", "CARD", 85000, "grail-art/umbreon-vmax-215.webp"),
        (2, "Monkey.D.Luffy", "One Piece", "Awakening of the New Era", "OP05-119", "CARD", 125000, "grail-art/luffy-op05-119-p2.png"),
        (3, "Son Goku", "Dragon Ball", "Awakened Pulse", "FB01-139", "CARD", None, "grail-art/goku-fb01-139-p2.webp"),
        (4, "World’s Strongest Warriors booster pack", "One Piece", "World’s Strongest Warriors", "OP-17", "SEALED", 866, "collection-photos/one-piece-op17-sealed.webp"),
    ]
]


def render_weekly_fixture(page, founder=False):
    """Keep populated evidence rows in the contrast and narrow-layout sweep."""
    summary = {
        "status": "READY", "scope": "OWN_COLLECTION", "window_days": 7,
        "owned_item_count": 4, "current_value_item_count": 3, "current_value_product_count": 3,
        "comparable_product_count": 2, "comparable_item_count": 2, "mover_product_count": 2,
        "unchanged_product_count": 0, "needs_details_item_count": 0, "stale_item_count": 0,
        "guide_comparison_count": 1, "history_ready": True,
        "earliest_baseline_at": "2026-10-27T06:00:00Z", "latest_current_at": "2026-11-03T12:00:00Z",
    }
    guide = {
        **ITEMS[0], "inventory_id": ITEMS[0]["id"], "quantity": 1,
        "current_value_minor": 85000, "baseline_value_minor": 80000,
        "current_market_value_minor": 85000, "prior_market_value_minor": 80000,
        "change_minor": 5000, "change_pct": 6.25,
        "current_at": "2026-11-03T12:00:00Z", "baseline_at": "2026-10-27T06:00:00Z",
        "comparison_days": 7.25, "comparison_kind": "GUIDE_ESTIMATE",
        "comparison_label": "Guide estimate change", "method": "CATALOGUE_CARDMARKET_V1",
    }
    sold = {
        **guide, **ITEMS[1], "inventory_id": ITEMS[1]["id"],
        "name": "Monkey.D.Luffy — Awakening of the New Era, Special Alternate Art",
        "current_value_minor": 125000, "baseline_value_minor": 130000,
        "current_market_value_minor": 125000, "prior_market_value_minor": 130000,
        "change_minor": -5000, "change_pct": -3.85,
        "comparison_kind": "SOLD_MARKET", "comparison_label": "Market value change", "method": "CATALOGUE_EBAY_V4",
    }
    page.evaluate("""({founder,summary,guide,sold})=>{
        if(founder)renderWeeklyMovers({...summary,gainers:[guide],decliners:[sold]},7);
        else renderOwnerInsightList('owner-weekly-movers',[guide,sold],true,summary);
    }""", {"founder": founder, "summary": summary, "guide": guide, "sold": sold})


def source_html(name: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / name).read_text(), flags=re.S | re.I)


def install_routes(page, name: str):
    def serve(route):
        url = urlsplit(route.request.url)
        if url.hostname != "premium-hub.test":
            return route.abort()
        if url.path in ("/owner", "/app", "/owner/join", "/join"):
            return route.fulfill(content_type="text/html", body=source_html(name))
        if url.path.startswith("/assets/"):
            file = (ROOT / url.path.removeprefix("/assets/")).resolve()
            if ROOT.resolve() in file.parents and file.is_file():
                return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        if url.path.endswith("/reference-image"):
            item_id = url.path.split("/")[-2]
            item = next((row for row in ITEMS if row["id"] == item_id), None)
            if item:
                assert route.request.headers.get("authorization") == "Bearer offline-preview"
                file = ROOT / item["fixture_art"]
                return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0])
        return route.abort()
    page.route(re.compile(r"^https?://"), serve)


def script(page, filename: str):
    code = (ROOT / filename).read_text()
    if filename in ("owner-portal.js", "app.js"):
        code = re.sub(r"\ninitialise\(\);\s*$", "\n", code)
    page.add_script_tag(content=code)


def owner_fixture(page):
    install_routes(page, "owner.html")
    page.goto(ORIGIN + "/owner")
    filenames = re.findall(r'<script src="/assets/([^"?]+)', (ROOT / "owner.html").read_text())
    for filename in dict.fromkeys(filenames):
        script(page, filename)
    page.evaluate("""items => {
        document.body.classList.remove('hub-restoring');
        byId('owner-auth-view').classList.add('hidden');
        byId('owner-portal-view').classList.remove('hidden');
        document.title='Synthetic preview · Drop Rate Seller Hub';
        state.session={access_token:'offline-preview',user:{id:'preview-owner',email:'preview@example.test',email_confirmed_at:'2026-10-01T10:00:00Z'}};
        window.previewItems=items;window.previewWrites=[];
        apiRequest=async (url, options={}) => {
            if(options.method && options.method!=='GET') {
                previewWrites.push({url,options});throw Error('Fixture blocks writes');
            }
            if(url.startsWith('/api/v1/fulfilment/to-ship?'))return {total:1,limit:25,offset:0,
                capabilities:{carrier_label_purchase:false,dispatch_confirmation:false,shopify_tracking_sync:false,buyer_address_access:false},
                items:[{order_item_id:'00000000-0000-4000-8000-000000000005',order_number:'#PREVIEW-001',order_status:'PAID',
                    inventory_code:'INV-PREVIEW-0004',card_name:'World’s Strongest Warriors booster pack',set_name:'World’s Strongest Warriors',
                    net_sale_minor:866,blockers:['PHYSICAL_SHIPPER_UNVERIFIED','CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED'],
                    state:'AWAITING_DISPATCH_SETUP',can_buy_label:false,can_confirm_dispatched:false}]};
            if(url.endsWith('/shipping-cost'))return {source:'OWNER_NET_POSTAGE_POLICY',currency:'GBP',net_shipping_charge_minor:0,
                shipping_charge_status:'NO_SELLER_CHARGE',automatic:true,purchase_allowed:false};
            if(url.endsWith('/shopify'))return {shopify_connected:true,state:'REVIEW_REQUIRED',
                blockers:['PHYSICAL_SHIPPER_UNVERIFIED','SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING'],can_buy_label:false,can_confirm_dispatched:false};
            if(url.includes('/imports'))return {items:[]};
            if(url.endsWith('/catalogue-browser/saved'))return {keys:[]};
            if(url.includes('/owner/profile'))return {profile:{display_name:'Preview collector',username:'preview_collector',owner_type:'CONSIGNOR',membership_created_at:'2026-10-01',commission_bps:500}};
            if(url.includes('/finance/sales'))return {total:1,items:[{sold_at:'2026-11-01',name:'Synthetic One Piece card',source:'SHOPIFY',order_number:'#PREVIEW-001',net_sale_minor:10000,commission_minor:500,owner_proceeds_minor:9500,financials_complete:true}]};
            if(url.includes('/finance/settlements'))return {total:1,items:[{placed_at:'2026-11-01',source:'SHOPIFY',order_number:'#PREVIEW-001',sales_revenue_minor:10000,item_count:1,commission_minor:500,owner_proceeds_minor:9500,financials_complete:true}]};
            const item=items.find(row=>url.endsWith('/'+row.id))||items[0];
            return {item,copies:[item],items,total:items.length,summary:{}};
        };
        loadOwnerInventory=loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=async()=>{};
        byId('owner-portal-name').textContent='Preview collector';
        byId('owner-portal-initial').textContent='P';
        byId('owner-portal-email').textContent='preview@example.test';
        byId('owner-overview-name').textContent='Preview collector';
        byId('owner-total-inventory').textContent='4';
        byId('owner-market-value').textContent='£2,108.66';
        byId('owner-market-value-label').textContent='Known market value · partial';
        byId('owner-inventory-type-note').textContent='3 cards · 1 sealed product';
        byId('owner-market-value-note').textContent='3 of 4 valued · 1 awaiting eligible prices';
        byId('owner-next-payout-date').textContent='Manual payout';
        byId('owner-next-payout-status').textContent='No payout scheduled';
        byId('owner-next-payout-amount').textContent='—';
        byId('owner-overview-balance').textContent='£0.00';
        byId('owner-store-value').textContent='Not set';
        byId('owner-sold-count').textContent='0';
        renderOverviewLatestInventory(items);
        renderInventoryCards(items);renderInventoryRows(items);
        state.inventory.total=items.length;
        byId('owner-inventory-total-label').textContent=String(items.length);
        renderInventoryPagination();
        window.previewCatalogueRequests=[];
        window.previewClient={owner:'preview-owner',active:()=>true,request:async url=>{window.previewCatalogueRequests.push(url);if(url.endsWith('/saved'))return {keys:[]};return {items:url.endsWith('/games')?
            [['POKEMON_TCG','Pokémon'],['ONE_PIECE_CARD_GAME','One Piece'],['DRAGON_BALL_SUPER_MASTERS','Dragon Ball Super Masters'],
             ['DRAGON_BALL_SUPER_FUSION_WORLD','Dragon Ball Super Fusion World'],['NARUTO','Naruto'],['COMICS','Comics'],['MANGA','Manga']]
                .map(([system_code,game])=>({system_code,game,languages:['English','Japanese']})):[],has_more:false};}};
        ownerSharedScanner=()=>window.previewClient;
        activateOwnerView('overview',false);
        document.dispatchEvent(new Event('hub-ready'));
    }""", ITEMS)
    render_weekly_fixture(page)


def founder_fixture(page):
    install_routes(page, "index.html")
    page.goto(ORIGIN + "/app")
    filenames = re.findall(r'<script src="/assets/([^"?]+)', (ROOT / "index.html").read_text())
    filenames += re.findall(r"'<script src=\"/assets/([^\"?]+)[^\"]*\" defer", (REPO / "backend/app/main.py").read_text())
    for filename in dict.fromkeys(filenames):
        script(page, filename)
    page.evaluate("""({items,origin}) => {
        document.body.classList.remove('hub-restoring');
        byId('auth-view').classList.add('hidden');
        byId('dashboard-view').classList.remove('hidden');
        document.title='Synthetic founder preview · Drop Rate Seller Hub';
        state.session={access_token:'offline-preview',user:{id:'preview-founder'}};
        window.previewWrites=[];
        apiRequest=async (url,options={}) => {
            if(options.method && options.method!=='GET') {
                previewWrites.push({url,options});throw Error('Fixture blocks writes');
            }
            if(url==='/api/v1/condition-review/queue')return {counts:{needs_review:1},items:[{
                id:'00000000-0000-4000-8000-000000000006',name:'Synthetic Charizard photo review',
                inventory_code:'INV-PREVIEW-MEDIA',set_name:'Synthetic review fixture',language:'English',is_graded:true,
                grading_company:'PSA',grade:'10',photo_ready:false,review_ready:false,condition_review_status:'PENDING',
                front_image_url:origin+'/assets/collection-photos/charizard-psa10-front.webp',front_capture_context:'GRADED_SLAB',
                back_image_url:null,back_capture_context:null}]};
            return {items:[],total:0,unlocated_count:4,summary:{},owner:{display_name:'Preview founder',email:'preview@example.test'}};
        };
        loadInventory=async()=>{};
        const data=items.map(item=>({...item,currency:'GBP',card_image_url:'fixture',card_image_direct_url:origin+'/assets/'+item.fixture_art}));
        renderInventory({total:data.length,items:data,owner:{display_name:'Preview founder',email:'preview@example.test'}});
        renderReadiness({total:4,for_sale:0,approved:0,approval_ready:0,personal_collection:4});
        setInventoryView('visual');
        activateSellerView('dashboard',false);
    }""", {"items": ITEMS, "origin": ORIGIN})
    render_weekly_fixture(page, founder=True)


def settle_images(page):
    page.evaluate("""async()=>{
        await document.fonts.ready;
        await Promise.all([...document.images].filter(img=>img.getBoundingClientRect().width>0)
            .map(img=>img.decode().catch(()=>{})));
        await Promise.all(document.getAnimations().filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>{})));
    }""")


def text_contrast(page):
    """Approximate foreground/ancestor colour sweep; images/gradients need review."""
    return page.evaluate("""() => {
        const rgb=s=>{const v=s.match(/[\\d.]+/g)?.map(Number)||[0,0,0];return [...v.slice(0,3),v[3]??1]};
        const over=(a,b)=>a.slice(0,3).map((c,i)=>c*a[3]+b[i]*(1-a[3])).concat(1);
        const bg=e=>{const layers=[];for(let n=e;n;n=n.parentElement)layers.push(rgb(getComputedStyle(n).backgroundColor));
            return layers.reverse().reduce((b,a)=>over(a,b),[8,15,28,1]);};
        const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
        const root=document.querySelector('dialog[open]')||document.body;
        const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT), findings=[],seen=new Set();
        for(let node=walker.nextNode();node;node=walker.nextNode()) {
            const e=node.parentElement,text=node.textContent.trim();
            if(!e||!text||e.closest('script,style,option,[aria-hidden="true"],.sr-only'))continue;
            const s=getComputedStyle(e),r=e.getBoundingClientRect();
            if(!r.width||!r.height||s.visibility!=='visible'||s.opacity==='0')continue;
            if(e.closest('button:disabled,input:disabled,select:disabled,textarea:disabled'))continue;
            const back=bg(e),front=over(rgb(s.color),back),ls=[lum(back),lum(front)].sort((a,b)=>a-b);
            const contrast=+((ls[1]+.05)/(ls[0]+.05)).toFixed(2);
            if(contrast>=4.5)continue;
            const key=[e.id,e.className,text].join('|');if(seen.has(key))continue;seen.add(key);
            let imageBackground=false;for(let p=e;p;p=p.parentElement)if(getComputedStyle(p).backgroundImage!=='none')imageBackground=true;
            findings.push({tag:e.tagName,id:e.id,cls:typeof e.className==='string'?e.className:'',text:text.slice(0,100),
                color:s.color,effectiveBackground:back.slice(0,3),contrast,fontSize:s.fontSize,fontWeight:s.fontWeight,
                largeText:parseFloat(s.fontSize)>=24||(parseFloat(s.fontSize)>=18.66&&parseFloat(s.fontWeight)>=700),imageBackground});
        }
        return findings;
    }""")


def inspect_navigation(page, founder=False):
    return page.evaluate("""founder=>{
        const primary=[...document.querySelectorAll(founder?'.seller-nav-tab':'.owner-nav-item')];
        const active=primary.filter(e=>e.getAttribute(founder?'aria-selected':'aria-current')===(founder?'true':'page'));
        const buttons=primary.map(e=>{const r=e.getBoundingClientRect();return {label:e.textContent.trim(),role:e.getAttribute('role'),
            width:r.width,height:r.height,top:r.top,bottom:r.bottom,left:r.left,right:r.right}});
        const secondary=document.querySelector('.workspace-secondary-nav');
        return {count:primary.length,active:active.length,buttons,secondaryHidden:!secondary||!secondary.getBoundingClientRect().height,
            tablists:document.querySelectorAll('.seller-nav [role="tablist"]').length,
            ownerHasFounderBusiness:!founder&&Boolean(document.querySelector('[data-owner-jump="accounts"], [data-owner-view-panel="accounts"]'))};
    }""", founder)


def inspect(page, surface: str, selectors: list[str]):
    page.mouse.move(0, 0)
    result = page.evaluate("""({surface,selectors}) => {
        const rgb=s=>{const v=s.match(/[\\d.]+/g)?.map(Number)||[0,0,0];return [...v.slice(0,3),v[3]??1]};
        const over=(a,b)=>a.slice(0,3).map((c,i)=>c*a[3]+b[i]*(1-a[3])).concat(1);
        const bg=e=>{const layers=[];for(let n=e;n;n=n.parentElement)layers.push(rgb(getComputedStyle(n).backgroundColor));
            return layers.reverse().reduce((b,a)=>over(a,b),[8,15,28,1]);};
        const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
        const nodes=selectors.flatMap(s=>[...document.querySelectorAll(s)]).filter((n,i,a)=>a.indexOf(n)===i);
        return {surface,viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,
          controls:nodes.filter(n=>n.getBoundingClientRect().height&&n.getBoundingClientRect().width).map(n=>{
            const c=getComputedStyle(n),r=n.getBoundingClientRect(),back=bg(n),front=over(rgb(c.color),back);
            const ls=[lum(back),lum(front)].sort((a,b)=>a-b);
            return {tag:n.tagName,id:n.id,cls:typeof n.className==='string'?n.className:'',text:(n.innerText||n.getAttribute('aria-label')||n.placeholder||'').trim().slice(0,80),
              width:r.width,height:r.height,x:r.x,y:r.y,fontSize:c.fontSize,color:c.color,background:c.backgroundColor,
              effectiveBackground:back.slice(0,3),contrast:+((ls[1]+.05)/(ls[0]+.05)).toFixed(2),scheme:c.colorScheme,
              disabled:n.disabled||false};})};
    }""", {"surface": surface, "selectors": selectors})
    result["contrast_findings"] = text_contrast(page)
    return result


def inspect_categories(page, width, reports, failures):
    categories = page.locator(".dr-browse-categories button")
    expected = ["TCG", "SPORTS", "COMICS", "MANGA", "FIGURES"]
    if categories.evaluate_all("els=>els.map(e=>e.dataset.category)") != expected:
        failures.append(f"{width}px catalogue: five category destinations differ")
    if not categories.evaluate_all("els=>els.every(e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44})"):
        failures.append(f"{width}px catalogue: category targets below44px")
    if any("COMICS" in name.upper() or "MANGA" in name.upper() for name in page.locator(".dr-browse-game").all_text_contents()):
        failures.append(f"{width}px catalogue: book family remains in the TCG directory")

    def capture(name):
        settle_images(page)
        report = inspect(page, "search-" + name, [".dr-browse-categories button", ".dr-browse-category-heading h2", ".dr-browse-category-heading p", ".dr-browse-types button", ".dr-browse-empty", ".dr-browse-status", ".dr-browse-game", ".dr-browse-searchbar input"])
        reports.append(report)
        if report["overflow"]:
            failures.append(f"{width}px search {name}: horizontal page overflow")
        if width in (390, 1440):
            page.screenshot(path=str(OUT / f"synthetic-{width}-search-{name}.png"))

    page.locator('.dr-browse-searchbar input').fill("Umbreon")
    page.locator('.dr-browse-searchbar input').press("Enter")
    page.wait_for_function("previewCatalogueRequests.some(url=>url.includes('q=Umbreon'))")
    params = parse_qs(urlsplit(page.evaluate("previewCatalogueRequests.at(-1)")).query)
    if params.get("product_type") != ["CARD"] or "system_code" in params:
        failures.append(f"{width}px global TCG search is not scoped to all card games")
    capture("tcg-query")
    page.locator('[data-action="clear-query"]').click()
    page.locator('[data-category="TCG"]').last.click()
    page.locator('[data-type="SEALED"]').click()
    page.wait_for_function("previewCatalogueRequests.at(-1).includes('product_type=SEALED')")
    capture("sealed")
    page.locator('[data-category="TCG"]').last.click()
    page.locator('.dr-browse-game').first.click()
    page.wait_for_function("previewCatalogueRequests.at(-1).includes('system_code=POKEMON_TCG')")
    capture("tcg-game")
    page.locator('[data-action="games"]').click()
    page.locator('.dr-browse-game').first.wait_for()

    for category in ("SPORTS", "COMICS", "MANGA", "FIGURES"):
        previous = page.evaluate("previewCatalogueRequests.length")
        page.locator(f'button[data-category="{category}"]').click()
        page.wait_for_function("c=>document.querySelector('.dr-browser-embedded').dataset.category===c", arg=category)
        if category in ("SPORTS", "FIGURES"):
            page.wait_for_function("c=>previewCatalogueRequests.at(-1).includes('category='+c)", arg=category)
            if page.locator('.dr-browse-searchbar').is_hidden():
                failures.append(f"{width}px {category}: category search is hidden")
            params = parse_qs(urlsplit(page.evaluate("previewCatalogueRequests.at(-1)")).query)
            if params.get("product_type") != (["CARD"] if category == "SPORTS" else ["FIGURE"]):
                failures.append(f"{width}px {category}: wrong product type")
        else:
            page.wait_for_function("c=>previewCatalogueRequests.at(-1).includes('system_code='+c)", arg=category)
            params = parse_qs(urlsplit(page.evaluate("previewCatalogueRequests.at(-1)")).query)
            if params.get("product_type") != ["COMIC"]:
                failures.append(f"{width}px {category}: existing book catalogue type was changed")
        if page.locator('.dr-browse-categories [aria-pressed="true"]').count() != 1:
            failures.append(f"{width}px {category}: category selection is ambiguous")
        capture(category.lower())
    page.locator('button[data-category="TCG"]').click()


def inspect_weekly_layout(page, width, failures, founder=False):
    selector = "#weekly-movers-list" if founder else "#owner-weekly-movers"
    result = page.locator(selector).evaluate("""e=>({
        text:e.textContent,width:e.clientWidth,scrollWidth:e.scrollWidth,
        rows:[...e.querySelectorAll('.owner-insight-row,.portfolio-mover-row')].map(r=>({
            width:r.clientWidth,scrollWidth:r.scrollWidth,
            detailsWidth:(r.querySelector('.owner-insight-copy')||r.firstElementChild).getBoundingClientRect().width
        }))
    })""")
    kind = "founder" if founder else "owner"
    if len(result["rows"]) != 2 or any(label not in result["text"] for label in (
        ("Guide estimate change" if founder else "Market value change") + " · Cardmarket", "Market value change · eBay sold evidence",
        "27 Oct 2026 → 3 Nov 2026", "Special Alternate Art",
    )):
        failures.append(f"{width}px {kind} weekly movers: populated evidence labels missing")
    if result["scrollWidth"] > result["width"] + 1 or any(row["scrollWidth"] > row["width"] + 1 for row in result["rows"]):
        failures.append(f"{width}px {kind} weekly movers: row or panel overflow")
    if any(row["detailsWidth"] < 120 for row in result["rows"]):
        failures.append(f"{width}px {kind} weekly movers: evidence text squeezed below readable width")
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports, errors, failures = [], [], []
    widths = [int(x) for x in os.getenv("PREVIEW_WIDTHS", "320,390,768,1440").split(",")]
    with sync_playwright() as p:
        options = {"headless": True}
        if os.getenv("CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
        browser = p.chromium.launch(**options)
        for width in widths:
            viewport = {"width": width, "height": 1000 if width >= 1001 else 844}
            page = browser.new_page(viewport=viewport, device_scale_factor=1)
            page.set_default_timeout(10000)
            page.on("pageerror", lambda error, w=width: errors.append({"width": w, "error": str(error)}))
            owner_fixture(page)
            for view in ("overview", "inventory", "search", "more", "selling", "balance", "settings", "profile", "channels", "settlements", "sales"):
                page.evaluate("view=>activateOwnerView(view,false)", view)
                if view == "search":
                    page.locator(".dr-browse-game").first.wait_for()
                if view == "overview":
                    page.wait_for_function("document.querySelector('.owner-latest-image img')?.naturalWidth>0")
                if view == "inventory":
                    page.wait_for_function("document.querySelector('.owner-card-thumb img')?.naturalWidth>0")
                settle_images(page)
                report = inspect(page, view, [
                    ".owner-dashboard-content", ".collector-headline", ".collector-intro", ".collector-button", ".owner-nav-item",
                    ".owner-kpi-card>strong", ".owner-kpi-card>small", ".owner-panel-heading h3", ".owner-link-button",
                    ".owner-card-title strong", ".owner-card-title span", ".owner-card-prices strong", ".owner-card-prices span",
                    "#owner-inventory-status", ".workspace-tool-grid .app-more-link", ".workspace-tool-grid small",
                    ".owner-page-header h1", ".owner-page-header .muted", ".owner-item-dialog", ".collector-vibe", ".dr-browse-game",
                    ".owner-definition-list dd", ".owner-definition-list dt", ".owner-form label", ".workspace-secondary-link",
                ])
                reports.append(report)
                report["navigation"] = inspect_navigation(page)
                if view == "overview":
                    report["weekly_layout"] = inspect_weekly_layout(page, width, failures)
                print(f'Rendered synthetic {width}px {view}', flush=True)
                if report["overflow"]:
                    failures.append(f"{width}px {view}: horizontal page overflow")
                if width in (390, 1440):
                    page.screenshot(path=str(OUT / f"synthetic-{width}-{view}.png"), full_page=view in ("more", "settings", "profile", "channels", "settlements"))
                if view == "search":
                    inspect_categories(page, width, reports, failures)
            page.evaluate("activateOwnerView('inventory',false)")
            page.locator(".owner-card-open-overlay").first.click()
            page.locator(".owner-item-dialog[open] .owner-item-values").wait_for()
            reports.append(inspect(page, "item-details", [".owner-item-dialog", ".owner-item-dialog h3", ".owner-item-dialog p", ".owner-item-dialog button", ".owner-item-values strong", ".owner-item-note"]))
            if not page.locator(".owner-item-dialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1"):
                failures.append(f"{width}px detail dialog: horizontal overflow")
            if width in (390, 1440):
                page.screenshot(path=str(OUT / f"synthetic-{width}-item-details.png"))
            page.get_by_role("button", name="Close item details", exact=True).click()

            page.locator('#owner-view-inventory [data-hub-add]').click()
            settle_images(page)
            reports.append(inspect(page, "add-item", ["#hub-add-dialog", ".hub-add-choice", ".hub-dialog-heading h2"]))
            if width in (390,1440):
                page.screenshot(path=str(OUT / f"synthetic-{width}-add-item.png"))
            page.locator('#hub-add-dialog').get_by_role('button',name='Close add item',exact=True).click()

            page.locator('#owner-view-inventory [data-hub-add]').click()
            page.locator('#hub-add-dialog').get_by_role('button', name='Import a collection').click()
            page.locator('#hub-add-dialog').get_by_role('button', name='Collectr', exact=False).click()
            page.locator("#owner-import-dialog[open]").wait_for()
            report = inspect(page, "import-dialog", ["#owner-import-dialog", "#owner-import-dialog h2", "#owner-import-dialog label", "#owner-import-dialog select", "#owner-import-dialog button"])
            reports.append(report)
            if not page.locator("#owner-import-dialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1 && e.getBoundingClientRect().right<=innerWidth+1"):
                failures.append(f"{width}px import dialog: horizontal overflow")
            if width in (390, 1440):
                page.screenshot(path=str(OUT / f"synthetic-{width}-import-dialog.png"))
            page.locator("#owner-import-close").click()

            page.evaluate("activateOwnerView('sales',false)")
            page.locator(".owner-dispatch-fulfill").first.click()
            page.locator("#owner-fulfill-dialog[open]").wait_for()
            page.wait_for_function("document.getElementById('owner-fulfill-shipping-figures').textContent.includes('£0.00')")
            report = inspect(page, "fulfilment-dialog", ["#owner-fulfill-dialog", "#owner-fulfill-dialog h2", "#owner-fulfill-dialog p", "#owner-fulfill-dialog button", "#owner-fulfill-dialog dd"])
            reports.append(report)
            if not page.locator("#owner-fulfill-dialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1 && e.getBoundingClientRect().right<=innerWidth+1"):
                failures.append(f"{width}px fulfilment dialog: horizontal overflow")
            if width in (390, 1440):
                page.screenshot(path=str(OUT / f"synthetic-{width}-fulfilment-dialog.png"))
            page.locator("#owner-fulfill-close").click()
            if page.evaluate("previewWrites.length"):
                failures.append(f"{width}px fixture unexpectedly attempted a write")
            page.close()

            if width in (390, 1440):
                page = browser.new_page(viewport=viewport, device_scale_factor=1)
                page.on("pageerror", lambda error, w=width: errors.append({"width": w, "surface": "founder", "error": str(error)}))
                founder_fixture(page)
                for view in ("dashboard", "inventory", "more", "media"):
                    page.evaluate("view=>activateSellerView(view,false)", view)
                    if view == "media":
                        page.locator('#condition-review-candidate option[value="00000000-0000-4000-8000-000000000006"]').wait_for(state="attached")
                        page.locator('#condition-review-candidate').select_option("00000000-0000-4000-8000-000000000006")
                    settle_images(page)
                    report = inspect(page, "founder-" + view, [".seller-nav-tab", ".workspace-secondary-link", ".collector-button", ".collector-headline", ".collector-intro", ".stat-card>strong", ".inventory-visual-card h3", ".inventory-visual-card p", ".media-workspace select", ".media-workspace .primary-button"])
                    report["navigation"] = inspect_navigation(page, founder=True)
                    reports.append(report)
                    if report["overflow"]:
                        failures.append(f"{width}px founder {view}: horizontal page overflow")
                    page.screenshot(path=str(OUT / f"synthetic-{width}-founder-{view}.png"), full_page=view == "more")
                    if view == "media":
                        page.locator('.condition-review-card').scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT / f"synthetic-{width}-founder-media-condition.png"))
                    print(f'Rendered synthetic {width}px founder {view}', flush=True)
                page.evaluate("activateSellerView('dashboard',false)")
                page.locator('summary').filter(has_text="Portfolio & market value").click()
                settle_images(page)
                report = inspect(page, "founder-weekly-movers", ["#weekly-movers-list", ".portfolio-mover-row", ".portfolio-value-stack"])
                report["weekly_layout"] = inspect_weekly_layout(page, width, failures, founder=True)
                reports.append(report)
                if report["overflow"]:
                    failures.append(f"{width}px founder weekly movers: horizontal page overflow")
                page.screenshot(path=str(OUT / f"synthetic-{width}-founder-weekly-movers.png"), full_page=True)
                page.locator('summary').filter(has_text="Portfolio & market value").click()
                for dialog_id, action in (("editor-dialog", "openInventoryCopies([...state.items.values()][0])"),
                                          ("inventory-import-dialog", "openInventoryImport()")):
                    page.evaluate(action)
                    page.locator(f"#{dialog_id}[open]").wait_for()
                    settle_images(page)
                    report = inspect(page, "founder-" + dialog_id, [f"#{dialog_id}", f"#{dialog_id} h2", f"#{dialog_id} label", f"#{dialog_id} button", f"#{dialog_id} select", f"#{dialog_id} input"])
                    reports.append(report)
                    if not page.locator(f"#{dialog_id}").evaluate("e=>e.scrollWidth<=e.clientWidth+1 && e.getBoundingClientRect().right<=innerWidth+1"):
                        failures.append(f"{width}px founder {dialog_id}: horizontal overflow")
                    page.screenshot(path=str(OUT / f"synthetic-{width}-founder-{dialog_id}.png"))
                    page.locator(f"#{dialog_id}").evaluate("e=>e.close()")
                if page.evaluate("previewWrites.length"):
                    failures.append(f"{width}px founder fixture unexpectedly attempted a write")
                page.close()

            for name, path, form_id in (("index.html", "/app", "login-form"), ("owner-join.html", "/owner/join", "owner-join-form")):
                page = browser.new_page(viewport=viewport, device_scale_factor=1)
                install_routes(page, name)
                page.goto(ORIGIN + path)
                page.evaluate("""formId=>{
                    document.body.classList.remove('hub-restoring');
                    document.title='Synthetic preview · Drop Rate Seller Hub';
                    document.querySelectorAll('#auth-view .auth-card').forEach(n=>n.classList.toggle('hidden',n.id!==formId));
                }""", form_id)
                settle_images(page)
                report = inspect(page, form_id, ["#auth-view .auth-panel", "#auth-view h1", "#auth-view h2", "#auth-view .muted", "#auth-view label", "#auth-view input", "#auth-view .primary-button", "#auth-view .text-button"])
                reports.append(report)
                if report["overflow"]:
                    failures.append(f"{width}px {form_id}: horizontal page overflow")
                if width in (390, 1440):
                    page.screenshot(path=str(OUT / f"synthetic-{width}-{form_id}.png"), full_page=form_id == "owner-join-form")
                page.close()
        browser.close()

    for report in reports:
        for finding in report["contrast_findings"]:
            if finding["imageBackground"] or (finding["largeText"] and finding["contrast"] >= 3):
                continue
            label = finding["id"] or finding["cls"] or finding["text"][:36]
            failures.append(f'{report["viewport"]}px {report["surface"]}: {label} text contrast {finding["contrast"]}:1')
        nav = report.get("navigation")
        if nav:
            expected_active = 0 if report["surface"] in ("more", "settings", "profile") else 1
            if nav["count"] != 5 or nav["active"] != expected_active:
                failures.append(f'{report["viewport"]}px {report["surface"]}: expected five navigation controls with {expected_active} current destination')
            if nav["ownerHasFounderBusiness"]:
                failures.append(f'{report["viewport"]}px owner fixture exposes founder Business controls')
            if report["viewport"] <= 1000:
                if not nav["secondaryHidden"] or any(n["height"] < 44 or n["bottom"] > 845 or n["left"] < -1 or n["right"] > report["viewport"] + 1 for n in nav["buttons"]):
                    failures.append(f'{report["viewport"]}px {report["surface"]}: mobile navigation target size or placement')
        for control in report["controls"]:
            if control["tag"] == "SELECT" and control["scheme"] != "dark":
                failures.append(f'{report["viewport"]}px {control["id"]} select has {control["scheme"]} native colour scheme')
            if re.search(r"(?:^| )(?:primary-button|collector-primary|collector-secondary|owner-primary-action|owner-import-primary|primary)(?: |$)", control["cls"]) and control["height"] < 44:
                failures.append(f'{report["viewport"]}px {control["cls"]} tap target {control["height"]}px')
    result = {"synthetic_fixture": True, "production_calls": 0, "failures": failures, "page_errors": errors, "reports": reports}
    (OUT / "premium-hub-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"output": str(OUT), "surfaces": len(reports), "failures": failures, "page_errors": errors}, indent=2))
    raise SystemExit(1 if failures or errors else 0)


if __name__ == "__main__":
    main()
