const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-browser.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const card={key:'c:00000000-0000-0000-0000-000000000001',catalogue_id:'card-1',name:'Luffy',game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',set_name:'A Fist of Divine Speed',set_id:'OP11',language:'English',product_type:'CARD',variant:'Foil',card_number:'OP11-118',owned_quantity:0,market_value_minor:null,source_kind:'CATALOGUE'};
const games=[{game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',languages:['English','Japanese']}];
let checks=0;
function fixture(handler=async()=>({items:[card],has_more:false}),owner='account-a'){
 const dom=new JSDOM('',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});const w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.eval(source);let alive=true;const calls=[];
 const client={owner,active:()=>alive,request:async(url,options)=>{calls.push({url,...options});return url.endsWith('/games')?{items:games}:handler(url,options);}};
 const browser=new w.DropRateCatalogue.Browser({client,navigate:()=>{},scan:()=>{},graded:()=>{},afterSave:async()=>{}});
 return {browser,w,calls,logout:()=>{alive=false;browser.destroy();},finish:()=>{browser.destroy();w.close();}};
}
(async()=>{
 {
  const f=fixture();await f.browser.open();assert.match(f.browser.find('.dr-browse-content').textContent,/Quick Filters/);
  assert.equal(f.calls.length,1);f.browser.filters.product_type='SEALED';await f.browser.load();
  assert.match(f.calls.at(-1).url,/product_type=SEALED/);assert.match(f.browser.find('.dr-browse-chips').textContent,/Sealed Only/);
  f.browser.reset();assert.equal(f.browser.filters.product_type,'');assert.match(f.browser.find('.dr-browse-content').textContent,/Quick Filters/);
  f.finish();checks++;
 }
 {
  const f=fixture(async url=>url.includes('/sets')?{items:[{system_code:'ONE_PIECE_CARD_GAME',set_id:'OP11',set_name:'A Fist of Divine Speed',language:'Japanese',provider:'Punk Records',indexed_count:200,owned_count:0,owned_value_minor:null,unknown_values:0}]}:{items:[card]});
  await f.browser.open();f.browser.pickGame(games[0]);await tick();f.browser.showSets();await tick();
  assert.equal(f.browser.filters.language,'English');
  [...f.browser.find('.dr-browse-languages').children].find(n=>n.textContent==='Japanese').click();await tick();
  assert.match(f.calls.at(-1).url,/language=Japanese/);
  f.browser.find('.dr-browse-set').click();await tick();
  assert.match(f.calls.at(-1).url,/set_id=OP11/);assert.match(f.calls.at(-1).url,/provider=Punk\+Records/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value pending/);
  f.finish();checks++;
 }
 {
  const one=deferred(),two=deferred();const f=fixture(url=>url.includes('q=old')?one.promise:two.promise);
  f.browser.games=games;f.browser.filters.q='old';const older=f.browser.load();f.browser.filters.q='new';const newer=f.browser.load();
  two.resolve({items:[{...card,name:'New result'}]});await newer;one.resolve({items:[{...card,name:'Old result'}]});await older;
  assert.match(f.browser.find('.dr-browse-content').textContent,/New result/);assert.doesNotMatch(f.browser.find('.dr-browse-content').textContent,/Old result/);
  f.finish();checks++;
 }
 {
  const f=fixture();await f.browser.open();f.browser.openProduct(card);
  f.browser.toggleWatch(card,f.browser.sheet.querySelector('.dr-browse-watch-product'));
  assert.deepEqual(JSON.parse(f.w.localStorage.getItem('drop-rate-watchlist:account-a')),[card.key]);
  assert.equal(f.w.localStorage.getItem('drop-rate-watchlist:account-b'),null);
  f.browser.closeSheet();f.browser.filters.watch=true;await f.browser.load();assert.match(f.calls.at(-1).url,/keys=c%3A/);
  f.finish();checks++;
 }
 {
  const seen=new Map();let lose=true;
  const f=fixture(async(url,opts)=>{if(!url.endsWith('/intake'))return {items:[card]};
   const key=opts.headers['Idempotency-Key'];const previous=seen.get(key);
   if(previous)assert.equal(previous,opts.body);else seen.set(key,opts.body);
   if(seen.size===2&&lose){lose=false;throw Error('Lost response');}
   return {inventory:{inventory_code:'INV-'+key}};
  });
  await f.browser.open();f.browser.openProduct(card);assert.ok(f.browser.sheet.querySelector('[data-add]').disabled);
  Object.assign(f.browser.edit,{confirmed:true,condition:'Near Mint',quantity:2});f.browser.validateAdd();
  const first=f.browser.save();await f.browser.save();await first;
  assert.equal(seen.size,2);assert.equal(f.browser.edit.requests.filter(r=>r.result).length,1);
  assert.ok(f.browser.sheet.querySelector('select').disabled);
  await f.browser.save();assert.equal(seen.size,2);assert.ok(f.browser.edit.requests.every(r=>r.result));
  assert.equal(f.calls.filter(c=>c.url.endsWith('/intake')).length,3);
  const body=JSON.parse(f.calls.find(c=>c.url.endsWith('/intake')).body);assert.equal(body.owner_id,undefined);assert.equal(body.confirmed,true);
  await f.browser.save();assert.equal(f.browser.pending.has(card.key),false);
  f.browser.openProduct(card);assert.equal(f.browser.edit.requests,null);assert.equal(f.browser.edit.confirmed,false);
  f.finish();checks++;
 }
 {
  const pending=deferred();const f=fixture(()=>pending.promise);f.browser.games=games;f.browser.filters.q='card';const p=f.browser.load();
  f.logout();pending.resolve({items:[card]});await p;assert.equal(f.w.document.querySelector('.dr-browser'),null);f.finish();checks++;
 }
 {
  const f=fixture();await f.browser.open();f.browser.openFilters();
  const sealed=[...f.browser.sheet.querySelectorAll('input')].find(i=>i.getAttribute('aria-label')==='Sealed Only');sealed.click();await tick();
  const raw=[...f.browser.sheet.querySelectorAll('input')].find(i=>i.getAttribute('aria-label')==='Cards Only');raw.click();await tick();
  assert.equal(f.browser.filters.product_type,'CARD');
  assert.equal([...f.browser.sheet.querySelectorAll('input')].find(i=>i.getAttribute('aria-label')==='Sealed Only').checked,false);
  assert.match(f.calls.at(-1).url,/product_type=CARD/);f.finish();checks++;
 }
 console.log('Catalogue browser: '+checks+' search, navigation, filter, ownership, session and retry scenarios passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
