"""Actual seller page/controls; intercepted API data only, no live account writes."""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]/'backend/app/static'
OUT=Path(os.getenv('COLLECTION_LAYOUT_DIR','/tmp/collection-confirmation'))


def main():
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES','chromium,webkit').split(','):
            options={'headless':True}
            if engine=='chromium' and os.getenv('CHROMIUM_EXECUTABLE'):options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
            browser=getattr(p,engine).launch(**options)
            for width in (390,1440):
                page=browser.new_page(viewport={'width':width,'height':900});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.abort())
                text=re.sub(r'<script[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S)
                page.set_content(text)
                for name in ('owner-inventory.css','owner-portal.css'):
                    if (ROOT/name).exists():page.add_style_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content=(ROOT/'hub-session.js').read_text())
                page.add_script_tag(content=(ROOT/'owner-inventory.js').read_text())
                page.add_script_tag(content=re.sub(r'\ninitialise\(\);\s*$','',(ROOT/'owner-portal.js').read_text()))
                page.evaluate('''async()=>{
                    state.session={access_token:'synthetic',user:{id:'seller-a'}};
                    loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=loadOwnerInventory=async()=>{};
                    window.calls=[];
                    window.currentItem={id:'d715b0e9-b3c4-451b-a909-5fa233f8a0e5',catalogue_id:'cat-a',inventory_code:'INV-TEST',version:1,
                      status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',product_type:'CARD',game:'One Piece',language:'Japanese',name:'Synthetic card',set_name:'Synthetic set',condition:null,
                      market_value_minor:null,store_price_minor:null,approval_blockers:['Drop Rate selling review'],shopify_sync_enabled:true};
                    apiRequest=async(url,options={})=>{
                      calls.push({url,...options});
                      if(options.method){
                        currentItem={...currentItem,version:2,status:'INSPECTION',sale_intent:'FOR_SALE',store_price_minor:1234,condition:'Near Mint'};
                        return {message:'Listing review requested'};
                      }
                      return {item:currentItem,copies:[currentItem]};
                    };
                    await DropRateInventory.open(currentItem);
                }''')
                assert not page.locator('.owner-item-selling').evaluate('e=>e.open')
                assert page.get_by_label('Your selling price in pounds').is_hidden()
                assert page.get_by_label('Condition when selling').is_hidden()
                assert not page.evaluate('calls.some(c=>c.method)')
                page.screenshot(path=str(OUT/f'{engine}-{width}-collection-detail.png'))
                page.locator('.owner-item-selling summary').click()
                assert not page.evaluate('calls.some(c=>c.method)'),'Opening disclosure mutated stock'
                page.get_by_label('Your selling price in pounds').fill('12.34')
                page.get_by_role('button',name='Request listing review',exact=True).click()
                assert not page.evaluate('calls.some(c=>c.method)')
                assert 'already saved' in page.locator('.owner-item-message').inner_text()
                page.get_by_label('Condition when selling').select_option('Near Mint')
                page.screenshot(path=str(OUT/f'{engine}-{width}-listing-detail.png'))
                page.get_by_role('button',name='Request listing review',exact=True).click()
                page.wait_for_function('calls.some(c=>c.method)')
                writes=page.evaluate('calls.filter(c=>c.method)')
                assert len(writes)==1 and writes[0]['url'].endswith('/approval-request')
                assert json.loads(writes[0]['body'])=={'version':1,'store_price_minor':1234,'condition':'Near Mint'}
                assert not any('/sync' in c['url'] for c in page.evaluate('calls'))
                assert not errors,errors
                results.append({'engine':engine,'width':width,'passed':True});page.close()
            browser.close()
    (OUT/'selling-results.json').write_text(json.dumps(results,indent=2))
    print(f'PASS: {len(results)} collection disclosure/explicit selling request cases; synthetic responses, not live publication.')

if __name__=='__main__':main()
