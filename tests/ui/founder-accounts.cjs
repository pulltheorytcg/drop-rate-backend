/* DOM/API-state tests; API responses mocked. Real JWT/PostgreSQL runs separately. */
const {JSDOM}=require('jsdom'), fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('../../backend/app/static/founder-accounts.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
 const dom=new JSDOM('<head></head><body><div id="dashboard-view"><div class="topbar-actions"></div></div><button data-more-view="accounts">Business</button><section data-seller-view="accounts"></section></body>',{runScripts:'outside-only',url:'https://business.test/app'});
 const run=code=>vm.runInContext(code,dom.getInternalVMContext());
 run(`const state={session:{access_token:'test',user:{id:'founder'}}};const byId=id=>document.getElementById(id);const sellerView=()=>document.querySelector('section');let reloadDashboard=async()=>{};const activateSellerView=()=>{};const requests=[];const pending=[];let permit=true;let fail=false;let deferred=false;
 let apiRequest=async(url,options)=>{requests.push({url,options});if(url==='/api/v1/access/me')return {access:{business_allowed:permit}};
 if(fail)throw Object.assign(new Error('denied'),{status:403});
 if(url==='/api/v1/founder/accounts')return {own_owner_id:'a',accounts:[{id:'a',display_name:'First founder',owner_type:'FOUNDER',username:'first',active_stock_count:2,for_sale_count:1,draft_count:1},{id:'b',display_name:'Seller <img src=x>',owner_type:'CONSIGNOR',username:'seller-b',active_stock_count:3,draft_count:3}]};
 if(deferred)return new Promise(resolve=>pending.push({url,resolve}));
 if(url.includes('/activity'))return {sales:[],payouts:[]};
 return {items:[{owner_id:'b',owner_name:'Seller B',inventory_code:'INV-ONE',name:'Shared card',status:'DRAFT',sale_intent:'FOR_SALE',market_value_minor:null}],total:1};};`);
 run(source);return {dom,run,doc:dom.window.document};
}
(async()=>{
 const {dom,run,doc}=harness();
 assert(doc.querySelector('[data-more-view]').hidden);assert(doc.getElementById('business-content').hidden);
 run(`document.dispatchEvent(new Event('hub-ready'))`);await tick();
 assert(!doc.querySelector('[data-more-view]').hidden);
 assert(run('requests.every(r=>r.url==="/api/v1/access/me")'),'No business data fetched merely showing the menu');
 run(`document.dispatchEvent(new CustomEvent('seller-view-changed',{detail:{view:'accounts'}}))`);await tick();await tick();
 assert.match(doc.getElementById('accounts-summary').textContent,/Approved for sale/);
 doc.getElementById('business-tab-sellers').click();await tick();await tick();
 const search=doc.getElementById('business-seller-search');search.value='seller-b';search.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
 assert.equal(doc.querySelectorAll('.business-seller-card').length,1);assert.equal(doc.querySelectorAll('.business-seller-card img').length,0);
 doc.querySelector('.business-seller-card button').click();await tick();await tick();
 assert.equal(doc.getElementById('accounts-owner').value,'b');assert.match(doc.getElementById('accounts-results').textContent,/INV-ONE/);
 assert.match(doc.getElementById('accounts-results').textContent,/Not recorded/);
 run('deferred=true');const owner=doc.getElementById('accounts-owner');owner.value='a';owner.dispatchEvent(new dom.window.Event('change'));await tick();
 owner.value='b';owner.dispatchEvent(new dom.window.Event('change'));await tick();
 assert.match(run('pending[1].url'),/owner_id=b/);
 run(`pending[1].resolve({items:[{owner_id:'b',owner_name:'Second',name:'Current item',inventory_code:'INV-CURRENT'}],total:1})`);await tick();
 run(`pending[0].resolve({items:[{owner_name:'First',name:'Stale item'}],total:1})`);await tick();
 assert.match(doc.getElementById('accounts-results').textContent,/Current item/);assert.doesNotMatch(doc.getElementById('accounts-results').textContent,/Stale item/);
 owner.value='a';owner.dispatchEvent(new dom.window.Event('change'));await tick();
 run(`state.session=null;window.dispatchEvent(new Event('hub-session-cleared'));pending[2].resolve({items:[{name:'After logout'}],total:1})`);await tick();
 assert.equal(doc.getElementById('accounts-results').textContent,'');assert.equal(doc.getElementById('accounts-summary').textContent,'');assert.equal(owner.options.length,1);assert(doc.getElementById('business-content').hidden);
 assert(run('requests.every(r=>r.options===undefined)'),'Business must not issue mutations');dom.window.close();
 const denied=harness();denied.run(`permit=false;document.dispatchEvent(new CustomEvent('seller-view-changed',{detail:{view:'accounts'}}))`);await tick();await tick();
 assert(denied.doc.querySelector('[data-more-view]').hidden);assert(denied.doc.getElementById('business-content').hidden);assert(denied.run('requests.every(r=>r.url==="/api/v1/access/me")'));denied.dom.window.close();
 const revoked=harness();revoked.run(`document.dispatchEvent(new CustomEvent('seller-view-changed',{detail:{view:'accounts'}}))`);await tick();await tick();revoked.run('fail=true');revoked.doc.getElementById('business-refresh').click();await tick();await tick();
 assert.equal(revoked.doc.getElementById('accounts-summary').textContent,'');assert(revoked.doc.getElementById('business-content').hidden);revoked.dom.window.close();
 console.log('PASS: Business capability/menu denial, seller username search, escaped account names, exact owner/copy navigation, missing-value label, stale response suppression, logout/revocation cleanup and GET-only requests. Mocked API/DOM tests.');
})().catch(error=>{console.error(error);process.exitCode=1;});
