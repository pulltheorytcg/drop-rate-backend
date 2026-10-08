const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(role,saved='electric'){
 const seller=role==='seller';
 const source=fs.readFileSync(path.join(base,seller?'owner.html':'index.html'),'utf8');
 const dom=new JSDOM(source.replace(/<script[^>]*><\/script>/g,''),{url:'https://example.test/'+(seller?'owner':'app'),runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,run=code=>vm.runInContext(code,dom.getInternalVMContext()),errors=[];
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
  const settingsButton=doc.querySelector(seller?'#owner-view-more [data-owner-jump="settings"]':'#seller-view-more [data-more-view="settings"]');
  settingsButton.click();assert.equal(w.location.hash,'#settings');assert.equal(settings.classList.contains('hidden'),false);
  settings.querySelector('[data-vibe="ninja"]').click();
  assert.equal(doc.body.dataset.collectorVibe,'ninja');assert.equal(w.localStorage.getItem('drop-rate-collector-vibe'),'ninja');
  assert.equal(settings.querySelectorAll('[aria-pressed="true"]').length,1);
  for(const b of home.querySelectorAll('.collector-game[data-system-code]:not([data-system-code=""])')){
   b.click();await tick();await tick();
   assert.equal(w.location.hash,'#search');assert.equal(w.dropRateCatalogue.filters.system_code,b.dataset.systemCode);
   assert.ok(w.catalogueRequests.some(url=>url.includes('system_code='+b.dataset.systemCode)));
   assert.equal(doc.body.dataset.collectorVibe,'ninja');assert.equal(w.localStorage.getItem('drop-rate-collector-vibe'),'ninja');
  }
  Object.assign(w.dropRateCatalogue.filters,{q:'stale',language:'Japanese',owned:'owned',product_type:'SEALED',watch:true});
  w.dropRateCatalogue.set={set_id:'old'};
  home.querySelector('.collector-game[data-system-code=""]').click();await tick();await tick();
  assert.equal(w.dropRateCatalogue.filters.system_code,'');assert.equal(w.dropRateCatalogue.filters.q,'');
  assert.equal(w.dropRateCatalogue.filters.language,'');assert.equal(w.dropRateCatalogue.filters.owned,'all');
  assert.equal(w.dropRateCatalogue.filters.watch,false);assert.equal(w.dropRateCatalogue.filters.product_type,'');assert.equal(w.dropRateCatalogue.set,null);
  assert.match(w.dropRateCatalogue.find('.dr-browse-content').textContent,/Browse card games/);
  // Re-entering Search from the primary navigation preserves a deliberate filter.
  w.dropRateCatalogue.filters.q='Luffy';await w.openDropRateCatalogue();assert.equal(w.dropRateCatalogue.filters.q,'Luffy');
  assert.equal(f.errors.length,0);f.finish();checks++;
 }
 const invalid=fixture('seller','unknown-theme');assert.equal(invalid.w.document.body.dataset.collectorVibe,'all');invalid.finish();checks++;
 console.log(`Collector settings: ${checks} seller/founder game-navigation, appearance, persistence and reset cases passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
