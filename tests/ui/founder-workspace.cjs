const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const staticDir = path.join(root, 'backend/app/static');
const source = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const html = source.replace(/<script[^>]*><\/script>/g, '');
const dom = new JSDOM(html, {url:'http://localhost:8765', runScripts:'outside-only', pretendToBeVisual:true});
const ctx = dom.getInternalVMContext();
const errors = [];
dom.window.addEventListener('error', e => errors.push(e.error));
dom.window.matchMedia = () => ({matches:false,addEventListener(){}});
dom.window.fetch = async () => ({ok:true,json:async()=>({items:[]})});
dom.window.HTMLDialogElement.prototype.showModal = function(){ this.open=true; };
dom.window.HTMLDialogElement.prototype.close = function(){ this.open=false; };
const run = code => vm.runInContext(code,ctx);
const scripts = [...source.matchAll(/<script src="\/assets\/([^"?]+)[^"]*"/g)].map(m=>m[1]);
const main = fs.readFileSync(path.join(root,'backend/app/main.py'),'utf8');
scripts.push(...[...main.matchAll(/'<script src="\/assets\/([^"?]+)[^"]*" defer/g)].map(m=>m[1]));
for(const file of scripts){
  let text=fs.readFileSync(path.join(staticDir,file),'utf8');
  if(file==='app.js') text=text.replace(/\ninitialise\(\);\s*$/, '\n');
  vm.runInContext(text,ctx,{filename:file});
}
run(`apiRequest = async () => ({items:[],total:0, owner:{display_name:'Demo founder',email:'preview@example.test'}});`);
const doc=dom.window.document;
assert.equal(errors.length,0);
assert.equal(doc.querySelectorAll('.seller-nav-tab').length,9);
assert.equal(doc.querySelector('#recognition-scanner-panel').closest('[data-seller-view]').dataset.sellerView,'intake');
for(const id of ['new-inventory-button','import-inventory-button']){
  assert.equal(doc.getElementById(id).closest('[data-seller-view]').dataset.sellerView,'intake');
  doc.getElementById(id).click();
}
assert.ok(doc.getElementById('inventory-intake-dialog').open);
assert.ok(doc.getElementById('inventory-import-dialog').open);
doc.querySelectorAll('dialog').forEach(d=>d.close());
run(`renderReadiness({total:120,approved:70,approval_ready:20,missing_cost:12,missing_condition:4,identity_unconfirmed:9});`);
doc.querySelector('.issue-button').click();
assert.equal(dom.window.location.hash,'#inventory');
assert.equal(run('state.issue'),'missing_cost');
assert.match(doc.getElementById('workspace-filter-summary').textContent,/Missing cost/);
doc.getElementById('workspace-clear-filters').click();
assert.equal(run('state.issue'),'');
assert.ok(doc.getElementById('workspace-clear-filters').hidden);
run(`state.brand='Pokemon'; state.status='DRAFT'; state.issue='missing_price';`);
doc.getElementById('workspace-search').value='Luffy';
doc.querySelector('.workspace-search').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
assert.equal(run('state.search'),'Luffy');
assert.equal(run('state.brand + state.status + state.issue'),'');
assert.equal(doc.getElementById('search-input').value,'Luffy');
doc.getElementById('seller-tab-dashboard').focus();
doc.getElementById('seller-tab-dashboard').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
assert.equal(doc.activeElement.id,'seller-tab-intake');
assert.equal(dom.window.location.hash,'#intake');
doc.getElementById('intake-notes').value='Keep this unsaved note';
run(`activateSellerView('inventory',true); activateSellerView('intake',true);`);
assert.equal(doc.getElementById('intake-notes').value,'Keep this unsaved note');
doc.getElementById('inventory-view-table').click();
assert.equal(dom.window.localStorage.getItem('drop-rate-inventory-layout'),'table');
assert.ok(doc.getElementById('inventory-visual-grid').classList.contains('hidden'));
run(`state.recognition.cameraStream = {getTracks: () => [{stop: () => {window.cameraStopped = true;}}]}; activateSellerView('intake', true);`);
assert.equal(dom.window.cameraStopped,undefined,'Camera stays open while using intake');
run(`activateSellerView('verification', true);`);
assert.equal(dom.window.cameraStopped,true,'Leaving intake releases the camera');
run(`renderReadiness({total:0,approved:0,approval_ready:0});`);
assert.match(doc.getElementById('issue-buttons').textContent,/Add your first cards/);
for(const view of run('SELLER_VIEWS.map(v=>v[0])')){
  run(`activateSellerView(${JSON.stringify(view)},true)`);
  assert.equal(doc.querySelectorAll('[data-seller-view]:not(.hidden)').length,1);
  assert.equal(doc.querySelectorAll('[role=tab][aria-selected=true]').length,1);
}
for(const id of ['shopify-settings-panel','ebay-connect-button','owner-invite-create','pricing-adapter-status']){
  assert.ok(doc.getElementById(id).closest('details'),'Settings control retained: '+id);
}
const ids=[...doc.querySelectorAll('[id]')].map(x=>x.id);
assert.equal(new Set(ids).size,ids.length,'No duplicate controls');
run(`activateSellerView('dashboard',true)`);
setTimeout(()=>{
  assert.equal(errors.length,0,errors.map(String).join('\n'));
  console.log('PASS: nine routes, intake dialogs, issue navigation, filter reset, global search, keyboard navigation, unsaved form preservation, saved layout, camera cleanup, empty state, settings and unique controls.');
  dom.window.close();
},100);
