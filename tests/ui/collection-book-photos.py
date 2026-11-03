"""Real book/photo handoff at mobile and desktop widths; synthetic APIs only."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2] / "backend/app/static"
OUT = Path(os.getenv("COLLECTION_LAYOUT_DIR", "/tmp/collection-confirmation"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        for engine in os.getenv("BROWSER_ENGINES", "chromium,webkit").split(","):
            browser = getattr(playwright, engine).launch(headless=True)
            for width in (390, 1440):
                print(f"Book photo handoff: {engine} {width}", flush=True)
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                html = re.sub(r"<script[^>]*>.*?</script>", "", (ROOT / "owner.html").read_text(), flags=re.S)

                def route_request(route):
                    url = urlsplit(route.request.url)
                    if route.request.url == "https://book-photos.test/":
                        route.fulfill(body=html, content_type="text/html")
                    elif url.netloc == "book-photos.test" and url.path.startswith("/assets/") and url.path.endswith(".css"):
                        route.fulfill(body=(ROOT / Path(url.path).name).read_text(), content_type="text/css")
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("https://book-photos.test/")
                page.evaluate("document.body.classList.remove('hub-restoring')")
                page.add_script_tag(content="""
                  const state={session:{access_token:'fixture-only',user:{id:'seller-a'}}};
                  const fields={system_code:'DC_COMICS',series_title:'Fixture Batman',issue_number:'463',
                    publisher:'DC',book_format:'SINGLE_ISSUE',language:'English',release_year:1991,printing_number:null};
                  const recognition={status:'NEEDS_REVIEW',fields,uncertain_fields:['printing_number'],warnings:[]};
                  const photo=color=>{const canvas=document.createElement('canvas');canvas.width=240;canvas.height=360;
                    const context=canvas.getContext('2d');context.fillStyle=color;context.fillRect(0,0,240,360);
                    return canvas.toDataURL('image/png');};
                  window.front=photo('#547082');window.back=photo('#d6ba8c');window.inside=photo('#d5d9dd');
                  window.intakes=[];window.transfers=[];window.readbacks=[];window.savedCallbacks=[];window.saveStates=[];
                  window.mode='ok';window.version=1;window.assetWrites=0;window.assets=new Map();window.releasePhoto=null;
                  async function loadOwnerInventory(){} async function loadOwnerOverview(){}
                  async function apiRequest(path,options={}){
                    if(path.endsWith('/market-value'))return {status:'UNAVAILABLE',market_value_minor:null,reason:'Synthetic fixture.'};
                    if(path.endsWith('/books/intake')){
                      intakes.push({path,options,actor:state.session.user.id});
                      return {catalogue:{name:'Fixture Batman #463'},inventory:{id:'copy-fixture',version:1}};
                    }
                    if(path==='/api/v1/owner/inventory/copy-fixture'){
                      readbacks.push({path,actor:state.session.user.id});return {item:{version}};
                    }
                    if(path.includes('/photo/upload?')){
                      const query=new URL(path,location.origin).searchParams;
                      const bytes=Array.from(new Uint8Array(await options.body.arrayBuffer()));
                      transfers.push({path,query:Object.fromEntries(query),bytes,type:options.headers['Content-Type'],actor:state.session.user.id});
                      const side=query.get('side'),key=query.get('request_key');
                      if(mode==='defer')await new Promise(resolve=>window.releasePhoto=resolve);
                      if(mode==='back-fails'&&side==='BACK'){mode='ok';version=2;throw new TypeError('Load failed');}
                      let result=assets.get(key);
                      if(!result){assetWrites++;result={asset:{id:'photo-'+key,side,
                        shopify_file_status:'READY',approval_status:'PENDING',rights_status:'PENDING'},inventory_version:version};assets.set(key,result);}
                      if(mode==='lost-response'){mode='ok';version=2;throw new TypeError('Load failed');}
                      return result;
                    }
                    throw new Error('Unexpected API in photo fixture: '+path);
                  }
                  window.start=(photos=[front],extra={})=>{
                    DropRateBooks.reset();
                    intakes=[];transfers=[];readbacks=[];savedCallbacks=[];saveStates=[];
                    mode='ok';version=1;assetWrites=0;assets=new Map();releasePhoto=null;
                    DropRateBooks.open({recognition,photos,
                      onSaved:(result,copy,context)=>savedCallbacks.push({result,copy,context}),
                      onSaveState:value=>saveStates.push(value),...extra});
                  };
                """)
                page.add_script_tag(content=(ROOT / "scan-photos.js").read_text())
                page.add_script_tag(content=(ROOT / "owner-books.js").read_text())

                def finished():
                    page.wait_for_function("savedCallbacks.length===1 && !document.querySelector('#owner-book-view-item').disabled")

                # Photos survive the recognition handoff. Only the first image
                # defaults to FRONT; barcode/inside pages are not listing photos.
                page.evaluate("start([front,back,inside])")
                assert page.locator("#owner-book-photo-details").evaluate("element=>!element.open")
                assert page.locator("#owner-book-photo-permission").is_visible()
                assert "permission" in page.locator("#owner-book-photo-permission").inner_text()
                assert page.locator("#owner-book-photo-choices select").evaluate_all("elements=>elements.map(element=>element.value)") == ["FRONT", "IDENTIFICATION_ONLY", "IDENTIFICATION_ONLY"]
                assert page.evaluate("intakes.length===0 && transfers.length===0")
                geometry = page.locator("#owner-book-photo-choices").evaluate("""element=>{
                  const container=element.getBoundingClientRect(),strip=document.querySelector('#owner-book-photos').getBoundingClientRect();
                  return {width:container.width,top:container.top,stripBottom:strip.bottom,
                    choices:[...element.querySelectorAll('select')].map(select=>{const rect=select.getBoundingClientRect();return {width:rect.width,height:rect.height};}),
                    overflow:document.querySelector('#owner-book-dialog').scrollWidth>document.querySelector('#owner-book-dialog').clientWidth+1};
                }""")
                assert geometry["top"] >= geometry["stripBottom"], geometry
                assert all(choice["height"] >= 44 and choice["width"] >= geometry["width"] - 2 for choice in geometry["choices"]), geometry
                assert not geometry["overflow"], geometry
                assert page.locator("#owner-book-photos button").evaluate_all("elements=>elements.every(element=>element.getBoundingClientRect().height>=44 && element.getBoundingClientRect().width>=44)")
                page.locator("#owner-book-photo-save").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f"{engine}-{width}-book-photo-choices.png"))

                # The copy is marked added before the upload completes. During
                # the transfer the actions stay locked, including native Escape.
                page.evaluate("mode='defer'")
                page.locator("#owner-book-save").click()
                page.wait_for_function("typeof releasePhoto==='function'")
                assert page.locator("#owner-book-title").inner_text() == "Added to your collection"
                assert page.locator("#owner-book-save").is_disabled()
                assert page.locator("#owner-book-close").is_disabled()
                assert page.locator("#owner-book-view-item").is_disabled()
                assert page.locator("#owner-book-add-another").is_disabled()
                assert page.evaluate("savedCallbacks.length===0")
                page.keyboard.press("Escape")
                assert page.locator("#owner-book-dialog").is_visible()
                page.evaluate("releasePhoto()")
                finished()
                assert page.evaluate("intakes.length===1 && transfers.length===1 && assetWrites===1")
                assert page.evaluate("JSON.stringify(transfers[0].bytes)===JSON.stringify(Array.from(atob(front.split(',')[1]),character=>character.charCodeAt(0)))")
                upload = page.evaluate("transfers[0]")
                assert upload["type"] == "image/png"
                assert upload["query"]["side"] == "FRONT" and upload["query"]["rights_confirmed"] == "true"
                assert upload["query"]["version"] == "1" and upload["actor"] == "seller-a"
                assert page.evaluate("savedCallbacks[0].context.photos[0]===front && savedCallbacks[0].context.photoResult.complete")
                assert "still need review" in page.locator("#owner-book-photo-message").inner_text()

                # A lost upload response must not change the committed intake to
                # a failed save. Retry uses its original bytes/key and the copy's
                # current version, with no second intake or scanner callback.
                page.evaluate("start();mode='lost-response'")
                page.locator("#owner-book-save").click()
                finished()
                assert page.locator("#owner-book-message").inner_text() == "Book added. Photo needs retry."
                assert page.locator("#owner-book-photo-retry").is_visible()
                assert page.locator("#owner-book-photo-retry").evaluate("element=>element.getBoundingClientRect().height>=44 && element.getBoundingClientRect().width>=44")
                assert page.locator("#owner-book-series").is_disabled()
                assert page.locator("#owner-book-save").is_disabled()
                assert page.evaluate("intakes.length===1 && transfers.length===1 && assetWrites===1 && savedCallbacks.length===1")
                page.locator("#owner-book-photo-save").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f"{engine}-{width}-book-photo-retry.png"))
                page.locator("#owner-book-photo-retry").click()
                page.wait_for_function("document.querySelector('#owner-book-photo-retry').hidden")
                assert page.evaluate("intakes.length===1 && transfers.length===2 && assetWrites===1 && savedCallbacks.length===1 && readbacks.length===1")
                assert page.evaluate("transfers[0].query.request_key===transfers[1].query.request_key && JSON.stringify(transfers[0].bytes)===JSON.stringify(transfers[1].bytes)")
                assert page.evaluate("transfers[1].query.version==='2'")

                # Partial success retries only the remaining side, after reading
                # the current copy version (an edit occurred between attempts).
                page.evaluate("start([front,back]);mode='back-fails'")
                page.get_by_label("Use photo 2 as", exact=True).select_option("BACK")
                page.locator("#owner-book-save").click()
                finished()
                assert page.evaluate("transfers.map(item=>item.query.side).join(',')==='FRONT,BACK' && assetWrites===1")
                page.locator("#owner-book-photo-retry").click()
                page.wait_for_function("document.querySelector('#owner-book-photo-retry').hidden")
                assert page.evaluate("transfers.map(item=>item.query.side).join(',')==='FRONT,BACK,BACK' && assetWrites===2 && intakes.length===1 && savedCallbacks.length===1")
                assert page.evaluate("transfers[1].query.request_key===transfers[2].query.request_key && transfers[2].query.version==='2' && readbacks.length===1")

                # Duplicate physical sides are rejected before creating a copy.
                page.evaluate("start([front,back])")
                page.get_by_label("Use photo 2 as", exact=True).select_option("FRONT")
                page.locator("#owner-book-save").click()
                assert "one photo for each side" in page.locator("#owner-book-message").inner_text()
                assert page.evaluate("intakes.length===0 && transfers.length===0")
                page.get_by_label("Use photo 1 as", exact=True).select_option("IDENTIFICATION_ONLY")
                page.get_by_label("Use photo 2 as", exact=True).select_option("IDENTIFICATION_ONLY")
                page.locator("#owner-book-save").click()
                finished()
                assert page.evaluate("intakes.length===1 && transfers.length===0")

                # A new open clears photo-side choices; no-photo manual intake
                # and catalogue artwork alone never start a physical upload.
                page.evaluate("start()")
                assert page.get_by_label("Use photo 1 as", exact=True).input_value() == "FRONT"
                page.evaluate("start([],{recognition:null,book:fields,catalogue:{catalogue_id:'reference-only',name:'Reference artwork only',image_url:'https://publisher.invalid/cover.jpg'}})")
                assert page.locator("#owner-book-photo-save").is_hidden()
                page.locator("#owner-book-save").click()
                finished()
                assert page.evaluate("intakes.length===1 && transfers.length===0")

                # Both a same-account new open and an account change invalidate
                # the old transfer. Neither may attach its second side, invoke
                # a callback into the new scan or change the new dialog's UI.
                for next_actor in ("seller-a", "seller-b"):
                    page.evaluate("start([front,back]);mode='defer'")
                    page.get_by_label("Use photo 2 as", exact=True).select_option("BACK")
                    page.locator("#owner-book-save").click()
                    page.wait_for_function("typeof releasePhoto==='function'")
                    page.evaluate("""actor=>{
                      window.releasePrevious=releasePhoto;
                      state.session={access_token:'another-fixture',user:{id:actor}};
                      DropRateBooks.reset();mode='ok';
                      DropRateBooks.open({book:{...fields,issue_number:'464'},onSaved:()=>savedCallbacks.push('new-open')});
                      releasePrevious();
                    }""", next_actor)
                    page.wait_for_timeout(50)
                    assert page.locator("#owner-book-number").input_value() == "464"
                    assert page.locator("#owner-book-message").inner_text() == ""
                    assert page.locator("#owner-book-photo-save").is_hidden()
                    assert not page.locator("#owner-book-save").is_disabled()
                    assert page.evaluate("transfers.length===1 && transfers[0].actor==='seller-a' && savedCallbacks.length===0")
                assert not errors, errors
                page.close()
            browser.close()
    print("Book photo handoff checks passed", flush=True)


if __name__ == "__main__":
    main()
