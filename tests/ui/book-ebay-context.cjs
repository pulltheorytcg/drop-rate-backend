const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const source=name=>fs.readFileSync(path.join(base,name),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const id='00000000-0000-4000-8000-000000000001';
const cover={kind:'OPEN_LIBRARY_EDITION_REFERENCE',provider:'OPEN_LIBRARY',edition_id:'OL8537239M',language:'English',
 image_url:'https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false',detail_image_url:'https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false',
 source_url:'https://openlibrary.org/books/OL8537239M',scope:'COMMUNITY_EDITION',status:'REFERENCE_ONLY'};
const book={catalogue_id:id,key:'c:'+id,product_type:'COMIC',system_code:'MANGA',name:'+Anima Volume 1',language:'English',owned_quantity:0,
 market_value_minor:null,book_market_status:'PRINTING_REVIEW_REQUIRED',community_cover:cover,artwork_kind:cover.kind,
 book_details:{system_code:'MANGA',series_title:'+Anima',issue_number:'1',publisher:'Tokyopop',book_format:'MANGA',volume_identifier:'Paperback',language:'English',release_year:2006,barcode_gtin:'9781598163476'}};
function response(row=book,changes={}) {
 const now=new Date().toISOString();
 return {status:'AVAILABLE',scope:'EDITION_ACTIVE_LISTINGS',source:'EBAY_BROWSE',observation_type:'ACTIVE',currency:'GBP',physical_valuation_eligible:false,
  catalogue_id:row.catalogue_id,isbn:'9781598163476',edition_digest:'a'.repeat(64),edition:{title:'+Anima',volume:'1',language:'English',binding:'Paperback'},checked_at:now,
  expires_at:new Date(Date.now()+3600000).toISOString(),item_count:2,asking_low_minor:650,asking_high_minor:1099,
  items:[{item_id:'v1|123456789012|0',title:'+Anima Vol. 1 English Paperback',condition:'Very Good',binding:'Paperback',price_minor:650,shipping_minor:250,
   url:'https://www.ebay.co.uk/itm/123456789012',image_url:'https://i.ebayimg.com/images/g/abc/s-l500.jpg',listed_at:now,checked_at:now},
   {item_id:'v1|123456789013|0',title:'+Anima Volume 1 Tokyopop 9781598163476',condition:'Brand new',binding:'Paperback',price_minor:1099,shipping_minor:null,
   url:'https://www.ebay.co.uk/itm/123456789013',image_url:null,listed_at:now,checked_at:now}],...changes};
}
function empty(row=book,status='UNAVAILABLE') {return response(row,{status,item_count:0,asking_low_minor:null,asking_high_minor:null,items:[]});}
function fixture(handler=async row=>response(row),rows=[structuredClone(book)]) {
 const dom=new JSDOM('',{url:'https://example.test/owner',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 const observers=[];
 w.IntersectionObserver=class {constructor(callback,options){this.callback=callback;this.options=options;this.elements=new Set();observers.push(this);}observe(target){this.elements.add(target);}unobserve(target){this.elements.delete(target);}disconnect(){this.elements.clear();}show(target){this.callback([{target,isIntersecting:true}]);}};
 w.fetch=async()=>{throw new Error('Listing photos must not use fetch or application credentials');};
 for(const name of ['book-community-artwork.js','book-ebay-context.js','catalogue-browser.js'])w.eval(source(name));
 let alive=true;const calls=[];
 const client={owner:'owner-a',active:()=>alive,request:async(url,options={})=>{
  calls.push({url,...options});
  if(url.includes('/listing-context'))return handler(rows.find(row=>url.includes(row.catalogue_id)),options);
  return {items:rows,has_more:false};
 }};
 const browser=new w.DropRateCatalogue.Browser({client,books:()=>{},navigate:()=>{},scan:()=>{}});
 browser.gamesLoaded=true;browser.filters.product_type='COMIC';
 const visible=()=>{const observer=observers.find(item=>item.options.rootMargin==='80px 0px');return {observer,cards:[...browser.dialog.querySelectorAll('.dr-browse-product')]};};
 return {w,browser,rows,calls,client,visible,logout:()=>{alive=false;},finish:()=>{browser.destroy();w.close();}};
}
(async()=>{
 let checks=0;
 // Actual edition, active evidence and source boundaries are all required.
 {
  const f=fixture(),helper=f.w.DropRateBookEbay;
  assert.equal(helper.validate(book,response()).asking_low_minor,650);
  for(const change of [
   {source:'EBAY_SOLD'}, {observation_type:'SOLD'}, {scope:'PHYSICAL_COPY'}, {physical_valuation_eligible:true}, {currency:'USD'},
   {catalogue_id:'00000000-0000-4000-8000-000000000002'}, {isbn:'9781598163483'}, {edition_digest:'bad'},
   {edition:{title:'+Anima',volume:'2',language:'English',binding:'Paperback'}},
   {edition:{title:'+Anima',volume:'1',language:'Japanese',binding:'Paperback'}},
   {expires_at:new Date(Date.now()-1).toISOString()}, {asking_low_minor:100}, {item_count:3}
  ])assert.equal(helper.validate(book,response(book,change)),null,JSON.stringify(change));
  for(const url of ['https://www.ebay.co.uk.evil.test/itm/123456789012','http://www.ebay.co.uk/itm/123456789012','https://user:pass@www.ebay.co.uk/itm/123456789012','https://www.ebay.co.uk/sch/i.html','javascript:alert(1)']){
   const data=response();data.items[0].url=url;assert.equal(helper.validate(book,data),null,url);
  }
  for(const url of ['https://i.ebayimg.com.evil.test/images/g/a/s-l500.jpg','https://user:pass@i.ebayimg.com/images/g/a/s-l500.jpg','http://i.ebayimg.com/images/g/a/s-l500.jpg','https://i.ebayimg.com/images/g/a/s-l500.jpg?redirect=bad','https://example.test/photo.jpg']){
   const data=response();data.items[0].image_url=url;assert.equal(helper.validate(book,data).items[0].image_url,null,url);
  }
  const unknown={...book,book_details:{...book.book_details,volume_identifier:null}};
  assert.equal(helper.validate(unknown,response(unknown,{edition:{title:'+Anima',volume:'1',language:'English',binding:null}})).edition.binding,null);
  assert.equal(unknown.book_details.volume_identifier,null);
  assert.equal(helper.identity({...book,catalogue_id:'../../other-owner'}),null);
  f.finish();checks++;
 }
 // Listing context cannot create anonymous requests, even if an embedding
 // mistakenly reports its page as active without an authenticated actor.
 {
  const f=fixture(),root=f.w.document.body,target=f.w.document.createElement('article');root.append(target);let calls=0;
  const session=new f.w.DropRateBookEbay.Session({client:{owner:'',active:()=>true,request:async()=>{calls++;}},active:()=>true,root});
  session.watch(book,target,()=>{throw new Error('Anonymous context must not render');},{immediate:true});await tick();
  assert.equal(calls,0);session.destroy();f.finish();checks++;
 }
 // Visible rows fetch through the authenticated app client. Successful source
 // covers stay first; asks never overwrite the book's independent market value.
 {
  const f=fixture();await f.browser.open();await tick();
  assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,0);
  const {observer,cards}=f.visible();observer.show(cards[0]);await tick();
  const card=cards[0],img=card.querySelector('.dr-browse-product-image img');
  assert.equal(img.src,cover.image_url);img.dispatchEvent(new f.w.Event('load'));
  assert.match(card.textContent,/eBay asking prices.*£6\.50–£10\.99/s);
  assert.match(card.textContent,/Very Good \/ Brand new.*postage/s);
  assert.match(card.querySelector('[data-price-key]').textContent,/Value pending/);
  assert.equal(f.rows[0].market_value_minor,null);
  for(const link of card.querySelectorAll('.book-ebay-sources a')){
   assert.equal(link.closest('button'),null);assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
   let bubbled=0;card.addEventListener('click',()=>bubbled++);link.addEventListener('click',event=>event.preventDefault());link.click();assert.equal(bubbled,0);
  }
  assert.equal(card.querySelector('.book-ebay-photo-credit'),null,'A loaded source image is not relabelled as a listing photo');
  f.browser.openProduct(f.rows[0]);await tick();
  assert.match(f.browser.sheet.textContent,/Active listings for this ISBN edition/);
  assert.match(f.browser.sheet.textContent,/£6\.50 · £2\.50 postage/);assert.match(f.browser.sheet.textContent,/Postage not stated/);
  assert.match(f.browser.sheet.textContent,/Very Good · Paperback/);
  assert.equal(f.browser.sheet.querySelector('input'),null,'Asks do not prefill a physical-copy review form');
  assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,1,'Detail reuses a fresh exact-edition context');
  f.finish();checks++;
 }
 // OL failure before or after context arrives can show a bounded listing photo,
 // with explicit external provenance outside the product-selection button.
 for(const late of [false,true]) {
  const pending=deferred(),f=fixture(late?()=>pending.promise:async()=>response());await f.browser.open();await tick();
  const {observer,cards}=f.visible(),card=cards[0];observer.show(card);await tick();
  card.querySelector('.dr-browse-product-image img').dispatchEvent(new f.w.Event('error'));
  if(late){assert.equal(card.querySelector('.dr-browse-product-image img'),null);pending.resolve(response());await tick();}
  const img=card.querySelector('.dr-browse-product-image img');assert.equal(img.src,response().items[0].image_url);
  assert.equal(img.crossOrigin,'anonymous');assert.equal(img.referrerPolicy,'no-referrer');assert.equal(img.loading,'lazy');
  assert.match(img.alt,/eBay listing photo; copy may vary/);img.dispatchEvent(new f.w.Event('load'));
  const credit=card.querySelector('.book-ebay-photo-credit');assert.match(credit.textContent,/eBay listing photo · Copy may vary/);
  assert.equal(card.querySelector('.book-cover-reference').hidden,true,'A listing photo cannot retain the previous cover-source caption');
  assert.equal(credit.querySelector('a').href,response().items[0].url);assert.equal(credit.closest('button'),null);
  img.dispatchEvent(new f.w.Event('error'));assert.equal(card.querySelector('.dr-browse-product-image img'),null);
  assert.equal(card.querySelector('.book-ebay-photo-credit'),null);f.finish();checks++;
 }
 // Missing context is explicit; the disabled optional feature stays hidden.
 // Neither case invents a price/photo or changes existing sold values.
 for(const status of ['UNAVAILABLE','DISABLED']) {
  const row={...structuredClone(book),market_value_minor:2300,basis_condition:'Near Mint'},f=fixture(async()=>empty(row,status),[row]);
  await f.browser.open();await tick();const {observer,cards}=f.visible();observer.show(cards[0]);await tick();
  assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,0,'A priced grid row does not spend a provider request');
  f.browser.openProduct(row);await tick();assert.match(f.browser.sheet.textContent,/£23\.00.*UK sold reference/);
  if(status==='DISABLED')assert.equal(f.browser.sheet.querySelector('.book-ebay-context').hidden,true);
  else assert.match(f.browser.sheet.textContent,/No matching eBay asking prices available/);
  assert.equal(row.market_value_minor,2300);
  assert.equal(f.browser.sheet.querySelector('.book-ebay-range'),null);f.finish();checks++;
 }
 // Only intersecting visible cards enter the queue, at most two concurrent
 // requests. Closing aborts active work and never starts the queued third job.
 {
  const rows=[1,2,3,4].map(n=>({...structuredClone(book),catalogue_id:id.slice(0,-1)+n,key:'c:'+id.slice(0,-1)+n}));
  const pending=[],f=fixture(row=>{const d=deferred();pending.push({d,row});return d.promise;},rows);
  await f.browser.open();await tick();const {observer,cards}=f.visible();cards.slice(0,3).forEach(card=>observer.show(card));await tick();
  assert.equal(pending.length,2);assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,2);
  f.browser.close();assert.ok(f.calls.filter(call=>call.url.includes('/listing-context')).every(call=>call.signal.aborted));
  pending.forEach(({d,row})=>d.resolve(response(row)));await tick();assert.equal(pending.length,2);
  assert.ok(rows.every(row=>row.market_value_minor===null&&!row.book_listing_context));f.finish();checks++;
 }
 // A changed actor, replaced detail, changed identity or replaced product page
 // cannot revive old content from a late, otherwise successful response.
 for(const change of ['actor','logout','detail','identity','page']) {
  const pending=deferred(),f=fixture(()=>pending.promise);await f.browser.open();await tick();
  f.browser.openProduct(f.rows[0]);await tick();
  if(change==='actor')f.client.owner='owner-b';
  if(change==='logout')f.logout();
  if(change==='detail')f.browser.openSort();
  if(change==='identity')f.rows[0].book_details.issue_number='2';
  if(change==='page'){f.browser.closeSheet();f.browser.reset();await tick();}
  pending.resolve(response());await tick();
  assert.equal(f.browser.sheet.querySelector('.book-ebay-range'),null,change);assert.equal(f.rows[0].book_listing_context,undefined,change);
  f.finish();checks++;
 }
 // Expiry removes dated asks and listing photos without a background refetch.
 {
  const f=fixture(async()=>response(book,{expires_at:new Date(Date.now()+70).toISOString()}));await f.browser.open();await tick();
  const {observer,cards}=f.visible(),card=cards[0];observer.show(card);await tick();
  card.querySelector('.dr-browse-product-image img').dispatchEvent(new f.w.Event('error'));
  const img=card.querySelector('.dr-browse-product-image img');img.dispatchEvent(new f.w.Event('load'));
  await pause(90);assert.equal(card.querySelector('.book-ebay-range'),null);assert.equal(card.querySelector('.book-ebay-photo-credit'),null);
  assert.equal(card.querySelector('.dr-browse-product-image img'),null);assert.equal(f.rows[0].book_listing_context,undefined);
  assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,1);
  const refresh=card.querySelector('.book-ebay-refresh');assert.ok(refresh);refresh.click();await tick();await tick();
  assert.equal(f.calls.filter(call=>call.url.includes('/listing-context')).length,2);
  assert.ok(card.querySelector('.book-ebay-range'));f.finish();checks++;
 }
 // A selected catalogue book can reuse the already displayed source photo,
 // while copy condition, printing and sale price remain unfilled.
 {
  const f=fixture();
  f.w.state={session:{user:{id:'owner-a'},access_token:'private-token'}};
  f.w.apiRequest=async()=>({status:'UNAVAILABLE',market_value_minor:null});f.w.loadOwnerInventory=async()=>{};f.w.loadOwnerOverview=async()=>{};
  f.w.eval(source('owner-books.js'));
  const row=structuredClone(book);row.book_listing_context=response(row);
  f.w.DropRateBooks.open({book:row.book_details,catalogue:row});
  const preview=f.w.document.getElementById('owner-book-selected');
  preview.querySelector('img').dispatchEvent(new f.w.Event('error'));
  const img=preview.querySelector('img');assert.equal(img.src,response().items[0].image_url);img.dispatchEvent(new f.w.Event('load'));
  assert.match(preview.textContent,/eBay listing photo · Copy may vary/);
  assert.equal(img.crossOrigin,'anonymous');assert.equal(img.referrerPolicy,'no-referrer');
  for(const field of ['printing','condition','price'])assert.equal(f.w.document.getElementById('owner-book-'+field).value,'',field);
  assert.equal(f.calls.length,0,'Selected context reuse must not start another provider lookup');
  f.w.DropRateBooks.reset();assert.equal(preview.querySelector('.book-ebay-photo-credit'),null);
  f.finish();checks++;
 }
 for(const html of ['owner.html','index.html']){
  const content=source(html);assert.ok(content.includes('/assets/book-ebay-context.css?v=1'));assert.ok(content.includes('/assets/book-ebay-context.js?v=1'));
  assert.ok(content.indexOf('/assets/book-ebay-context.js')<content.indexOf(html==='owner.html'?'/assets/owner-inventory.js':'/assets/app.js'));
 }
 console.log(`book eBay context: ${checks} behavioral groups passed`);
})().catch(error=>{console.error(error);process.exit(1);});
