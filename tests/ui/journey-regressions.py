"""Actual hub JavaScript with controlled races; synthetic HTTP, no live credentials.

The initial baseline reproduction is recorded in the QA report. This final
regression suite always requires every assertion to pass.
"""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2] / 'backend/app/static'
OUT = Path(os.getenv('JOURNEY_LAYOUT_DIR', '/tmp/journey-regressions'))


def shell(browser, role='seller'):
    page = browser.new_page(viewport={'width': 390, 'height': 900})
    html = re.sub(r'<script[^>]*>.*?</script>', '', (ROOT / ('index.html' if role == 'founder' else 'owner.html')).read_text(), flags=re.S)
    page.route('**/*', lambda r: r.abort())
    page.set_content(html)
    # Opaque-origin offline fixture: Storage is a synthetic per-page adapter.
    page.evaluate('''()=>{for(const name of ['sessionStorage','localStorage']){const data=new Map();Object.defineProperty(window,name,{value:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k),clear:()=>data.clear()}});}}''')
    page.add_script_tag(content=(ROOT/'hub-session.js').read_text())
    page.add_script_tag(content=(ROOT/'inventory-groups.js').read_text())
    page.add_script_tag(content=re.sub(r'\ninitialise\(\);\s*$', '', (ROOT/('app.js' if role == 'founder' else 'owner-portal.js')).read_text()))
    page.evaluate('''()=>{state.session={access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}};PullTheoryHubSession.save(state.session);
      window.switchAccount=()=>saveSession({access_token:'token-b',refresh_token:'refresh-b',user:{id:'owner-b'}});
      window.outcome=p=>p.then(value=>({returned:true,value}),e=>({returned:false,error:e.message,code:e.code||e.name}));}''')
    return page


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results=[]
    def check(engine, role, name, passed, actual):
        results.append(dict(engine=engine, role=role, case=name, passed=bool(passed), actual=actual))
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES','chromium,webkit').split(','):
            options={'headless':True}
            if engine=='chromium' and os.getenv('CHROMIUM_EXECUTABLE'):
                options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
            browser=getattr(p,engine).launch(**options)
            for role in ('seller','founder'):
                page=shell(browser,role)
                for code in (200,401,403):
                    actual=page.evaluate('''async code=>{
                      saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                      let release;const requests=[];fetch=async (url,options)=>{requests.push(options.headers.Authorization);
                        if(requests.length===1)return await new Promise(r=>release=r);return {ok:true,status:200,json:async()=>({acceptedFor:'owner-b'})};};
                      authRequest=async()=>({access_token:'refreshed-b',refresh_token:'refresh-b',user:{id:'owner-b'}});
                      const pending=outcome(apiRequest('/synthetic-intake',{method:'POST',body:'{"test":true}'}));
                      switchAccount();release({status:code,ok:code===200,json:async()=>({private:'owner-a-only',detail:'owner-a-private-error'})});
                      return {result:await pending,requests,user:state.session.user.id};
                    }''',code)
                    check(engine,role,f'old-{code}-response-and-write-never-replayed-as-new-owner',not actual['result']['returned'] and len(actual['requests'])==1 and 'owner-a-private' not in actual['result'].get('error',''),actual)
                actual=page.evaluate('''async()=>{
                  saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                  let release;fetch=async()=>({status:200,ok:true,json:()=>new Promise(r=>release=r)});
                  const pending=outcome(apiRequest('/synthetic-overview'));await Promise.resolve();await Promise.resolve();
                  switchAccount();release({private:'owner-a-only'});return await pending;
                }''')
                check(engine,role,'account-change-during-json-body-read',not actual['returned'],actual)
                actual=page.evaluate('''async()=>{
                  saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                  let release;authRequest=()=>new Promise(r=>release=r);
                  const pending=outcome(hydrateSessionUser());switchAccount();release({id:'owner-a'});
                  return {result:await pending,user:state.session.user.id};
                }''')
                check(engine,role,'old-user-hydration-cannot-overwrite-new-account',actual['user']=='owner-b' and not actual['result']['returned'],actual)
                actual=page.evaluate('''async()=>{
                  saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                  let release;fetch=()=>new Promise(r=>release=r);const pending=outcome(apiRequest('/synthetic-overview'));
                  clearSession();saveSession({access_token:'new-a',refresh_token:'new-refresh-a',user:{id:'owner-a'}});
                  release({status:200,ok:true,json:async()=>({private:'old-login'})});return await pending;
                }''')
                check(engine,role,'logout-and-same-owner-login-invalidates-old-work',not actual['returned'],actual)
                actual=page.evaluate('''async()=>{
                  saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                  let count=0;fetch=async()=>++count===1?{status:401,ok:false}:{status:200,ok:true,json:async()=>({saved:true})};
                  authRequest=async()=>({access_token:'fresh-a',refresh_token:'fresh-refresh-a',user:{id:'owner-a'}});
                  return {result:await outcome(apiRequest('/same-owner')),count};
                }''')
                check(engine,role,'legitimate-same-account-token-refresh-preserved',actual['result']['returned'] and actual['count']==2,actual)
                actual=page.evaluate('''async()=>{
                  saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                  let releaseA,releaseB;authRequest=async(path,options)=>{
                    const owner=JSON.parse(options.body).refresh_token;
                    return await new Promise(r=>{if(owner==='refresh-a')releaseA=r;else releaseB=r;});};
                  const old=outcome(refreshSession());await Promise.resolve();
                  clearSession();switchAccount();const fresh=outcome(refreshSession());await Promise.resolve();
                  releaseA({access_token:'late-a',refresh_token:'ra',user:{id:'owner-a'}});
                  const oldResult=await old;
                  const third=outcome(refreshSession());await Promise.resolve();
                  const started=typeof releaseB==='function';
                  if(started)releaseB({access_token:'fresh-b',refresh_token:'rb',user:{id:'owner-b'}});
                  return {oldResult,newResult:await fresh,third:await third,user:state.session?.user?.id};
                }''')
                check(engine,role,'old-refresh-cannot-block-or-reset-new-account-refresh',not actual['oldResult']['returned'] and actual['newResult']['returned'] and actual['third']['returned'] and actual['user']=='owner-b',actual)
                if role=='founder':
                    actual=page.evaluate('''async()=>{
                      saveSession({access_token:'token-a',refresh_token:'refresh-a',user:{id:'owner-a'}});
                      let release;fetch=async()=>({status:200,ok:true,blob:()=>new Promise(r=>release=r)});
                      const pending=outcome(apiImageBlob('/synthetic-image'));await Promise.resolve();await Promise.resolve();switchAccount();release(new Blob(['fake']));return await pending;
                    }''')
                    check(engine,role,'private-image-body-scoped-to-original-account',not actual['returned'],actual)
                page.close()

            page=shell(browser)
            actual=page.evaluate('''async()=>{
              let first;let calls=0;apiRequest=async()=>++calls===1?new Promise(r=>first=r):{total:1,items:[{inventory_id:'new',inventory_code:'NEW-RESULT',name:'New result'}],channels:[]};
              const old=loadOwnerChannels();state.channels.search='new';await loadOwnerChannels();
              first({total:77,items:[{inventory_id:'old',inventory_code:'OLD-RESULT',name:'Old result'}],channels:[]});await old;
              return {total:state.channels.total,text:document.getElementById('owner-channels-body').textContent};
            }''')
            check(engine,'seller','late-channel-search-cannot-overwrite-new-filter',actual['total']==1 and 'NEW-RESULT' in actual['text'] and 'OLD-RESULT' not in actual['text'],actual)
            for reason in ('Consignor eBay publishing is not enabled yet','eBay v1 only supports individual physical cards'):
                actual=page.evaluate('''reason=>{renderOwnerChannelsRows([{inventory_id:'synthetic',inventory_code:'INV-SYN',name:'Synthetic',inventory_status:'APPROVED',sale_intent:'FOR_SALE',channel_sync_blockers:{EBAY:reason}}],[{code:'EBAY',label:'Drop Rate eBay',sync_enabled:true}]);const body=document.getElementById('owner-channels-body');return {text:body.textContent,buttons:Array.from(body.querySelectorAll('button')).map(b=>b.textContent)};}''',reason)
                check(engine,'seller','unsupported-channel-scope-'+reason.split()[0],reason in actual['text'] and not any('eBay' in x for x in actual['buttons']),actual)
            page.close()
            page=shell(browser)
            page.add_script_tag(content=(ROOT/'owner-imports.js').read_text())
            page.evaluate('''()=>{document.body.classList.remove('hub-restoring');document.getElementById('owner-portal-view').classList.remove('hidden');
              window.importWrites=0;apiRequest=async(url)=>{if(url.endsWith('?limit=8'))return {items:[]};if(url.endsWith('/upload')){importWrites++;return new Promise((resolve,reject)=>{window.releaseImport=resolve;window.rejectImport=reject;});}throw Error('Unexpected '+url);};
              window.openImporter=()=>{document.getElementById('owner-import-trigger').click();document.querySelector('[data-owner-import-adapter="COLLECTR"]').click();};openImporter();}''')
            page.locator('#owner-import-file').set_input_files({'name':'synthetic.csv','mimeType':'text/csv','buffer':b'Name,Quantity\nSynthetic,1\n'})
            page.wait_for_function("document.getElementById('owner-import-message').textContent.includes('headers detected')")
            page.evaluate("document.getElementById('owner-import-form').requestSubmit()")
            page.wait_for_function('window.importWrites===1')
            page.evaluate("document.getElementById('owner-import-close').click();openImporter()")
            actual=page.evaluate("({disabled:document.getElementById('owner-import-preview').disabled,fileDisabled:document.getElementById('owner-import-file').disabled,open:document.getElementById('owner-import-dialog').open})")
            check(engine,'seller','import-reopens-usable-while-old-upload-pending',actual['open'] and not actual['disabled'] and not actual['fileDisabled'],actual)
            page.evaluate("rejectImport(Error('old-context-failure'))");page.wait_for_timeout(30)
            actual=page.locator('#owner-import-message').text_content()
            check(engine,'seller','late-upload-error-does-not-overwrite-reopened-dialog','could not finish' not in actual,actual)
            page.evaluate("PullTheoryHubSession.clear()")
            actual=page.evaluate("document.getElementById('owner-import-dialog').open")
            check(engine,'seller','expired-session-clears-open-import-ui',not actual,actual)
            page.close()

            page=shell(browser)
            page.add_script_tag(content=(ROOT/'owner-imports.js').read_text())
            page.evaluate('''()=>{
              document.body.classList.remove('hub-restoring');document.getElementById('owner-portal-view').classList.remove('hidden');
              window.batch={batch:{id:'batch-a',status:'PREVIEW',version:1,adapter:'COLLECTR',physical_units:2,source_rows:2},candidates:[
                {id:'ready',source_row:2,status:'READY',quantity:1,normalized_record:{name:'Ready synthetic'}},
                {id:'review',source_row:3,status:'REVIEW',quantity:1,issues:['catalogue_not_found'],normalized_record:{name:'Review synthetic',card_number:'OLD',set_name:'Set'}}]};
              window.mode='normal';window.searchReleases={};window.mutations=[];window.confirm=()=>true;
              loadOwnerInventory=async()=>{};loadOwnerOverview=async()=>{};
              apiRequest=async(url,options={})=>{
                if(url.endsWith('?limit=8'))return {items:[{id:'batch-a',filename:'synthetic.csv',status:'PREVIEW',adapter:'COLLECTR'}]};
                if(url.includes('catalogue-search?'))return new Promise(r=>searchReleases[new URLSearchParams(url.split('?')[1]).get('q')]=r);
                if(options.method==='POST'){mutations.push(url);return new Promise((resolve,reject)=>{window.pendingMutations??={};pendingMutations[url]={resolve,reject};});}
                if(mode==='resume-delay')return new Promise(r=>{window.resumeRelease=r});
                return structuredClone(batch);
              };
              window.openImporter=()=>{document.getElementById('owner-import-trigger').click();document.querySelector('[data-owner-import-adapter="COLLECTR"]').click();};openImporter();
            }''')
            page.wait_for_selector('.owner-import-history-row button');page.locator('.owner-import-history-row button').click()
            page.wait_for_selector('.owner-import-row-actions button');page.locator('.owner-import-row-actions button').first.click()
            page.wait_for_function("Object.keys(searchReleases).length===1")
            search=page.locator('.owner-import-resolver input');search.fill('NEW');search.press('Enter')
            page.wait_for_function("Boolean(searchReleases.NEW)")
            page.evaluate("searchReleases.NEW({items:[{id:'new-card',name:'New exact result'}]})")
            page.wait_for_function("document.querySelector('.owner-import-resolver-results').textContent.includes('New exact result')")
            page.evaluate("searchReleases['OLD Set']({items:[{id:'old-card',name:'Old stale result'}]})");page.wait_for_timeout(30)
            actual=page.locator('.owner-import-resolver-results').inner_text()
            check(engine,'seller','latest-import-search-wins','New exact result' in actual and 'Old stale result' not in actual,actual)
            page.locator('#owner-import-commit').click();page.wait_for_function("mutations.some(u=>u.endsWith('/commit'))")
            page.evaluate("document.getElementById('owner-import-close').click();openImporter()")
            page.locator('#owner-import-file').set_input_files({'name':'synthetic-2.csv','mimeType':'text/csv','buffer':b'Name,Quantity\nSynthetic,1\n'})
            page.wait_for_function("document.getElementById('owner-import-message').textContent.includes('headers detected')")
            page.evaluate("document.getElementById('owner-import-form').requestSubmit()")
            page.wait_for_function("mutations.some(u=>u.endsWith('/upload'))")
            page.evaluate("pendingMutations['/api/v1/owner/imports/batch-a/commit'].reject(Error('Old commit failure'))");page.wait_for_timeout(30)
            actual=page.evaluate("({disabled:document.getElementById('owner-import-preview').disabled,message:document.getElementById('owner-import-message').textContent})")
            check(engine,'seller','old-commit-error-cannot-unlock-new-upload',actual['disabled'] and 'could not finish' not in actual['message'],actual)
            page.evaluate("document.getElementById('owner-import-close').click();pendingMutations['/api/v1/owner/imports/upload'].reject(Error('Closed upload'));openImporter();mode='resume-delay';")
            page.wait_for_selector('.owner-import-history-row button');page.locator('.owner-import-history-row button').click()
            page.wait_for_function("typeof resumeRelease==='function'")
            page.evaluate("document.getElementById('owner-import-close').click();mode='normal';openImporter();resumeRelease(structuredClone(batch));");page.wait_for_timeout(30)
            actual=page.evaluate("({previewHidden:document.getElementById('owner-import-preview-section').hidden,disabled:document.getElementById('owner-import-preview').disabled})")
            check(engine,'seller','old-resume-cannot-restore-batch-into-new-dialog',actual['previewHidden'] and not actual['disabled'],actual)
            page.close()

            page=shell(browser)
            for name in ('reference-value-display.js','owner-inventory.js'):
                page.add_script_tag(content=(ROOT/name).read_text())
            page.evaluate('''()=>{window.currentItem={id:'00000000-0000-4000-8000-000000000001',name:'Synthetic',catalogue_id:'synthetic-card',product_type:'CARD',language:'Japanese',condition:'Near Mint',status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',version:1,store_price_minor:null,reference_value:{status:'AVAILABLE',market_value_minor:1200,recommended_retail_minor:1200}};
              apiRequest=async()=>({item:currentItem,copies:[currentItem]});DropRateInventory.open(currentItem);}''')
            page.wait_for_selector('dialog .owner-item-selling');page.locator('.owner-item-selling summary').click()
            field=page.get_by_label('Your selling price in pounds')
            page.get_by_label('Condition when selling').select_option('Lightly Played')
            check(engine,'seller','wrong-condition-clears-automatic-suggestion',field.input_value()=='',field.input_value())
            page.get_by_label('Condition when selling').select_option('Near Mint')
            actual={'value':field.input_value(),'note':page.locator('[data-recommended-retail]').inner_text()}
            check(engine,'seller','returning-to-matched-condition-restores-untouched-suggestion',actual['value']=='12.00' and 'does not apply' not in actual['note'],actual)
            field.fill('18.25');page.get_by_label('Condition when selling').select_option('Lightly Played');page.get_by_label('Condition when selling').select_option('Near Mint')
            check(engine,'seller','manual-price-survives-condition-round-trip',field.input_value()=='18.25',field.input_value())
            page.close();browser.close()
    (OUT/'results.json').write_text(json.dumps(results,indent=2))
    failed=[f"{r['engine']}/{r['role']}/{r['case']}" for r in results if not r['passed']]
    print(json.dumps({'checks':len(results),'failures':failed},indent=2))
    assert not failed,failed

if __name__=='__main__':main()
