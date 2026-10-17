"""Actual home/search/collection HTML and assets; synthetic owner/API, no live writes."""
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]/'backend/app/static'
OUT=Path('/tmp/collection-confirmation')


def main():
    OUT.mkdir(exist_ok=True)
    html=re.sub(r'<script\b[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S|re.I)
    receipts=[]
    with sync_playwright() as p:
        for engine in ('chromium','webkit'):
            browser=getattr(p,engine).launch()
            for width in (320,390,1440):
                page=browser.new_page(viewport={'width':width,'height':844})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def serve(route):
                    url=urlsplit(route.request.url)
                    if url.hostname!='collection.test':return route.abort()
                    if url.path=='/owner':return route.fulfill(content_type='text/html',body=html)
                    file=(ROOT/url.path.removeprefix('/assets/')).resolve()
                    if url.path.startswith('/assets/') and ROOT.resolve() in file.parents and file.is_file():
                        return route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                    route.abort()
                page.route('**/*',serve);page.goto('https://collection.test/owner')
                for file in ('hub-session.js','reference-value-display.js','inventory-groups.js','owner-inventory.js','owner-portal.js','catalogue-browser.js','workspace-shell.js'):
                    code=(ROOT/file).read_text()
                    if file=='owner-portal.js':code=re.sub(r'\ninitialise\(\);\s*$','',code)
                    page.add_script_tag(content=code)
                page.evaluate('''() => {
                  document.body.classList.remove('hub-restoring');document.querySelector('.hub-loading')?.remove();
                  byId('owner-auth-view').classList.add('hidden');byId('owner-portal-view').classList.remove('hidden');
                  state.session={access_token:'fixture-only',user:{id:'fixture-owner'}};window.writes=[];window.failOnce=false;
                  window.sample={id:'11111111-1111-4111-8111-111111111111',key:'c:11111111-1111-4111-8111-111111111111',
                    catalogue_id:'11111111-1111-4111-8111-111111111111',name:'Monkey D. Luffy',product_type:'CARD',game:'One Piece',
                    set_name:'Awakening of the New Era',card_number:'OP05-119',language:'English',variant:'Alternate art',
                    source_kind:'CATALOGUE',display_image_url:'/assets/grail-art/luffy-op05-119-p2.png',market_value_minor:null,
                    sale_intent:'PERSONAL_COLLECTION',status:'DRAFT',grouped_quantity:1};
                  apiRequest=async()=>({items:[],summary:{}});
                  activateOwnerView('overview',false);
                  byId('owner-total-inventory').textContent='1';byId('owner-market-value').textContent='Unavailable';
                  window.client={owner:'fixture-owner',active:()=>true,request:async(url,options)=>{
                    if(url.endsWith('/intake')){writes.push({url,...options});if(failOnce){failOnce=false;throw new Error('Connection interrupted');}
                      renderInventoryCards([sample]);return {inventory:{inventory_code:'INV-FIXTURE'}};}
                    return {items:[]};
                  }};
                  window.browser=new DropRateCatalogue.Browser({host:byId('owner-view-search'),client,navigate:activateOwnerView,
                    scan:()=>{},graded:()=>{},afterSave:async()=>{}});
                }''')
                assert not page.locator('#owner-next-payout-amount').is_visible()
                assert not page.locator('#owner-store-value').is_visible()
                assert page.locator('#owner-view-overview .owner-kpi-card').count()==2
                assert 'payout' not in page.locator('#owner-view-overview').inner_text().lower()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                if width==390:page.screenshot(path=str(OUT/f'{engine}-simple-home.png'))
                page.evaluate("activateOwnerView('more');")
                page.locator('[data-owner-jump="selling"]').click()
                assert page.locator('#owner-view-selling').is_visible()
                assert page.locator('#owner-next-payout-amount').is_visible()
                page.evaluate("activateOwnerView('search');browser.openProduct(sample)")
                assert page.get_by_role('heading',name='Is this your item?').is_visible()
                assert not page.get_by_label('Condition',exact=True).is_visible()
                assert not page.get_by_label('Quantity',exact=True).is_visible()
                assert page.locator('[aria-label="Confirm exact product"]').count()==0
                add=page.get_by_role('button',name='Add to collection',exact=True)
                assert add.is_enabled() and not page.evaluate('writes.length')
                page.wait_for_function('document.querySelector(".dr-browse-detail-image img").naturalWidth>0')
                assert page.locator('.dr-browse-sheet').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                if width in (390,1440):page.screenshot(path=str(OUT/f'{engine}-{width}-simple-add.png'))
                add.click();page.get_by_role('button',name='Done',exact=True).wait_for()
                body=json.loads(page.evaluate('writes[0].body'))
                assert body['confirmed'] is True and body['condition'] is None
                assert len(page.evaluate('writes'))==1 and 'price' not in body and 'owner_id' not in body
                assert 'added to your collection' in page.locator('.dr-browse-detail-message').inner_text()
                page.get_by_role('button',name='Done',exact=True).click()
                # Collection tile has no listing setup; selling remains an explicit disclosure.
                page.evaluate("activateOwnerView('inventory');renderInventoryCards([sample]);")
                assert 'Selling price' not in page.locator('.owner-inventory-card').inner_text()
                assert 'DRAFT' not in page.locator('.owner-inventory-card').inner_text()
                if width==390:page.screenshot(path=str(OUT/f'{engine}-simple-collection.png'))
                # Lost responses freeze the same copy; Retry never sends a new idempotency key.
                page.evaluate("activateOwnerView('search');browser.openProduct(sample);failOnce=true")
                page.get_by_role('button',name='Add to collection',exact=True).click()
                page.get_by_role('button',name='Retry remaining saves',exact=True).wait_for()
                page.get_by_role('button',name='Retry remaining saves',exact=True).click()
                page.get_by_role('button',name='Done',exact=True).wait_for()
                writes=page.evaluate('writes')
                assert len(writes)==3 and writes[1]['body']==writes[2]['body']
                assert writes[1]['headers']['Idempotency-Key']==writes[2]['headers']['Idempotency-Key']
                assert not errors,errors
                receipts.append({'engine':engine,'width':width,'one_click_add':True,'null_condition':True,'retry_safe':True})
                page.close()
            browser.close()
    (OUT/'simplicity.json').write_text(json.dumps(receipts,indent=2))
    print('PASS: six real-browser collection-first journeys; one-click card add, optional details, separate selling and lost-response retry.')


if __name__=='__main__':main()
