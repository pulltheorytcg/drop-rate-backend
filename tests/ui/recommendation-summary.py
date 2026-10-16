"""Real overview/detail JavaScript with intercepted synthetic API responses, not live login."""
import json, os, re
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]/'backend/app/static'
OUT=Path(os.getenv('RECOMMENDATION_LAYOUT_DIR','/tmp/recommendation-layout'))


def main():
    OUT.mkdir(parents=True,exist_ok=True); results=[]
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES','chromium,webkit').split(','):
            kwargs={'headless':True}
            if engine=='chromium' and os.getenv('CHROMIUM_EXECUTABLE'):kwargs['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
            browser=getattr(p,engine).launch(**kwargs)
            for width in (320,390,1440):
                page=browser.new_page(viewport={'width':width,'height':1000}); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.abort())
                html=re.sub(r'<script[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S)
                page.set_content(html)
                for name in re.findall(r'href="/assets/([^?"/]+\.css)',html):page.add_style_tag(content=(ROOT/name).read_text())
                for name in ('hub-session.js','reference-value-display.js','owner-inventory.js'):page.add_script_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content=re.sub(r'\ninitialise\(\);\s*$','',(ROOT/'owner-portal.js').read_text()))
                page.evaluate('''()=>{document.body.classList.remove('hub-restoring');document.getElementById('owner-auth-view')?.classList.add('hidden');document.getElementById('owner-portal-view').classList.remove('hidden');state.session={access_token:'synthetic',user:{id:'owner-a'}};window.calls=[];window.summary={};apiRequest=async(url,options={})=>{calls.push({url,method:options.method||'GET'});return url.endsWith('/overview')?{summary}:{item:currentItem,copies:[currentItem]}};}''')
                for status,count,total,recommended,expected in [('partial',6,99,14132,'£20.00'),('none',0,99,None,'£20.00'),('empty',0,0,None,'£0.00')]:
                    payload={'total_inventory_count':total,'active_inventory_count':total,'active_valued_count':count,'active_unvalued_count':total-count,'active_market_value_minor':14035 if count else None,
                             'active_recommended_count':count,'active_unrecommended_count':total-count,'active_recommended_retail_minor':recommended,'recommendation_guide_count':1 if count else 0,
                             'recorded_asking_count':2 if total else 0,'recorded_asking_value_minor':2000 if total else None,'active_store_value_minor':2000}
                    page.evaluate('data=>{summary=data}',payload); page.evaluate('loadOwnerOverview()')
                    assert page.locator('#owner-store-value').text_content()==expected,(status,expected,page.locator('#owner-store-value').text_content(),page.evaluate('calls'),errors)
                    recommendation=page.locator('#owner-recommendation-note').inner_text()
                    if count:
                        assert f'{count} of {total}' in recommendation
                        assert '£141.32' in recommendation
                    elif total:
                        assert 'Automatic recommendation unavailable' in recommendation
                    if total:
                        assert '£20.00' == page.locator('#owner-store-value').inner_text()
                        assert f'2 of {total} copies have saved Store Prices' in page.locator('#owner-asking-price-note').inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(engine,width,status)
                    if width in (390,1440) and status=='partial':page.locator('#owner-view-overview .owner-kpi-grid').screenshot(path=str(OUT/f'{engine}-{width}-overview.png'))
                    results.append({'engine':engine,'width':width,'case':status,'passed':True})
                for status,saved,expected in [('AVAILABLE',None,'12.00'),('REFERENCE_ESTIMATE',None,'12.00'),('STALE',None,''),('UNAVAILABLE',None,''),('AVAILABLE',2000,'20.00')]:
                    item={'id':'00000000-0000-4000-8000-000000000001','catalogue_id':'cat','inventory_code':'INV-SYN','name':'Synthetic card','set_name':'Synthetic set','card_number':'SYN-1','product_type':'CARD','game':'One Piece','language':'Japanese','condition':'Near Mint','status':'DRAFT','sale_intent':'PERSONAL_COLLECTION','version':1,
                          'market_value_minor':1200 if status in ('AVAILABLE','REFERENCE_ESTIMATE') else None,'recommended_retail_minor':999999,'store_price_minor':saved,'approval_blockers':[],
                          'reference_value':{'status':status,'market_value_minor':1200,'recommended_retail_minor':1200,'basis':'Japanese · Near Mint'}}
                    page.evaluate('item=>{window.currentItem=item;calls=[]}',item);page.evaluate('DropRateInventory.open(currentItem)');page.wait_for_selector('dialog .owner-item-selling')
                    page.locator('.owner-item-selling summary').click()
                    price=page.get_by_label('Your selling price in pounds');assert price.input_value()==expected,(status,saved,price.input_value())
                    if status=='REFERENCE_ESTIMATE':assert 'Guide estimate' in page.locator('[data-recommended-retail]').inner_text()
                    page.get_by_label('Condition when selling').select_option('Lightly Played')
                    if saved is None and expected:assert price.input_value()==''
                    if saved:assert price.input_value()==expected
                    assert not page.evaluate("calls.some(c=>c.method!=='GET')")
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(engine,width,status)
                    page.locator('dialog').evaluate('d=>d.close()');results.append({'engine':engine,'width':width,'case':status,'saved_price':saved,'passed':True})
                assert not errors,errors;page.close()
            browser.close()
    (OUT/'results.json').write_text(json.dumps(results,indent=2));print(f'PASS {len(results)} overview/recommendation/prefill/condition cases; actual source, synthetic responses, GET-only.')
if __name__=='__main__':main()
