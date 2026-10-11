"""Real seller image JavaScript + local image responses. No live login or stock writes."""
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhZkAAAAASUVORK5CYII=')
ID='d715b0e9-b3c4-451b-a909-5fa233f8a0e5'
PATH=f'/api/v1/inventory/{ID}/image'
REF=f'/api/v1/owner/inventory/{ID}/reference-image'
OUT=Path(os.environ.get('MEDIA_LAYOUT_DIR','/tmp/shared-image-layout'))

def main():
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    with sync_playwright() as p:
        for engine in ('chromium','webkit'):
            browser=getattr(p,engine).launch()
            for width in (390,1440):
                for mode in ('provider','inventory_alias','missing_metadata','cdn_failure','reference_fallback','expired','denied','bad_mime','stale_session'):
                    page=browser.new_page(viewport={'width':width,'height':900});calls=[];errors=[]
                    page.on('pageerror',lambda e: errors.append(str(e)))
                    def handle(route):
                        u=urlsplit(route.request.url)
                        if u.hostname=='image.test' and u.path=='/':
                            return route.fulfill(content_type='text/html',body='<html><head><meta name="viewport" content="width=device-width"></head><body><div id="images"></div></body></html>')
                        calls.append((u.hostname,u.path,route.request.headers.get('authorization')))
                        if u.hostname!='image.test': return route.fulfill(status=403,body='Provider blocked direct browser request')
                        if u.path in (PATH,REF):
                            assert route.request.method=='GET'
                            assert route.request.headers.get('authorization') in ('Bearer fixture-a','Bearer refreshed-a')
                            if mode=='expired' and route.request.headers.get('authorization')=='Bearer fixture-a':return route.fulfill(status=401,body='expired')
                            if mode=='denied' or (mode=='reference_fallback' and u.path==PATH):return route.fulfill(status=404,body='not available')
                            if mode=='bad_mime':return route.fulfill(content_type='text/html',body='<html>not an image</html>')
                            return route.fulfill(content_type='image/png',body=PNG)
                        return route.abort()
                    page.route('**/*',handle);page.goto('http://image.test/')
                    page.evaluate('''() => {window.state={session:{access_token:'fixture-a',user:{id:'seller-a'}}};window.refreshes=0;window.refreshSession=async()=>{refreshes++;state.session.access_token='refreshed-a';return 'refreshed-a';};}''')
                    page.add_script_tag(content=(ROOT/'backend/app/static/owner-inventory.js').read_text())
                    item={'id':ID,'name':'Synthetic known card','image_url':'https://www.onepiece-cardgame.com/card.png'}
                    if mode=='inventory_alias':item['inventory_id']=item.pop('id')
                    if mode=='missing_metadata':item.pop('image_url')
                    if mode=='cdn_failure':item['image_url']='https://cdn.shopify.com/missing.png'
                    if mode=='reference_fallback':item.update(reference_image_url='https://www.onepiece-cardgame.com/exact-reference.png',reference_image_path=REF)
                    if mode=='stale_session':page.evaluate('''() => {window.pending=null;window.fetch=()=>new Promise(resolve=>{window.pending=resolve;});}''')
                    page.evaluate('(item)=>document.getElementById("images").append(DropRateInventory.image(item,"owner-card-thumb"))',item)
                    if mode=='stale_session':
                        page.wait_for_function('window.pending!==null');page.evaluate('''() => {state.session={access_token:'fixture-b',user:{id:'seller-b'}};pending(new Response(new Blob(['private'],{type:'image/png'})));}''');page.wait_for_timeout(50)
                        assert page.locator('img[src^="blob:"]').count()==0
                    elif mode in ('denied','bad_mime'):
                        page.wait_for_function('document.getElementById("images").textContent.includes("Image unavailable")')
                        assert page.locator('#images img').count()==0 and len(calls)==1
                    else:
                        page.wait_for_function('document.querySelector("#images img")?.naturalWidth>0')
                        assert page.locator('.owner-image-placeholder').is_hidden()
                        assert page.locator('#images img').get_attribute('src').startswith('blob:')
                        assert sum(1 for _,path,_ in calls if path==PATH)==(2 if mode=='expired' else 1)
                        if mode=='reference_fallback':assert sum(1 for _,path,_ in calls if path==REF)==1
                        if mode=='expired':assert page.evaluate('refreshes')==1
                        if mode=='provider':assert all(host=='image.test' for host,_,_ in calls)
                    assert not errors,errors
                    assert all(host=='image.test' or token is None for host,_,token in calls),'Credentials leaked to provider'
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'engine':engine,'width':width,'mode':mode,'passed':True})
                    page.close()
            browser.close()
    (OUT/'results.json').write_text(json.dumps(results,indent=2))
    print(f'PASS: {len(results)} Chromium/WebKit image-loader cases, provider blocked, shared source, CDN/reference fallback, expiry, denied/bad MIME, stale-session suppression. Local response fixtures; not live seller authentication.')

if __name__=='__main__':main()
