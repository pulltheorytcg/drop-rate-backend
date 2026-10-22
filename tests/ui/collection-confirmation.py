"""Actual scanner/layout code; synthetic HTTP data, not camera/provider accuracy."""
from __future__ import annotations
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.getenv('COLLECTION_LAYOUT_DIR', '/tmp/collection-confirmation'))

FIXTURE = r'''(args) => {
  if(!crypto.randomUUID)crypto.randomUUID=()=>[4,2,2,2,6].map(n=>Array.from(crypto.getRandomValues(new Uint8Array(n)),v=>v.toString(16).padStart(2,'0')).join('')).join('-');
  window.calls=[]; window.failOnce=false; window.refreshed=0;
  window.session={access_token:'synthetic',user:{id:'seller-a'}};
  window.scanner=new DropRateScanner.Scanner({role:args.role,session:()=>session,
    afterSave:async()=>{refreshed++},viewInventory:()=>{},
    request:async(url,options={})=>{
      calls.push({url,body:options.body,headers:options.headers});
      if(url.endsWith('/feedback'))return {};
      if(url.endsWith('/recognition-intake')||url.endsWith('/graded-certificate-intake')||url.endsWith('/graded-intake')||url.endsWith('/inventory/intake')){
        if(failOnce){failOnce=false;throw new Error('Connection interrupted after send');}
        return {inventory:{id:'saved-a',inventory_code:'INV-SYNTHETIC',status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',identity_confirmed:false}};
      }
      if(url.includes('catalogue-browser'))return {items:[]};
      throw new Error('Unexpected request '+url);
    }});
  const candidate={catalogue_id:'catalogue-a',id:'candidate-a',market_value_minor:null,
    candidate_snapshot:{name:'Synthetic exact printing',game:'One Piece',set_name:'Synthetic set',card_number:'OP99-001',language:'Japanese',variant:'Parallel',product_type:args.mode==='SEALED'?'SEALED':'CARD'}};
  window.item={id:'scan-a',mode:args.mode,quantity:1,condition:'',selected:candidate,status:'matched',
    run:{id:'run-a',decision:'EXACT_CANDIDATE',status:'EXACT_CANDIDATE',top_catalogue_id:'catalogue-a'},candidates:[candidate],
    grading_company:args.mode==='GRADED'?'PSA':null,grade:args.mode==='GRADED'?'10':null,certificate_number:args.mode==='GRADED'?'12345678':null};
  window.uncertain={id:'scan-b',mode:'RAW',quantity:1,condition:'',status:'unresolved',selected:null,candidates:[],run:{id:'run-b',decision:'NEEDS_REVIEW'}};
  scanner.items=[item,uncertain];scanner.dialog.showModal();scanner.showReview();scanner.openDetails(item);
}'''

def main():
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    with sync_playwright() as p:
        engines=os.getenv('BROWSER_ENGINES','chromium,webkit').split(',')
        for engine in engines:
            options={'headless':True}
            if engine=='chromium' and os.getenv('CHROMIUM_EXECUTABLE'):options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
            browser=getattr(p,engine).launch(**options)
            for width in (320,390,1440):
                for role in ('seller','founder'):
                    for mode in ('RAW','GRADED','SEALED'):
                        page=browser.new_page(viewport={'width':width,'height':900});errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.route('**/*',lambda route:route.abort())
                        page.set_content('<html><head><meta name="viewport" content="width=device-width"></head><body></body></html>')
                        page.add_style_tag(content=(ROOT/'backend/app/static/scanner-flow.css').read_text())
                        page.add_script_tag(content=(ROOT/'backend/app/static/reference-value-display.js').read_text())
                        page.add_script_tag(content=(ROOT/'backend/app/static/scanner-flow.js').read_text())
                        page.evaluate(FIXTURE,{'mode':mode,'role':role})
                        if mode=='RAW' and role=='seller':
                            page.evaluate('''item.selected.shared_price={status:'STALE',market_value_minor:null,
                                last_known_minor:1250,checked_at:'2026-10-10T12:00:00Z',
                                basis:'Japanese · Raw catalogue reference',
                                reason:'Last recorded guide; not a current value.',physical_valuation_eligible:false};
                                scanner.renderDetails();''')
                            assert '£12.50 · Last known 10/10/2026' in page.locator('.dr-scan-detail-identity').inner_text()
                            assert page.evaluate('scanner.totals().value') is None
                        confirm=page.locator('[data-details-save]')
                        assert confirm.inner_text()=='Add to collection'
                        assert confirm.is_enabled()
                        assert page.evaluate('calls.length')==0
                        assert 'Japanese' in page.locator('.dr-scan-details').inner_text()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        if mode=='RAW' and role=='seller':page.screenshot(path=str(OUT/f'{engine}-{width}-confirm.png'))
                        confirm.click();page.wait_for_function('item.status==="added" && scanner.saving===false')
                        summary=page.evaluate('({calls,refreshed,unknown:uncertain.requests||null,status:item.status})')
                        saves=[c for c in summary['calls'] if c.get('headers',{}).get('Idempotency-Key')]
                        assert len(saves)==1 and summary['refreshed']==1
                        assert summary['unknown'] is None
                        payload=json.loads(saves[0]['body'])
                        for name in ('owner_id','store_price_minor','acquisition_cost_minor','storage_location_id'):
                            assert name not in payload
                        if mode=='RAW':assert payload['condition'] is None
                        assert payload['language']=='Japanese'
                        assert all('/refresh-market' not in c['url'] and '/sync' not in c['url'] and '/approval-request' not in c['url'] for c in summary['calls'])
                        assert page.locator('.dr-scan-added').inner_text()=='Added to collection'
                        if mode=='RAW' and role=='seller':
                            assert '£12.50 · Last known 10/10/2026' in page.locator('.dr-scan-review-item.added .dr-scan-card-value').inner_text()
                            assert page.evaluate('scanner.totals().value') is None
                        await_saves=len(saves);page.evaluate('scanner.saveAll()')
                        assert len(page.evaluate('calls.filter(c=>c.headers?.["Idempotency-Key"])'))==await_saves
                        assert not errors,errors
                        results.append({'engine':engine,'width':width,'role':role,'mode':mode,'passed':True})
                        page.close()
            page=browser.new_page(viewport={'width':390,'height':900})
            page.goto('about:blank');page.add_script_tag(content=(ROOT/'backend/app/static/scanner-flow.js').read_text())
            page.evaluate(FIXTURE,{'mode':'RAW','role':'seller'})
            page.evaluate('failOnce=true; scanner.confirmDetails()')
            assert page.evaluate('item.status')=='save-error'
            page.evaluate('scanner.saveAll()')
            saved=page.evaluate('calls.filter(c=>c.headers?.["Idempotency-Key"])')
            assert len(saved)==2 and saved[0]['body']==saved[1]['body'] and saved[0]['headers']['Idempotency-Key']==saved[1]['headers']['Idempotency-Key']
            assert page.evaluate('item.status')=='added'
            results.append({'engine':engine,'case':'lost-response-retry','passed':True});page.close();browser.close()
    (OUT/'results.json').write_text(json.dumps(results,indent=2))
    print(f'PASS: {len(results)} actual scanner cases. Synthetic API data; no real camera or production login.')
if __name__=='__main__':main()
