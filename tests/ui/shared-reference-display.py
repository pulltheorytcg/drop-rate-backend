"""Actual owner details and founder market column; synthetic API responses.
Not production login, camera recognition, or live provider-price acceptance.
"""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];OUT=Path(os.environ.get('REFERENCE_LAYOUT_DIR','/tmp/reference-layout'))
ID='00000000-0000-4000-8000-000000000001'
def main():
 OUT.mkdir(parents=True,exist_ok=True);results=[]
 with sync_playwright() as p:
  for engine in os.environ.get('BROWSER_ENGINES','chromium,webkit').split(','):
   kwargs={'headless':True}
   if engine=='chromium' and os.environ.get('CHROMIUM_EXECUTABLE'):kwargs['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
   browser=getattr(p,engine).launch(**kwargs)
   for width in (320,390,1440):
    for status in ('AVAILABLE','REFERENCE_ESTIMATE','STALE','NEEDS_DETAILS','UNAVAILABLE','CATALOGUE_GUIDE','CONDITION_REFERENCE','HISTORICAL_GUIDE'):
     page=browser.new_page(viewport={'width':width,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
     page.route('**/*',lambda r:r.fulfill(status=404,body='Synthetic image unavailable'))
     page.set_content('<html><head><meta name="viewport" content="width=device-width"></head><body><table><thead><tr><th>Card</th><th>Store price</th></tr></thead><tbody id="inventory-body"></tbody></table></body></html>')
     page.add_style_tag(content='body{font-family:Arial;background:#fff;color:#142944;margin:16px}button,input,select{font:inherit}*{box-sizing:border-box}')
     page.add_style_tag(content=(ROOT/'backend/app/static/owner-inventory.css').read_text())
     item={'id':ID,'name':'Synthetic exact card','game':'One Piece','set_name':'Exact set','card_number':'TEST-001','language':'Japanese','product_type':'CARD','condition':'Near Mint','status':'DRAFT','sale_intent':'PERSONAL_COLLECTION','version':1,'inventory_code':'INV-TEST','store_price_minor':None,'market_value_minor':9900 if status in ('AVAILABLE','REFERENCE_ESTIMATE') else None,'pricing_method':'CARDMARKET_GUIDE_V1' if status=='REFERENCE_ESTIMATE' else 'LIVE_EBAY_MARKET_V1','approval_blockers':[],'reference_value':{'status':status,'market_value_minor':9900 if status in ('AVAILABLE','REFERENCE_ESTIMATE') else None,'basis':'Japanese · Near Mint','reason':'Synthetic evidence status','checked_at':'2026-10-11T12:00:00Z'}}
     if status in ('CATALOGUE_GUIDE','CONDITION_REFERENCE'):
      item['reference_value']['status']='NEEDS_DETAILS'
      item['catalogue_reference']={'status':status,'market_value_minor':132,'market_value_high_minor':170 if status=='CATALOGUE_GUIDE' else None,'label':'Catalogue guide' if status=='CATALOGUE_GUIDE' else 'Near-mint reference','basis':'English · Raw reference','reason':'Display only; copy details unconfirmed.','checked_at':'2026-10-15T12:00:00Z'}
     if status=='STALE':item['reference_value']['last_known_minor']=9900
     if status=='HISTORICAL_GUIDE':
      item['reference_value']['status']='NEEDS_DETAILS'
      item['catalogue_reference']={'status':'STALE','market_value_minor':None,'last_known_minor':800,'last_known_high_minor':1200,'checked_at':'2026-10-14T12:00:00Z','basis':'English · Raw catalogue reference','source':'Cardmarket','reason':'Last recorded Cardmarket catalogue guide. Refresh unavailable; not a current value.','physical_valuation_eligible':False}
     page.evaluate('''item => {window.item=item;window.calls=[];window.state={session:{access_token:'synthetic',user:{id:'seller-fixture'}}};
       window.formatMoney=n=>n==null?'—':new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(n/100);
       window.inventoryCardSubtitle=x=>x.card_number;window.conditionLabel=x=>x.condition;window.inventoryTypeLabel=x=>x.product_type;window.statusClass=()=>'';window.collectionStatus=x=>x.sale_intent==='PERSONAL_COLLECTION'?'In collection':x.status;
       window.apiRequest=async(path,options={})=>{calls.push({path,method:options.method||'GET'});return path.includes('market-values')?{items:[item]}:{item,copies:[item]}};
       window.renderInventory=data=>{document.getElementById('inventory-body').innerHTML='<tr><td>Exact card</td><td data-label="Store price">Not selling</td></tr>';};
     }''',item)
     for name in ('reference-value-display.js','owner-inventory.js','market-value-column.js'):page.add_script_tag(content=(ROOT/'backend/app/static'/name).read_text())
     page.evaluate('renderInventory({items:[item]})');page.wait_for_function("document.querySelector('[data-market-value-cell]')?.textContent!=='—'")
     assert page.evaluate('calls.length')==0,'Inventory prices must render from the initial payload without another request'
     founder=page.locator('[data-market-value-cell]').inner_text().strip()
     if status in ('CATALOGUE_GUIDE','CONDITION_REFERENCE','STALE','HISTORICAL_GUIDE'):
      page.add_style_tag(content=(ROOT/'backend/app/static/catalogue-browser.css').read_text())
      page.add_script_tag(content=(ROOT/'backend/app/static/catalogue-browser.js').read_text())
      page.evaluate('''async()=>{
       const host=document.createElement('main');document.body.append(host);
       const ref=DropRateReferenceValue.displayReference(item);
       const row={key:'r:'+'a'.repeat(32),name:'Synthetic exact card',game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',
        set_name:'Exact release',set_id:'OP11',provider:'Punk Records',language:'English',product_type:'CARD',
        source_kind:'REFERENCE',variant:'OP11-101',card_number:'OP11-101',catalogue_id:null,owned_quantity:0,
        market_value_minor:ref.market_value_minor,shared_price:ref,market_refresh_needed:true};
       window.browseCalls=[];window.sharedBrowse=new DropRateCatalogue.Browser({host,
        client:{owner:'synthetic',active:()=>true,request:async(path,options={})=>{
         browseCalls.push({path,method:options.method||'GET'});
         return path.endsWith('/market-values')?{items:[{key:row.key,market_value_minor:null,provider_refresh_failed:true}]}:{items:[row]};
        }},
        navigate:()=>{},scan:()=>{}});
       sharedBrowse.filters.q='OP11-101';await sharedBrowse.load();
      }''')
      assert page.locator('[data-price-key]').inner_text().strip()==founder
      if status=='HISTORICAL_GUIDE':
       assert 'Value: £8.00' == founder
       assert page.evaluate('sharedBrowse.rows[0].market_value_minor') is None
       if width in (390,1440):page.screenshot(path=str(OUT/f'{engine}-historical-search-{width}.png'),full_page=True)
      page.evaluate('''async()=>{sharedBrowse.filters.q='';sharedBrowse.filters.system_code='ONE_PIECE_CARD_GAME';
       sharedBrowse.set={system_code:'ONE_PIECE_CARD_GAME',set_id:'OP11',provider:'Punk Records'};await sharedBrowse.load()}''')
      assert page.locator('[data-price-key]').inner_text().strip()==founder
      browse_calls=page.evaluate('browseCalls')
      refreshes=[call for call in browse_calls if call['path'].endswith('/market-values')]
      assert all(call['method']=='GET' or (call['method']=='POST' and call['path'].endswith('/market-values')) for call in browse_calls)
      assert len(refreshes)==(2 if status in ('STALE','HISTORICAL_GUIDE') else 0),'Only dated guides should request a refresh; no inventory writes'
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(engine,width,status,'catalogue')
      if width==390 and status=='CONDITION_REFERENCE':page.screenshot(path=str(OUT/f'{engine}-search-set-immediate-390.png'),full_page=True)
      page.evaluate('sharedBrowse.destroy()')
     page.evaluate('DropRateInventory.open(item)');page.wait_for_selector('.owner-item-values strong')
     seller=page.locator('.owner-item-values strong').inner_text().strip();assert founder.removeprefix('Value: ')==seller,(status,founder,seller)
     if status in ('AVAILABLE','REFERENCE_ESTIMATE','STALE'):assert '£99.00' == seller
     elif status in ('CATALOGUE_GUIDE','CONDITION_REFERENCE'):assert '£1.32' == seller
     elif status=='HISTORICAL_GUIDE':assert '£8.00' == seller
     else:assert '£0' not in seller and 'pending' not in seller.lower()
     assert all(call['method']=='GET' for call in page.evaluate('calls'))
     assert not errors,errors
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(engine,width,status)
     if width in (390,1440) and status in ('AVAILABLE','UNAVAILABLE'):
      page.screenshot(path=str(OUT/f'{engine}-{width}-{status}.png'),full_page=True)
     results.append({'engine':engine,'width':width,'status':status,'same_display':True});page.close()
   browser.close()
 (OUT/'results.json').write_text(json.dumps(results,indent=2));print(f'PASS {len(results)} paired founder/seller display cases; synthetic responses, bounded stale-guide refresh and no inventory writes.')
if __name__=='__main__':main()
