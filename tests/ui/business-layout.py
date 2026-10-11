"""Actual founder shell CSS and Business module; mocked API, Chromium/WebKit.
Not a live seller login or physical-device check. Only local fixtures served.
"""
import json,mimetypes,re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];STATIC=ROOT/'backend/app/static';OUT=Path('/tmp/drop-rate-business-layout')
SIZES=[(320,680),(390,844),(660,800),(768,900),(1440,1000)]

def main():
 OUT.mkdir(exist_ok=True);records=[]
 html=re.sub(r'<script\b[^>]*>.*?</script>','',(STATIC/'index.html').read_text(),flags=re.S|re.I)
 with sync_playwright() as p:
  for engine in ('chromium','webkit'):
   browser=getattr(p,engine).launch()
   for width,height in SIZES:
    page=browser.new_page(viewport={'width':width,'height':height});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def serve(route):
     url=urlsplit(route.request.url)
     if url.hostname!='business-layout.test':return route.abort()
     if url.path=='/app':return route.fulfill(content_type='text/html',body=html)
     file=(STATIC/url.path.removeprefix('/assets/')).resolve()
     if STATIC.resolve() in file.parents and file.is_file():return route.fulfill(content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream',body=file.read_bytes())
     route.abort()
    page.route('**/*',serve);page.goto('http://business-layout.test/app',wait_until='load')
    page.evaluate('''()=>{document.body.classList.remove('hub-restoring');document.querySelector('.hub-loading')?.remove();document.getElementById('auth-view')?.remove();const dash=document.getElementById('dashboard-view');dash.classList.remove('hidden');dash.classList.add('founder-workspace');const content=dash.querySelector('.dashboard-content');content.replaceChildren();const section=document.createElement('section');section.dataset.sellerView='accounts';content.append(section);window.state={session:{access_token:'fixture',user:{id:'founder'}}};window.sellerView=()=>section;window.activateSellerView=()=>{};window.reloadDashboard=async()=>{};window.apiRequest=async url=>{if(url==='/api/v1/access/me')return {access:{business_allowed:true}};if(url==='/api/v1/founder/accounts')return {own_owner_id:'a',accounts:[{id:'a',display_name:'Founder A',owner_type:'FOUNDER',username:'founder-a',active_stock_count:10,for_sale_count:7,draft_count:3,unvalued_count:3},{id:'b',display_name:'Independent seller with a longer account name',owner_type:'CONSIGNOR',username:'seller-b',active_stock_count:4,draft_count:4,unvalued_count:4}]};return {items:[{owner_id:'b',owner_name:'Independent seller',inventory_code:'INV-SYNTHETIC-LONG-000001',name:'An exact card with a longer variant title',game:'One Piece',set_name:'Synthetic set',card_number:'OP01-001',language:'Japanese',grading_company:'BGS',grade:'9.5',variant:'Alternate art',status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',market_value_minor:null,store_price_minor:null}],total:1};};}''')
    page.add_script_tag(content=(STATIC/'founder-accounts.js').read_text());page.evaluate("document.dispatchEvent(new CustomEvent('seller-view-changed',{detail:{view:'accounts'}}))")
    page.locator('.business-kpi').first.wait_for()
    for mode in ('overview','sellers','inventory'):
     if mode!='overview':page.locator(f'#business-tab-{mode}').click()
     target='.business-kpi' if mode=='overview' else '.business-seller-card' if mode=='sellers' else '.business-table'
     page.locator(target).first.wait_for()
     for element in page.locator('.business-area button:visible,.business-area input:visible,.business-area select:visible').all():
      box=element.bounding_box();assert box and box['x']>=-1 and box['x']+box['width']<=width+1,(engine,width,mode,box)
     assert page.locator('.business-area').evaluate('el=>el.scrollWidth<=el.clientWidth+1'),(engine,width,mode,'overflow')
     if width in (390,1440):page.screenshot(path=str(OUT/f'{engine}-{width}-{mode}.png'),full_page=True)
    page.evaluate("window.state.session=null;window.dispatchEvent(new Event('hub-session-cleared'))")
    assert not page.locator('#business-content').is_visible();assert not errors,errors
    records.append({'engine':engine,'width':width,'passed':True});page.close()
   browser.close()
 (OUT/'results.json').write_text(json.dumps(records,indent=2));print('PASS: 10 Chromium/WebKit sizes, 30 Business states, controls contained, no horizontal overflow, logout hides content. Mocked API, not production login.')
if __name__=='__main__':main()
