"""Repair artwork on an existing copy; private thumbnails and retry readback."""
import json
import os
import re
import runpy
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]/'backend/app/static'
OUT=Path(os.getenv('COLLECTION_LAYOUT_DIR','/tmp/collection-confirmation'))
PNG=runpy.run_path(str(Path(__file__).with_name('collection-book-research.py')))['PNG']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES','chromium,webkit').split(','):
            browser=getattr(p,engine).launch(headless=True)
            for width in (390,1440):
                page=browser.new_page(viewport={'width':width,'height':900});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                html=re.sub(r'<script[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S)
                def route(r):
                    if r.request.url=='https://book-library.test/':r.fulfill(body=html,content_type='text/html')
                    elif '/covers/' in r.request.url or '/image' in r.request.url or '/reference-image' in r.request.url:
                        assert r.request.headers.get('authorization')=='Bearer synthetic'
                        r.fulfill(body=PNG,content_type='image/png')
                    elif r.request.url.startswith(('blob:','data:')):r.continue_()
                    else:r.abort()
                page.route('**/*',route);page.goto('https://book-library.test/')
                for name in ('owner-portal.css','owner-inventory.css','owner-books.css'):
                    page.add_style_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content=(ROOT/'hub-session.js').read_text())
                page.add_script_tag(content=(ROOT/'owner-inventory.js').read_text())
                page.add_script_tag(content=re.sub(r'\ninitialise\(\);\s*$','',(ROOT/'owner-portal.js').read_text()))
                page.evaluate('''async()=>{
                    state.session={access_token:'synthetic',user:{id:'seller-a'}};
                    loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=loadOwnerInventory=async()=>{};
                    window.calls=[];
                    window.currentItem={id:'d715b0e9-b3c4-451b-a909-5fa233f8a0e5',catalogue_id:'cat-a',inventory_code:'INV-BOOK',version:1,
                      status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',product_type:'COMIC',game:'Marvel Comics',language:'English',name:'Deadpool / Batman #1',set_name:'Deadpool / Batman',condition:null,
                      market_value_minor:null,store_price_minor:null,approval_blockers:['Drop Rate selling review'],shopify_sync_enabled:true};
                    apiRequest=async(url,options={})=>{
                      calls.push({url,...options});
                      if(url.endsWith('/covers'))return {version:1,identity_digest:'d'.repeat(64),candidates:[{id:'a'.repeat(24),source_title:'Ryan Stegman second printing',
                        fields:{language:'English',printing_number:2,cover_artist:'Ryan Stegman'},image_path:'/api/v1/owner/books/inventory/'+currentItem.id+'/covers/'+'a'.repeat(24)+'?version=1'}]};
                      if(options.method){
                        currentItem={...currentItem,version:2,reference_image_path:'/api/v1/owner/inventory/'+currentItem.id+'/reference-image'};
                        return {message:'Cover saved.'};
                      }
                      return {item:currentItem,copies:[currentItem]};
                    };
                    await DropRateInventory.open(currentItem);
                }''')
                page.get_by_role('button',name='Choose cover',exact=True).click()
                save=page.get_by_role('button',name='Use this cover',exact=True)
                page.wait_for_function('document.querySelector(".owner-book-cover img")?.naturalWidth === 160')
                assert save.is_enabled()
                assert not page.evaluate('calls.some(c=>c.method)')
                assert page.locator('.owner-item-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                save.scroll_into_view_if_needed()
                assert save.bounding_box()['height']>=44
                page.screenshot(path=str(OUT/f'{engine}-{width}-saved-book-cover-choice.png'))
                save.click()
                page.get_by_role('button',name='Change cover',exact=True).wait_for()
                writes=page.evaluate('calls.filter(c=>c.method)')
                assert len(writes)==1 and writes[0]['url'].endswith('/cover')
                body=json.loads(writes[0]['body'])
                assert body==dict(version=1,identity_digest='d'*64,candidate_id='a'*24,confirmed=True)
                assert page.evaluate('currentItem.id')=='d715b0e9-b3c4-451b-a909-5fa233f8a0e5'
                assert page.evaluate('currentItem.sale_intent')=='PERSONAL_COLLECTION'
                assert not errors,errors
                page.screenshot(path=str(OUT/f'{engine}-{width}-saved-book-cover-restored.png'))
                page.close()
            browser.close()


if __name__=='__main__':main()
