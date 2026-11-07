"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-browser.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const card={key:'c:00000000-0000-4000-8000-000000000001',catalogue_id:'00000000-0000-4000-8000-000000000001',name:'Pikachu',system_code:'POKEMON_TCG',game:'Pokémon',set_id:'base1',set_name:'Base Set',card_number:'58/102',language:'English',product_type:'CARD',owned_quantity:0,source_kind:'CATALOGUE'};
const other='r:'+'a'.repeat(32);
const games=[{system_code:'POKEMON_TCG',game:'Pokémon',languages:['English','Japanese']},{system_code:'YUGIOH',game:'Yu-Gi-Oh!',languages:['English']},{system_code:'COMICS',game:'Comics',languages:['English']},{system_code:'MANGA',game:'Manga',languages:['English','Japanese']}];
function fixture({account='a',server=new Map(),device=[],products,saveOverride}={}){
 const dom=new JSDOM('',{runScripts:'outside-only',url:'https://discovery.example.test',pretendToBeVisual:true}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 if(device.length)w.localStorage.setItem('drop-rate-watchlist:'+account,JSON.stringify(device));
 w.eval(source);let alive=true,currentAccount=account;const calls=[],books=[],views=[],scans=[];
 const client={owner:account,active:()=>alive&&currentAccount===account,request:async(url,opts={})=>{
  calls.push({url,...opts});const params=new URL(url,'https://discovery.example.test').searchParams;
  if(url.includes('/catalogue-browser/saved')){
   if(saveOverride)return saveOverride(url,opts);
   const keys=server.get(account)||new Set();server.set(account,keys);
   if(opts.method==='PUT')keys.add(JSON.parse(opts.body).key);
   if(opts.method==='DELETE')keys.delete(decodeURIComponent(url.split('/').at(-1)));
   if(url.endsWith('/import'))for(const key of JSON.parse(opts.body).keys)keys.add(key);
   return {keys:[...keys],imported_count:opts.method==='POST'?JSON.parse(opts.body).keys.length:0};
  }
  if(url.endsWith('/games'))return {items:games};
  if(url.endsWith('/intake'))return {inventory:{id:'copy-1',inventory_code:'INV-1'}};
  if(url.includes('/sets?'))return {items:[],has_more:false};
  return products?products(params):{items:[{...card}],has_more:false};
 }};
 const browser=new w.DropRateCatalogue.Browser({client,navigate:view=>views.push(view),scan:mode=>scans.push(mode),graded:()=>{},books:value=>books.push(value),afterSave:async()=>{},viewItem:receipt=>views.push(receipt.inventory),viewCollection:()=>views.push('inventory')});
 const submit=async query=>{browser.input.value=query;browser.input.dispatchEvent(new w.Event('input'));browser.input.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',cancelable:true}));await tick();};
 const choose=async category=>{browser.find(`[data-category="${category}"]`).click();await tick();};
 const setFilter=(name,value)=>{const select=browser.sheet.querySelector(`[data-filter="${name}"]`);assert.ok(select);select.value=value;select.dispatchEvent(new w.Event('change'));};
 const apply=async()=>{[...browser.sheet.querySelectorAll('button')].find(button=>button.textContent==='Show results').click();await tick();};
 const lastProduct=()=>calls.filter(call=>call.url.includes('/products?')).at(-1);
 return {w,browser,calls,server,books,views,scans,submit,choose,setFilter,apply,lastProduct,switchAccount:next=>{currentAccount=next;},stop:()=>{alive=false;browser.destroy();},finish:()=>{alive=false;browser.destroy();w.close();}};
}
(async()=>{
 let groups=0;
 {
  const expansionKey='x:'+'b'.repeat(64),server=new Map([['a',new Set([expansionKey])]]);
  const f=fixture({server,device:[expansionKey,'x:invalid']});await f.browser.open();await tick();
  assert.deepEqual([...f.browser.watchlist],[expansionKey]);
  assert.deepEqual([...f.browser.deviceSaved],[expansionKey]);
  f.browser.find('[data-action="watch"]').click();await tick();
  assert.equal(new URL(f.lastProduct().url,'https://test').searchParams.get('keys'),expansionKey);
  const row={...card,key:expansionKey,catalogue_id:null,source_kind:'REFERENCE',system_code:'YUGIOH',game:'Yu-Gi-Oh!',metadata_only:true,identity_review_required:true};
  f.browser.openProduct(row);await f.browser.toggleWatch(row,f.browser.sheet.querySelector('[data-saved-key]'));
  assert.match(f.browser.sheet.textContent,/Printing details need review/);
  assert.match(f.browser.sheet.textContent,/Artwork and market value are not verified/);
  assert.equal(f.browser.watchlist.size,0);assert.equal(server.get('a').size,0);f.finish();groups++;
 }
 {
  const f=fixture({products:params=>({items:[{...card}],has_more:false,...(!params.get('system_code')?{catalogue_scope:'LEGACY_WITH_SEPARATE_R2_SYSTEMS',additional_catalogue_systems:['YUGIOH']}:{catalogue_scope:'R2_FIRST_SYSTEM'})})});
  await f.browser.open();await f.submit('Blue-Eyes');
  const scope=f.browser.find('.dr-browse-r2-scope');assert.ok(scope);assert.match(scope.textContent,/separate game search/);
  scope.querySelector('button').click();await tick();
  const request=new URL(f.lastProduct().url,'https://test').searchParams;
  assert.equal(request.get('system_code'),'YUGIOH');assert.equal(request.get('q'),'Blue-Eyes');
  assert.equal(f.browser.find('.dr-browse-r2-scope'),null);f.finish();groups++;
 }
 {
  const f=fixture();await f.browser.open();await f.submit('Pikachu');
  assert.doesNotMatch(f.browser.find('.dr-browse-chips').textContent,/Cards Only/);
  assert.equal(f.browser.find('[data-action="menu"]'),null);assert.equal(f.browser.find('[data-action="sort-visible"]'),null);
  f.browser.openFilters();const count=f.calls.length;f.setFilter('language','Japanese');f.setFilter('owned','owned');
  assert.equal(f.calls.length,count,'Draft filters must not reset or reload results');f.browser.closeSheet();assert.equal(f.browser.filters.language,'');
  f.browser.openFilters();f.setFilter('system_code','POKEMON_TCG');f.setFilter('language','Japanese');f.setFilter('sort','value_desc');await f.apply();
  const scoped=new URL(f.lastProduct().url,'https://test').searchParams;assert.equal(scoped.get('q'),'Pikachu');assert.equal(scoped.get('language'),'Japanese');assert.equal(scoped.get('sort'),'value_desc');
  f.browser.clearCategoryFilters();await f.browser.load();const cleared=new URL(f.lastProduct().url,'https://test').searchParams;
  assert.equal(cleared.get('q'),'Pikachu');assert.equal(cleared.get('product_type'),'CARD');assert.equal(cleared.get('language'),null);assert.equal(cleared.get('system_code'),null);
  f.finish();groups++;
 }
 {
  const f=fixture();await f.browser.open();await f.submit('Batman');await f.choose('COMICS');f.browser.openFilters();
  assert.match(f.browser.sheet.textContent,/Publisher/);assert.doesNotMatch(f.browser.sheet.textContent,/All trading card games|Cards Only/);
  f.setFilter('browse_group','DC');await f.apply();
  const params=new URL(f.lastProduct().url,'https://test').searchParams;assert.equal(params.get('system_code'),'COMICS');assert.equal(params.get('browse_group'),'DC');assert.equal(params.get('product_type'),'COMIC');assert.equal(params.get('q'),'Batman');assert.equal(f.browser.categoryId,'COMICS');
  await f.choose('MANGA');f.browser.openFilters();assert.equal(f.browser.sheet.querySelector('[data-filter="system_code"]'),null);assert.ok(f.browser.sheet.querySelector('[data-filter="language"]'));
  f.finish();groups++;
 }
 {
  const f=fixture({products:()=>({items:[],has_more:false})});await f.browser.open();await f.submit('One Piece');await f.choose('MANGA');
  [...f.browser.find('.dr-browse-content').querySelectorAll('button')].find(button=>button.textContent==='Add manga').click();
  assert.equal(f.books[0].query,'One Piece');assert.equal(f.books[0].category,'MANGA');assert.equal(f.books[0].book,undefined);assert.equal(typeof f.books[0].onAddAnother,'function');
  await f.browser.open();await f.choose('TCG');f.browser.pickGame(games[0]);await tick();
  [...f.browser.find('.dr-browse-content').querySelectorAll('button')].find(button=>button.textContent==='Search all games').click();await tick();
  assert.equal(new URL(f.lastProduct().url,'https://test').searchParams.get('q'),'One Piece');
  [...f.browser.find('.dr-browse-content').querySelectorAll('button')].find(button=>button.textContent==='Scan this item').click();assert.equal(f.scans[0],'RAW');f.finish();groups++;
 }
 {
  const f=fixture();await f.browser.open();await f.submit('Pikachu');f.browser.scroll.scrollTop=270;
  const tile=f.browser.find('[data-product-key]');tile.focus();tile.click();await f.browser.save();
  assert.match(f.browser.sheet.textContent,/Added to your collection/);assert.equal(f.browser.sheet.querySelector('[data-add]'),null);
  assert.equal(f.calls.filter(call=>call.url.endsWith('/intake')).length,1);
  f.browser.sheet.querySelector('[data-added-action="another"]').click();assert.equal(f.browser.filters.q,'Pikachu');assert.equal(f.browser.scroll.scrollTop,270);assert.equal(f.browser.rows[0].owned_quantity,1);
  f.browser.openProduct(card);await f.browser.save();f.browser.sheet.querySelector('[data-added-action="view"]').click();await tick();
  assert.deepEqual(f.views.at(-1),{id:'copy-1',inventory_code:'INV-1'});
  const calls=f.calls.length;await f.browser.open();assert.equal(f.browser.filters.q,'Pikachu');assert.equal(f.browser.scroll.scrollTop,270);assert.equal(f.calls.length,calls);f.finish();groups++;
 }
 {
  const server=new Map(),f=fixture({server,device:[card.key]});await f.browser.open();await tick();
  assert.equal(f.browser.watchlist.size,0);assert.equal(server.get('a').size,0);assert.equal(f.calls.filter(call=>call.method).length,0,'Never silently migrate device saves');
  f.browser.find('[data-action="watch"]').click();await tick();assert.match(f.browser.find('.dr-browse-saved-note').textContent,/device only/);
  f.browser.find('.dr-browse-device-import').click();await tick();
  const request=f.calls.find(call=>call.url.endsWith('/import'));assert.equal(JSON.parse(request.body).confirmed,true);assert.deepEqual([...server.get('a')],[card.key]);
  assert.equal(f.w.localStorage.getItem('drop-rate-watchlist:a'),'[]');assert.equal(f.browser.deviceSaved.size,0);
  const next=fixture({server});await next.browser.open();await tick();assert.deepEqual([...next.browser.watchlist],[card.key]);
  const another=fixture({server,account:'b'});await another.browser.open();await tick();assert.equal(another.browser.watchlist.size,0);assert.equal(another.browser.deviceSaved.size,0);
  f.finish();next.finish();another.finish();groups++;
 }
 {
  const f=fixture({saveOverride:async()=>{throw Error('Offline');}});await f.browser.open();f.browser.openProduct(card);await f.browser.toggleWatch(card,f.browser.sheet.querySelector('[data-saved-key]'));
  assert.equal(f.browser.watchlist.size,0);assert.match(f.browser.sheet.textContent,/Not saved/);assert.equal(f.w.localStorage.getItem('drop-rate-watchlist:a'),null);
  f.browser.closeSheet();f.browser.find('[data-action="watch"]').click();await tick();assert.match(f.browser.find('.dr-browse-status').textContent,/could not sync/);assert.ok([...f.browser.find('.dr-browse-content').querySelectorAll('button')].find(button=>button.textContent==='Try again'));f.finish();groups++;
 }
 {
  let release;const waiting=new Promise(resolve=>{release=resolve;});const f=fixture({saveOverride:()=>waiting});const opening=f.browser.open();await tick();f.stop();release({keys:[other]});await opening;await tick();assert.equal(f.browser.watchlist.size,0);f.finish();groups++;
 }
 {
  let release;const waiting=new Promise(resolve=>{release=resolve;});
  const f=fixture({device:[other],saveOverride:(_url,options)=>options.method==='PUT'?waiting:{keys:[]}});await f.browser.open();f.browser.openProduct(card);
  const mutation=f.browser.toggleWatch(card,f.browser.sheet.querySelector('[data-saved-key]'));await tick();f.switchAccount('b');release({keys:[card.key]});await mutation;
  assert.equal(f.browser.watchlist.size,0);assert.deepEqual(JSON.parse(f.w.localStorage.getItem('drop-rate-watchlist:a')),[other]);
  // A different account in the same browser must not even offer the previous
  // account's device list as an import candidate.
  const next=new f.w.DropRateCatalogue.Browser({client:{owner:'b',active:()=>true,request:async url=>url.endsWith('/saved')?{keys:[]}:{items:games}},navigate:()=>{},scan:()=>{},graded:()=>{},afterSave:async()=>{}});
  await next.open();assert.equal(next.deviceSaved.size,0);assert.equal(next.watchlist.size,0);assert.equal(next.storageKey,'drop-rate-watchlist:b');next.destroy();f.finish();groups++;
 }
 {
  const dom=new JSDOM('',{runScripts:'outside-only',url:'https://books.example.test'}),w=dom.window;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.eval('window.state={session:{user:{id:"owner-a"}}};window.intakes=[];async function apiRequest(url,options){intakes.push({url,options});return {inventory:{id:"book-copy",inventory_code:"INV-BOOK"},catalogue:{name:"One Piece Volume 1"}};}async function loadOwnerInventory(){}async function loadOwnerOverview(){}function activateOwnerView(view){window.destination=view;}');
  w.eval(fs.readFileSync(path.join(__dirname,'../../backend/app/static/owner-books.js'),'utf8'));
  let opened;w.document.addEventListener('hub:inventory-open',event=>{opened=event.detail;});
  w.DropRateBooks.open({category:'MANGA',query:'One Piece'});
  const field=id=>w.document.getElementById('owner-book-'+id);
  assert.equal(field('series').value,'One Piece');field('number').value='1';field('publisher').value='VIZ Media';
  field('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();
  assert.equal(field('success').hidden,false);assert.equal(field('actions').hidden,true);assert.equal(field('title').textContent,'Added to your collection');
  field('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();assert.equal(w.intakes.length,1);
  field('view-item').click();assert.equal(w.destination,'inventory');assert.equal(opened.inventoryId,'book-copy');assert.equal(opened.inventoryCode,'INV-BOOK');
  let returned=0;w.DropRateBooks.open({category:'MANGA',query:'One Piece',onAddAnother:()=>{returned++;}});
  assert.equal(field('success').hidden,true);assert.equal(field('actions').hidden,false);field('number').value='2';field('publisher').value='VIZ Media';
  field('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();field('add-another').click();assert.equal(returned,1);assert.equal(w.intakes.length,2);
  w.DropRateBooks.reset();w.close();groups++;
 }
 console.log(`Discovery UX: ${groups} groups passed (query-preserving refinements, category filters, recovery, card/book receipts, return state, explicit account migration, offline and stale-session safety).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
