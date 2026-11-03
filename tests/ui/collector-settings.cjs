const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(role,saved='electric',missingTools=[]){
 const seller=role==='seller';
 const source=fs.readFileSync(path.join(base,seller?'owner.html':'index.html'),'utf8');
 const dom=new JSDOM(source.replace(/<script[^>]*><\/script>/g,''),{url:'https://example.test/'+(seller?'owner':'app'),runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,run=code=>vm.runInContext(code,dom.getInternalVMContext()),errors=[];
 for(const key of missingTools)w.document.querySelector(`#owner-view-more [data-owner-jump="${key}"]`)?.remove();
 w.addEventListener('error',e=>errors.push(e.error));w.scrollTo=()=>{};
 w.matchMedia=()=>({matches:false,addEventListener(){}});
 w.fetch=async()=>({ok:true,json:async()=>({items:[]})});
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.localStorage.setItem('drop-rate-collector-vibe',saved);
 const scripts=[...source.matchAll(/<script src="\/assets\/([^"?]+)[^"]*"/g)].map(m=>m[1]);
 if(!seller)scripts.push(...[...fs.readFileSync(path.join(base,'../main.py'),'utf8').matchAll(/'<script src="\/assets\/([^"?]+)[^"]*" defer/g)].map(m=>m[1]));
 for(const file of [...new Set(scripts)]){
  let text=fs.readFileSync(path.join(base,file),'utf8');
  if(file==='app.js'||file==='owner-portal.js')text=text.replace(/\ninitialise\(\);\s*$/,'\n');
  run(text);
 }
 w.catalogueRequests=[];
 w.catalogueClient={owner:'test-owner',active:()=>true,request:async url=>{w.catalogueRequests.push(url);return {items:[]};}};
 run(`state.session={access_token:'test',user:{id:'test-account'}};${seller?'ownerSharedScanner':'founderSharedScanner'}=()=>window.catalogueClient;`);
 return {w,run,errors,finish:()=>w.close()};
}
(async()=>{
 let checks=0;
 for(const role of ['seller','founder']){
  const f=fixture(role),w=f.w,doc=w.document,seller=role==='seller';
  const home=doc.getElementById(seller?'owner-view-overview':'seller-view-dashboard');
  const settings=doc.getElementById(seller?'owner-view-settings':'seller-view-settings');
  assert.equal(f.errors.length,0);assert.equal(doc.body.dataset.collectorVibe,'electric');
  assert.equal(home.querySelector('[data-vibe]'),null);
  assert.equal(settings.querySelectorAll('[data-vibe]').length,5);
  assert.deepEqual([...settings.querySelectorAll('[data-vibe]')].map(button=>button.textContent),['Default','Ocean','Gold','Ember','Violet']);
  assert.match(settings.querySelector('.collector-appearance p').textContent,/accent for your dark workspace/);
  // Desktop shortcuts reuse only the role's existing destinations; the five
  // primary controls and their keyboard model remain intact on both layouts.
  const primary=[...doc.querySelectorAll(seller?'.owner-nav-item':'.seller-nav-tab')];
  assert.equal(primary.length,5);
  for(const button of primary){
   const icon=button.querySelector('svg.workspace-icon');
   assert.ok(icon);assert.equal(icon.getAttribute('aria-hidden'),'true');assert.equal(icon.getAttribute('focusable'),'false');
  }
  const groups=[...doc.querySelectorAll('.workspace-tool-group')];
  assert.deepEqual(groups.map(group=>group.querySelector('h2').textContent),seller
   ?['Selling','Payouts & finance','Account & settings']
   :['Collection tools','Selling','Payouts & finance','Account & settings']);
  assert.deepEqual(groups.map(group=>[...group.querySelectorAll('.app-more-link')].map(button=>button.dataset[seller?'ownerJump':'moreView'])),seller
   ?[['selling','sales','channels'],['balance','settlements'],['profile','settings']]
   :[['verification','media'],['sales'],['balance','reports'],['settings','accounts']]);
  const shortcuts=[...doc.querySelectorAll('.workspace-secondary-link')];
  assert.deepEqual(shortcuts.map(button=>button.dataset.workspaceView),seller?['selling','sales','balance']:['sales','balance']);
  for(const shortcut of shortcuts){
   shortcut.click();const view=shortcut.dataset.workspaceView;
   assert.equal(w.location.hash,'#'+view);
   assert.equal(doc.getElementById((seller?'owner-view-':'seller-view-')+view).classList.contains('hidden'),false);
   assert.equal(shortcut.getAttribute('aria-current'),'page');
   assert.equal(doc.querySelectorAll('.workspace-secondary-link[aria-current="page"]').length,1);
   assert.equal(doc.querySelector(seller?'.owner-nav-item.active':'.seller-nav-tab.active').dataset[seller?'ownerView':'targetView'],'more');
  }
  if(!seller){
   const tabs=doc.querySelector('.workspace-primary-nav');
   assert.equal(tabs.getAttribute('role'),'tablist');assert.equal(tabs.querySelectorAll('[role="tab"]').length,5);
   assert.equal(doc.querySelectorAll('.workspace-secondary-nav [role="tab"]').length,0);
   Object.defineProperty(w,'innerWidth',{value:390,writable:true});w.dispatchEvent(new w.Event('resize'));
   assert.equal(tabs.getAttribute('aria-orientation'),'horizontal');assert.equal(doc.getElementById('seller-nav').hasAttribute('aria-orientation'),false);
   primary[0].focus();primary[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
   assert.equal(doc.activeElement,primary[1]);
  }
  assert.equal(doc.querySelector('.workspace-approved-logo').getAttribute('src'),'/assets/brand-assets/storefront-logo.png');
  assert.equal(doc.querySelector('.workspace-brand-caption').textContent,seller?'Seller Hub':'Founder HQ');
  assert.equal(doc.querySelector('.workspace-storefront-link').href,'https://droprate.co.uk/');
  const settingsButton=doc.querySelector(seller?'#owner-view-more [data-owner-jump="settings"]':'#seller-view-more [data-more-view="settings"]');
  settingsButton.click();assert.equal(w.location.hash,'#settings');assert.equal(settings.classList.contains('hidden'),false);
  assert.equal(doc.querySelectorAll('.workspace-secondary-link[aria-current="page"]').length,0);
  settings.querySelector('.workspace-back').click();
  assert.equal(w.location.hash,'#more');assert.equal(doc.activeElement,settingsButton);
  settingsButton.click();
  settings.querySelector('[data-vibe="ninja"]').click();
  assert.equal(doc.body.dataset.collectorVibe,'ninja');assert.equal(w.localStorage.getItem('drop-rate-collector-vibe'),'ninja');
  assert.equal(settings.querySelectorAll('[aria-pressed="true"]').length,1);
  if(seller){
   assert.equal(home.querySelector('.collector-finance-row'),null);
   assert.equal(home.querySelector('.collector-explore'),null);
   assert.equal(home.querySelector('.collector-grails'),null);
   assert.equal(home.querySelectorAll('.owner-kpi-card').length,2);
   assert.ok(doc.querySelector('#owner-view-selling #owner-next-payout-amount'));
   home.querySelector('.collector-secondary').click();await tick();await tick();
   assert.equal(w.location.hash,'#search');
  }
  for(const b of home.querySelectorAll('.collector-game[data-system-code]:not([data-system-code=""])')){
   b.click();await tick();await tick();
   assert.equal(w.location.hash,'#search');assert.equal(w.dropRateCatalogue.filters.system_code,b.dataset.systemCode);
   assert.ok(w.catalogueRequests.some(url=>url.includes('system_code='+b.dataset.systemCode)));
   assert.equal(doc.body.dataset.collectorVibe,'ninja');assert.equal(w.localStorage.getItem('drop-rate-collector-vibe'),'ninja');
  }
  Object.assign(w.dropRateCatalogue.filters,{q:'stale',language:'Japanese',owned:'owned',product_type:'SEALED',watch:true});
  w.dropRateCatalogue.set={set_id:'old'};
  home.querySelector(seller?'.collector-secondary':'.collector-game[data-system-code=""]').click();await tick();await tick();
  assert.equal(w.dropRateCatalogue.filters.system_code,'');assert.equal(w.dropRateCatalogue.filters.q,'');
  assert.equal(w.dropRateCatalogue.filters.language,'');assert.equal(w.dropRateCatalogue.filters.owned,'all');
  assert.equal(w.dropRateCatalogue.filters.watch,false);assert.equal(w.dropRateCatalogue.filters.product_type,'CARD');assert.equal(w.dropRateCatalogue.set,null);
  assert.match(w.dropRateCatalogue.find('.dr-browse-content').textContent,/Browse by game/);
  // Re-entering Search from the primary navigation preserves a deliberate filter.
  w.dropRateCatalogue.filters.q='Luffy';await w.openDropRateCatalogue();assert.equal(w.dropRateCatalogue.filters.q,'Luffy');
  assert.equal(f.errors.length,0);f.finish();checks++;
 }
 const invalid=fixture('seller','unknown-theme');assert.equal(invalid.w.document.body.dataset.collectorVibe,'all');invalid.finish();checks++;
 const limited=fixture('seller','all',['selling']);assert.equal(limited.w.document.querySelector('.workspace-secondary-link[data-workspace-view="selling"]'),null);limited.finish();checks++;
 console.log(`Collector settings: ${checks} seller/founder navigation, accessible shortcuts, appearance, persistence and reset cases passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
