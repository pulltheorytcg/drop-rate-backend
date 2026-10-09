const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-browser.js'),'utf8');
const titleArt=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-title-art.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const card={key:'c:00000000-0000-0000-0000-000000000001',catalogue_id:'card-1',name:'Luffy',game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',set_name:'A Fist of Divine Speed',set_id:'OP11',language:'English',product_type:'CARD',variant:'Foil',card_number:'OP11-118',owned_quantity:0,market_value_minor:null,source_kind:'CATALOGUE'};
const games=[{game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',languages:['English','Japanese']}];
let checks=0;
function fixture(handler=async()=>({items:[card],has_more:false}),owner='account-a',embedded=false,gameHandler=async()=>({items:games})){
 const dom=new JSDOM('',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});const w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.eval(titleArt);w.eval(source);let alive=true;const calls=[];
 const client={owner,active:()=>alive,request:async(url,options)=>{calls.push({url,...options});return url.endsWith('/games')?gameHandler():handler(url,options);}};
 let host;
 if(embedded){w.document.body.innerHTML='<header class="topbar"></header><nav class="seller-nav"></nav><aside class="owner-sidebar"></aside><header class="owner-page-header"></header><main id="catalogue-host"></main>';host=w.document.getElementById('catalogue-host');}
 const browser=new w.DropRateCatalogue.Browser({host,client,navigate:()=>{},scan:()=>{},graded:()=>{},afterSave:async()=>{}});
 return {browser,w,calls,logout:()=>{alive=false;browser.destroy();},finish:()=>{browser.destroy();w.close();}};
}
(async()=>{
 {
  const waiting=deferred(),ref={...card,key:'r:'+'a'.repeat(32),provider:'TCGdex',source_kind:'REFERENCE',market_refresh_needed:true};
  const f=fixture(async(url,options)=>url.endsWith('/market-values')?waiting.promise:{items:[ref]});
  f.browser.filters.q='Seel';await f.browser.open();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value pending/);
  f.browser.openProduct(ref);const select=f.browser.sheet.querySelector('select');select.value='Near Mint';select.dispatchEvent(new f.w.Event('change'));
  waiting.resolve({items:[{key:ref.key,market_value_minor:7,market_value_high_minor:19,market_value_source:'TCGDEX_CARDMARKET',market_refresh_needed:false,
    basis_condition:'Raw · Cardmarket',pricing_updated_at:'2026-10-08T12:00:00Z',market_quotes:[{finish:'Normal',price_gbp_minor:7},{finish:'Reverse Holofoil',price_gbp_minor:19}]}]});
  await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/£0.07–£0.19/);
  assert.match(f.browser.sheet.textContent,/Reverse Holofoil: £0.19/);
  assert.match(f.browser.sheet.textContent,/converted from EUR/);
  assert.equal(f.browser.sheet.querySelector('select'),select);assert.equal(select.value,'Near Mint');
  const request=f.calls.find(call=>call.url.endsWith('/market-values'));
  assert.equal(request.method,'POST');assert.deepEqual(request.body.keys,[ref.key]);
  f.finish();checks++;
 }
 {
  const waiting=deferred(),ref={...card,key:'r:'+'b'.repeat(32),market_refresh_needed:true};
  const f=fixture(async(url)=>url.endsWith('/market-values')?waiting.promise:{items:[ref]});
  f.browser.filters.q='Old search';await f.browser.open();f.browser.reset();
  waiting.resolve({items:[{key:ref.key,market_value_minor:900,market_refresh_needed:false}]});await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Browse card games/);
  assert.equal(ref.market_value_minor,null);f.finish();checks++;
 }
 {
  const ref={...card,key:'r:'+'c'.repeat(32),market_refresh_needed:true};
  const f=fixture(async(url)=>{if(url.endsWith('/market-values'))throw new Error('Provider down');return {items:[ref]};});
  f.browser.filters.q='Card';await f.browser.open();await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value pending/);
  f.finish();checks++;
 }
 {
  const f=fixture();
  const picture=f.browser.productImage({...card,display_image_url:'https://www.dbs-cardgame.com/missing.webp',image_url:'https://www.dbs-cardgame.com/missing.webp',fallback_image_url:'https://cdn.shopify.com/approved.webp'});
  const img=picture.querySelector('img');
  assert.equal(img.referrerPolicy,'no-referrer');
  img.dispatchEvent(new f.w.Event('error'));assert.equal(img.src,'https://cdn.shopify.com/approved.webp');
  img.dispatchEvent(new f.w.Event('error'));assert.equal(picture.querySelector('img'),null);
  assert.match(picture.textContent,/Image unavailable/);
  assert.equal(f.browser.productImage({...card,image_url:'//untrusted.example/card.png'}).querySelector('img'),null);
  f.browser.openProduct(card);assert.match(f.browser.sheet.textContent,/No verified market value/);
  f.browser.openProduct({...card,key:'c:priced',market_value_minor:1250});assert.match(f.browser.sheet.textContent,/£12.50/);assert.doesNotMatch(f.browser.sheet.textContent,/No verified market value/);
  f.finish();checks++;
 }

 {
  const f=fixture();
  const picture=f.browser.productImage({...card,image_url:'https://www.onepiece-cardgame.com/images/cardlist/card/OP12-058.png'});
  const placeholder=picture.querySelector('.dr-browse-image-placeholder'),img=picture.querySelector('img');
  assert.equal(placeholder.textContent,'Loading image…');assert.equal(placeholder.hidden,false);
  img.dispatchEvent(new f.w.Event('load'));assert.equal(placeholder.hidden,true);
  assert.equal(f.browser.productImage(card).textContent,'Artwork unavailable');
  assert.equal(f.browser.productImage({...card,image_url:img.src},'dr-browse-detail-image').querySelector('img').loading,'eager');
  f.finish();checks++;
 }

 {
  const f=fixture();await f.browser.open();assert.match(f.browser.find('.dr-browse-content').textContent,/Browse card games/);
  assert.equal(f.calls.length,1);f.browser.filters.product_type='SEALED';await f.browser.load();
  assert.match(f.calls.at(-1).url,/product_type=SEALED/);assert.match(f.browser.find('.dr-browse-chips').textContent,/Sealed Only/);
  f.browser.reset();assert.equal(f.browser.filters.product_type,'');assert.match(f.browser.find('.dr-browse-content').textContent,/Browse card games/);
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
  const unownedSet={system_code:'ONE_PIECE_CARD_GAME',set_id:'empty',set_name:'Unowned set',language:'English',provider:'Checklist',indexed_count:0,card_count:160,owned_count:0,owned_value_minor:null,unknown_values:0,checklist_status:'UNAVAILABLE'};
  const availableSet={...unownedSet,set_id:'available',set_name:'Available set',indexed_count:102,card_count:102,checklist_status:'AVAILABLE'};
  const f=fixture(async url=>{
   const query=new URL(url,'https://example.test').searchParams;
   if(url.includes('/sets'))return {items:[query.get('offset')==='0'?unownedSet:availableSet],has_more:query.get('offset')==='0',total_count:2};
   return {items:query.get('set_id')==='empty'||query.get('owned')==='owned'?[]:[card],has_more:false};
  });
  await f.browser.open();f.browser.pickGame(games[0]);await tick();
  assert.equal(new URL(f.calls.at(-1).url,'https://example.test').searchParams.get('owned'),'all');
  assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Qty: 0/);
  Object.assign(f.browser.filters,{owned:'owned',watch:true,product_type:'SEALED'});
  f.browser.showSets();await tick();
  assert.equal(f.browser.filters.owned,'all');assert.equal(f.browser.filters.watch,false);assert.equal(f.browser.filters.product_type,'');
  assert.match(f.browser.find('.dr-browse-set').textContent,/Progress: 0\/160/);
  assert.match(f.browser.find('.dr-browse-status').textContent,/2 sets/);
  assert.equal(f.browser.find('[data-action="more"]').hidden,false);
  await f.browser.load(true);assert.equal(f.browser.dialog.querySelectorAll('.dr-browse-set').length,2);
  f.browser.find('.dr-browse-set').click();await tick();
  assert.match(f.browser.find('.dr-browse-status').textContent,/checklist is currently unavailable/);
  assert.equal(new URL(f.calls.at(-1).url,'https://example.test').searchParams.get('owned'),'all');
  f.browser.showSets();await tick();await f.browser.load(true);
  f.browser.dialog.querySelectorAll('.dr-browse-set')[1].click();await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  f.browser.filters.owned='owned';await f.browser.load();assert.doesNotMatch(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  f.browser.filters.owned='all';await f.browser.load();assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  f.finish();checks++;
 }
 // Leaving Search with a sheet open dismisses it without stealing destination focus.
 {
  const f=fixture(undefined,undefined,true);await f.browser.open();f.browser.filters.q='Luffy';
  const outside=f.w.document.querySelector('.topbar');outside.inert=false;
  f.browser.openProduct(card);const pending=f.browser.edit;pending.condition='Near Mint';
  const destination=f.w.document.createElement('button');f.w.document.body.append(destination);destination.focus();
  f.browser.close();assert.equal(f.browser.dialog.hidden,true);assert.equal(f.browser.find('.dr-browse-backdrop').hidden,true);
  assert.equal(outside.inert,false);assert.equal(f.w.document.activeElement,destination);
  await f.browser.open();assert.equal(f.browser.dialog.hidden,false);assert.equal(f.browser.find('.dr-browse-backdrop').hidden,true);
  for(const selector of ['.dr-browse-header','.dr-browse-scroll','.dr-browse-nav'])assert.equal(f.browser.find(selector).inert,false);
  assert.equal(f.browser.filters.q,'Luffy');f.browser.openProduct(card);assert.equal(f.browser.edit,pending);assert.equal(f.browser.edit.condition,'Near Mint');
  assert.equal(outside.inert,true);f.browser.closeSheet();assert.equal(outside.inert,false);
  f.finish();checks++;
 }
 {
  const f=fixture(),row={system_code:'POKEMON_TCG',provider:'TCGdex',language:'English',set_id:'base1',set_name:'Base Set'};
  assert.match(f.w.DropRateTitleArt.set(row).url,/^https:\/\/assets\.tcgdex\.net\/en\/base\/base1\/logo\.webp$/);
  assert.equal(f.w.DropRateTitleArt.set({...row,language:'Japanese'}),null);
  assert.equal(f.w.DropRateTitleArt.set({...row,provider:'Another provider'}),null);
  assert.equal(f.w.DropRateTitleArt.set({...row,set_id:'__proto__'}),null);
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
 // Updating an embedded sheet must not leave the surrounding workspace disabled.
 for(const exit of ['Show results','Close Filters','Escape']){
  const f=fixture(undefined,undefined,true);await f.browser.open();
  const outside=[...f.w.document.querySelectorAll('.topbar,.seller-nav,.owner-sidebar,.owner-page-header')];
  outside.forEach((el,index)=>{el.inert=index===2;});
  f.browser.openFilters();
  for(const label of ['Cards Only','Products Owned','Watchlist']){
   [...f.browser.sheet.querySelectorAll('input')].find(input=>input.getAttribute('aria-label')===label).click();await tick();
   assert.ok(outside.every(el=>el.inert===true));
  }
  if(exit==='Escape')f.browser.sheet.dispatchEvent(new f.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  else [...f.browser.sheet.querySelectorAll('button')].find(control=>control.textContent===exit||control.getAttribute('aria-label')===exit).click();
  assert.equal(f.browser.find('.dr-browse-backdrop').hidden,true);
  outside.forEach((el,index)=>assert.equal(el.inert,index===2));
  // A later sheet takes a fresh snapshot and still preserves pre-existing inert state.
  f.browser.openFilters();f.browser.closeSheet();outside.forEach((el,index)=>assert.equal(el.inert,index===2));
  f.finish();checks++;
 }
 {
  const f=fixture(async url=>url.includes('/sets')?{items:[{system_code:'NARUTO_BANDAI_LEGACY',set_id:'same-id',set_name:'Legacy set',provider:'Bandai',language:'English',indexed_count:1,owned_count:0}]}:{items:[]});
  assert.equal(f.browser.games.filter(g=>g.system_code.startsWith('NARUTO')).length,1);
  f.browser.games=[{system_code:'NARUTO',game:'Naruto',languages:['Chinese','English']}];f.browser.gamesLoaded=true;
  await f.browser.open();assert.equal(f.browser.dialog.querySelectorAll('[data-system="NARUTO"]').length,1);
  f.browser.pickGame(f.browser.games[0]);await tick();assert.match(f.calls.at(-1).url,/system_code=NARUTO&/);
  f.browser.showSets();await tick();assert.match(f.calls.at(-1).url,/system_code=NARUTO&/);
  f.browser.find('.dr-browse-set').click();await tick();
  const params=new URL(f.calls.at(-1).url,'https://example.test').searchParams;
  assert.equal(params.get('system_code'),'NARUTO_BANDAI_LEGACY');assert.equal(params.get('provider'),'Bandai');assert.equal(params.get('set_id'),'same-id');
  assert.equal(f.browser.filters.system_code,'NARUTO');
  f.finish();checks++;
 }
 // Spotlight resolves only the requested server identity; it never opens a similar variant.
 for(const outcome of ['exact','missing','navigate']){
  const pending=deferred(),f=fixture(()=>pending.promise);
  f.browser.hasMore=true;f.browser.loading=false;f.browser.find('[data-action="more"]').hidden=false;
  const opened=f.browser.open(card.key);assert.match(f.calls[0].url,/keys=c%3A/);assert.equal(f.calls.length,1);
  assert.equal(f.browser.hasMore,false);assert.equal(f.browser.loading,true);assert.equal(f.browser.find('[data-action="more"]').hidden,true);
  if(outcome==='navigate')f.browser.close();
  pending.resolve({items:outcome==='missing'?[{...card,key:'r:different-printing'}]:[card]});await opened;
  assert.equal(f.browser.loading,false);
  assert.equal(f.browser.find('.dr-browse-backdrop').hidden,outcome!=='exact');
  if(outcome==='exact')assert.equal(f.browser.edit.row.key,card.key);
  if(outcome==='missing')assert.match(f.browser.find('.dr-browse-status').textContent,/currently unavailable/);
  f.finish();checks++;
 }
 // Direct game entry must show products without waiting for slow/failed game metadata.
 for(const failure of [false,true]){
  const metadata=deferred(),f=fixture(async()=>({items:[card]}),'account-a',true,()=>metadata.promise);
  f.browser.filters.system_code=card.system_code;
  await f.browser.open();
  assert.equal(f.browser.gamesLoaded,false);assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  assert.equal(f.calls.filter(c=>c.url.includes('/products?')).length,1);
  if(failure)metadata.resolve(Promise.reject(Error('Directory unavailable')));else metadata.resolve({items:games});
  await tick();await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  assert.equal(f.calls.filter(c=>c.url.includes('/products?')).length,1);
  f.finish();checks++;
 }
 // Late metadata must not repeat a search or revive an older result.
 {
  const metadata=deferred(),old=deferred();
  const f=fixture(url=>url.includes('q=old')?old.promise:Promise.resolve({items:[{...card,name:'New result'}]}),'account-a',true,()=>metadata.promise);
  f.browser.filters.q='old';const opening=f.browser.open();
  f.browser.filters.q='new';await f.browser.load();
  metadata.resolve({items:games});old.resolve({items:[{...card,name:'Old result'}]});await opening;await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/New result/);
  assert.doesNotMatch(f.browser.find('.dr-browse-content').textContent,/Old result/);
  assert.equal(f.calls.filter(c=>c.url.includes('/products?')).length,2);
  f.finish();checks++;
 }
 console.log('Catalogue browser: '+checks+' search, navigation, filter, ownership, session and retry scenarios passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
