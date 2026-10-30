const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-browser.js'),'utf8');
const ownerShell=fs.readFileSync(path.join(__dirname,'../../backend/app/static/owner.html'),'utf8');
assert.ok(ownerShell.includes('/assets/catalogue-browser.js?v=book-ebay-context-v1'), 'Seller Hub must load the current book artwork and listing-context script');
assert.ok(ownerShell.includes('/assets/catalogue-browser.css?v=simple-v1'), 'Seller Hub must load the fresh mobile sort styles');
const titleArt=fs.readFileSync(path.join(__dirname,'../../backend/app/static/catalogue-title-art.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const card={key:'c:00000000-0000-0000-0000-000000000001',catalogue_id:'card-1',name:'Luffy',game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',set_name:'A Fist of Divine Speed',set_id:'OP11',language:'English',product_type:'CARD',variant:'Foil',card_number:'OP11-118',owned_quantity:0,market_value_minor:null,source_kind:'CATALOGUE'};
const games=[{game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',languages:['English','Japanese']}];
const askingFixture=()=>({status:'ASKING_PRICE_ESTIMATE',source:'EBAY_OFFICIAL_BROWSE',method_version:'EBAY_UK_RAW_ASK_V1',
 estimate_minor:1234,estimate_high_minor:1400,currency:'GBP',listing_count:4,seller_count:3,
 observed_at:new Date(Date.now()-60000).toISOString(),expires_at:new Date(Date.now()+3600000).toISOString(),
 shipping_basis:'ITEM_PLUS_SHIPPING',shipping_context:'CONFIGURED_SHOP_POSTCODE_BENCHMARK',condition:'Near Mint',finish:'Foil',physical_valuation_eligible:false,recommended_retail_minor:null});
let checks=0;
function fixture(handler=async()=>({items:[card],has_more:false}),owner='account-a',embedded=false,gameHandler=async()=>({items:games})){
 const dom=new JSDOM('',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});const w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.eval(fs.readFileSync(path.join(__dirname,'../../backend/app/static/reference-value-display.js'),'utf8'));w.eval(titleArt);w.eval(source);let alive=true;const calls=[];
 const client={owner,active:()=>alive,request:async(url,options)=>{calls.push({url,...options});return url.endsWith('/games')?gameHandler():handler(url,options);}};
 let host;
 if(embedded){w.document.body.innerHTML='<header class="topbar"></header><nav class="seller-nav"></nav><aside class="owner-sidebar"></aside><header class="owner-page-header"></header><main id="catalogue-host"></main>';host=w.document.getElementById('catalogue-host');}
 const browser=new w.DropRateCatalogue.Browser({host,client,navigate:()=>{},scan:()=>{},graded:()=>{},afterSave:async()=>{}});
 return {browser,w,calls,logout:()=>{alive=false;browser.destroy();},finish:()=>{browser.destroy();w.close();}};
}
(async()=>{
 {
  const row={...card,market_value_minor:3,market_value_source:'DROP_RATE_COMPUTED_MARKET_V1',market_quotes:[{
   source:'DROP_RATE_COMPUTED_MARKET_V1',price_gbp_minor:3,observed_at:new Date().toISOString()}]};
  const f=fixture(async()=>({items:[row],has_more:false}));await f.browser.open();f.browser.pickGame(games[0]);await tick();
  assert.equal(f.browser.find('[data-price-key]').textContent,'Drop Rate estimate: £0.03');
  f.browser.openProduct(row);assert.match(f.browser.sheet.textContent,/Drop Rate estimate: £0.03/);
  assert.doesNotMatch(f.browser.sheet.textContent,/undefined:|Cardmarket #/);f.finish();
 }
 // Current asking evidence is visibly separate and never fills market-value fields.
 {
  const row={...card,asking_price_estimate:askingFixture()},f=fixture(async()=>({items:[row],has_more:false}));
  await f.browser.open();f.browser.pickGame(games[0]);await tick();
  assert.equal(f.browser.find('[data-price-key]').textContent,'Asking-price estimate: £12.34');
  f.browser.openProduct(row);
  assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Asking-price estimate: £12.34');
  assert.match(f.browser.sheet.textContent,/eBay current listings: 4 listings from 3 sellers/);
  assert.ok(f.browser.sheet.textContent.includes(new Date(row.asking_price_estimate.observed_at).toLocaleDateString('en-GB')));
  assert.match(f.browser.sheet.textContent,/Estimate basis: Near Mint · Foil · Shop delivery estimate included/);
  assert.match(f.browser.sheet.textContent,/Current asking prices; not completed sales or a valuation of your copy/);
  assert.doesNotMatch(f.browser.sheet.textContent,/Cardmarket|No verified market value/);
  assert.equal(row.market_value_minor,null);
  assert.equal(row.asking_price_estimate.recommended_retail_minor,null);
  f.finish();checks++;
 }
 // Expired, incomplete or unsafe evidence never becomes a displayed estimate.
 {
  const f=fixture();
  const invalid=[null,{}, {status:'AVAILABLE'}, {source:'CARDMARKET'}, {method_version:'unknown'}, {currency:'USD'},
   {estimate_minor:0},{estimate_minor:1234.5},{estimate_minor:'1234'},{estimate_high_minor:1233},{estimate_high_minor:null},
   {listing_count:2},{seller_count:2},{seller_count:5},{shipping_basis:'ITEM_ONLY'},
   {shipping_context:null},{shipping_context:'BUYER_POSTCODE'},
   {condition:'Graded'},{finish:'Unknown'},{physical_valuation_eligible:true},{recommended_retail_minor:1300},
   {observed_at:'bad'},{expires_at:'bad'},{observed_at:new Date(Date.now()+60000).toISOString()},
   {observed_at:new Date(Date.now()-4*86400000).toISOString()},
   {expires_at:new Date(Date.now()-1).toISOString()}, {expires_at:new Date(Date.now()+4*86400000).toISOString()}];
  for(const patch of invalid){
   const estimate=patch===null?null:Object.keys(patch).length?{...askingFixture(),...patch}:{};
   f.browser.openProduct({...card,asking_price_estimate:estimate});
   assert.doesNotMatch(f.browser.sheet.textContent,/Asking-price estimate|eBay current listings/);
   assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Value unavailable');
  }
  f.finish();checks++;
 }
 // Existing supported prices win; fresh asking evidence may replace dated history only in presentation.
 {
  const f=fixture(),estimate=askingFixture();
  for(const stronger of [
   {market_value_minor:900,market_value_source:'CARDMARKET_BULK_SINGLES'},
   {shared_price:{status:'CATALOGUE_GUIDE',market_value_minor:900,label:'Catalogue guide'}}]){
   f.browser.openProduct({...card,...stronger,asking_price_estimate:estimate});
   assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Value: £9.00');
   assert.doesNotMatch(f.browser.sheet.textContent,/Asking-price estimate|eBay current listings/);
  }
  const history={status:'STALE',market_value_minor:null,last_known_minor:800,checked_at:'2026-01-01T00:00:00Z'};
  const row={...card,shared_price:history,asking_price_estimate:estimate};
  f.browser.openProduct(row);
  assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Asking-price estimate: £12.34');
  assert.equal(row.shared_price,history);assert.equal(row.market_value_minor,null);
  f.finish();checks++;
 }
 // A legacy guide refresh may omit asking evidence; it preserves it until a stronger value arrives.
 for(const outcome of ['missing','stronger']){
  const waiting=deferred(),estimate=askingFixture(),row={...card,key:'r:0123456789abcdef0123456789abcdef',
   source_kind:'REFERENCE',market_refresh_needed:true,asking_price_estimate:estimate};
  const f=fixture(async url=>url.endsWith('/market-values')?waiting.promise:{items:[row],has_more:false});
  await f.browser.open();f.browser.pickGame(games[0]);await tick();f.browser.openProduct(row);
  assert.equal(f.browser.find('[data-price-key]').textContent,'Asking-price estimate: £12.34');
  waiting.resolve({items:[{key:row.key,market_value_minor:outcome==='stronger'?900:null,
   market_value_source:outcome==='stronger'?'TCGDEX_CARDMARKET':null,market_refresh_needed:false,
   provider_refresh_failed:outcome==='missing',market_quotes:[]}]});await tick();
  const label=outcome==='stronger'?'Value: £9.00':'Asking-price estimate: £12.34';
  assert.equal(f.browser.find('[data-price-key]').textContent,label);
  assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,label);
  assert.equal(row.asking_price_estimate,estimate);
  assert.equal(row.market_value_minor,outcome==='stronger'?900:null);
  f.finish();checks++;
 }
 {
  const f=fixture();
  const book={...card,product_type:'COMIC',book_data_attribution:{source_url:'https://www.comics.org/issue/1/',license_url:'https://creativecommons.org/licenses/by-sa/4.0/'}};
  f.browser.openProduct(book);
  assert.equal(f.browser.sheet.querySelector('a').href,book.book_data_attribution.source_url);
  assert.match(f.browser.sheet.textContent,/Edition data adapted from Grand Comics Database.*CC BY-SA 4.0/);
  book.book_data_attribution.source_url='https://www.comics.org.evil.test/issue/1/';
  f.browser.openProduct(book);assert.equal(f.browser.sheet.querySelector('a'),null);
  book.publisher_source_url='https://prhcomics.com/book/?isbn=9781569319017';
  f.browser.openProduct(book);assert.equal(f.browser.sheet.querySelector('a').href,book.publisher_source_url);
  f.finish();checks++;
 }
 // Open Library attribution never implies publisher approval or cover rights.
 {
  const f=fixture(),book={...card,product_type:'COMIC',book_data_attribution:{
    source_url:'https://openlibrary.org/books/OL123M',
    license_url:'https://openlibrary.org/developers/licensing'}};
  f.browser.openProduct(book);
  assert.match(f.browser.sheet.textContent,/Edition metadata from Open Library.*Data licensing/);
  assert.doesNotMatch(f.browser.sheet.textContent,/CC0|CC BY-SA|Official publisher/);
  const links=[...f.browser.sheet.querySelectorAll('a')];
  assert.equal(links[0].href,book.book_data_attribution.source_url);
  assert.equal(links[1].href,book.book_data_attribution.license_url);
  assert.ok(links.every(link=>link.target==='_blank'&&link.rel==='noopener noreferrer'));
  for(const url of ['https://openlibrary.org.evil.test/books/OL123M',
    'http://openlibrary.org/books/OL123M','https://openlibrary.org/books/OL123M?next=x',
    'https://openlibrary.org/works/OL123W','javascript:alert(1)']){
    book.book_data_attribution.source_url=url;f.browser.openProduct(book);
    assert.equal(f.browser.sheet.querySelector('a'),null);
  }
  book.book_data_attribution.source_url='https://openlibrary.org/books/OL123M';
  book.book_data_attribution.license_url='https://creativecommons.org/publicdomain/zero/1.0/';
  f.browser.openProduct(book);assert.equal(f.browser.sheet.querySelector('a'),null);
  f.finish();checks++;
 }
 // A regional guide must retain its actual provider and limitations.
 {
  const f=fixture(),row={...card,market_value_minor:425,
    market_value_source:'POKEWALLET_POKEMON_CARDMARKET_CATALOGUE',
    market_quotes:[],basis_condition:'Raw · Cardmarket Non-English regional guide'};
  f.browser.openProduct(row);
  assert.match(f.browser.sheet.textContent,/Value: £4.25/);
  assert.match(f.browser.sheet.textContent,/Cardmarket Non-English regional guide via PokéWallet/);
  assert.match(f.browser.sheet.textContent,/Japanese language.*not verified/);
  assert.doesNotMatch(f.browser.sheet.textContent,/Cardmarket reference via TCGdex/);
  f.finish();checks++;
 }
 // Mobile sort is visible before opening the overflow menu and is an actual
 // server-side paginated sort, not a client-only rearrangement of 40 tiles.
 {
  const f=fixture(async()=>({items:[card],has_more:false}));
  await f.browser.open();f.browser.pickGame(games[0]);await tick();
  const sort=f.browser.find('[data-action="sort-visible"]');
  const filters=f.browser.find('[data-action="filters-visible"]');
  assert.equal(f.browser.find('.dr-browse-toolbar').hidden,false);
  assert.match(sort.textContent,/Sort: Newest first/);
  assert.equal(filters.textContent,'Filters');
  sort.click();assert.match(f.browser.sheet.textContent,/Name Z–A/);
  [...f.browser.sheet.querySelectorAll('button')].find(b=>b.textContent.startsWith('Name Z–A')).click();await tick();
  assert.match(f.calls.at(-1).url,/sort=name_desc/);
  assert.match(sort.textContent,/Name Z–A/);
  sort.click();
  [...f.browser.sheet.querySelectorAll('button')].find(b=>b.textContent.startsWith('Value: high to low')).click();await tick();
  assert.match(f.calls.at(-1).url,/sort=value_desc/);
  assert.match(sort.textContent,/Value: high to low/);
  sort.click();
  [...f.browser.sheet.querySelectorAll('button')].find(b=>b.textContent.startsWith('Oldest first')).click();await tick();
  assert.match(f.calls.at(-1).url,/sort=oldest/);
  assert.match(sort.textContent,/Oldest first/);
  filters.click();assert.match(f.browser.sheet.textContent,/Product Type/);
  f.browser.closeSheet();f.browser.reset();
  assert.equal(f.browser.find('.dr-browse-toolbar').hidden,true);
  f.finish();checks++;
 }
 // No Naruto sealed products: be explicit that the verified index is missing,
 // and offer a working route to browse indexed Naruto cards instead.
 {
  const f=fixture(async()=>({items:[],has_more:false}));
  f.browser.games=[{system_code:'NARUTO',game:'Naruto',languages:['Unknown']}];f.browser.gamesLoaded=true;
  f.browser.filters.system_code='NARUTO';f.browser.filters.product_type='SEALED';
  await f.browser.load();
  assert.match(f.browser.find('.dr-browse-status').textContent,/Naruto sealed products are not yet indexed/);
  assert.doesNotMatch(f.browser.find('.dr-browse-status').textContent,/No matches/);
  const action=[...f.browser.find('.dr-browse-content').querySelectorAll('button')]
    .find(b=>b.textContent==='Browse Naruto cards');
  assert.ok(action);action.click();await tick();
  const params=new URL(f.calls.at(-1).url,'https://example.test').searchParams;
  assert.equal(params.get('system_code'),'NARUTO');
  assert.equal(params.get('product_type'),'CARD');
  f.finish();checks++;
 }
 // Separate Bandai artwork/parallel identity is rendered as a labelled
 // printing, never silently deduplicated or assigned the base-card price.
 {
  const row={...card,source_kind:'REFERENCE',provider:'Bandai Official',system_code:'DRAGON_BALL_SUPER_FUSION_WORLD',
    name:'Android 13',card_number:'FB06-006',set_name:'Release Event Pack [FB06 - FB09]',
    provider_id:'583903:FB06-006_p1',variant:'583903:FB06-006_p1',
    market_value_minor:null};
  const base={...row,key:'r:'+'1'.repeat(32),provider_id:'583006:FB06-006',variant:'583006:FB06-006',set_name:'BOOSTER PACK -RIVALS CLASH- [FB06]'};
  const alt={...row,key:'r:'+'2'.repeat(32)};
  const f=fixture(async()=>({items:[base,alt],has_more:false}));
  f.browser.filters.q='Android 13';await f.browser.load();
  const results=[...f.browser.find('.dr-browse-content').querySelectorAll('.dr-browse-product')];
  assert.equal(results.length,2);
  assert.match(results[0].textContent,/RIVALS CLASH/);
  assert.match(results[1].textContent,/Release Event Pack/);
  assert.match(results[1].textContent,/Printing variant p1/);
  assert.match(results[1].textContent,/Value unavailable/);
  assert.equal(f.browser.rows[0].provider_id,base.provider_id);
  assert.equal(f.browser.rows[1].provider_id,alt.provider_id);
  f.finish();checks++;
 }
 for(const owner of ['account-a','account-b'])for(const view of ['search','set']){
  const ref={...card,key:'r:'+'d'.repeat(32),catalogue_id:null,source_kind:'REFERENCE',
    market_value_minor:132,market_value_source:'SHARED_CATALOGUE_REFERENCE',market_refresh_needed:true,
    shared_price:{status:'CONDITION_REFERENCE',market_value_minor:132,label:'Near-mint reference',
      checked_at:'2026-10-15T12:00:00Z',basis:'English · Near Mint',physical_valuation_eligible:false}};
  const f=fixture(async()=>({items:[ref]}),owner);
  if(view==='search')f.browser.filters.q='OP11-101';
  else {f.browser.filters.system_code=card.system_code;f.browser.set={set_id:'OP11',provider:'Punk Records',system_code:card.system_code};}
  await f.browser.load();
  assert.equal(f.browser.find('[data-price-key]').textContent,'Value: £1.32');
  f.browser.openProduct(ref);
  assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Value: £1.32');
  assert.equal(f.calls.filter(c=>c.url.endsWith('/market-values')).length,0,'Shared price is in the first response, no second fetch');
  assert.equal(ref.catalogue_id,null,'Displaying a value must not create an intake mapping');
  f.finish();checks++;
 }
 {
  const row={...card,image_url:'https://en.onepiece-cardgame.com/images/cardlist/card/OP17-002.png',reference_image_path:'/api/v1/catalogue-browser/reference-image?provider_id=OP17-002'};
  const waiting=deferred(),calls=[];
  const f=fixture(async url=>({items:[{...row,key:row.key+(new URL(url,'https://example.test').searchParams.get('offset')||'0')}],has_more:true}));
  f.w.URL.createObjectURL=()=> 'blob:kept';f.w.URL.revokeObjectURL=()=>{};
  f.browser.client.requestImage=async path=>{calls.push(path);return waiting.promise;};
  f.browser.filters.q='Luffy';await f.browser.load();await tick();
  const first=f.browser.find('.dr-browse-product img');
  await f.browser.load(true);await tick();
  assert.equal(f.browser.find('.dr-browse-product img'),first,'Pagination must retain the loading artwork node');
  assert.equal(calls.length,2,'Earlier pages must not start another download');
  assert.ok(calls.every(path=>path.endsWith('&size=grid')));
  waiting.resolve(new f.w.Blob(['image'],{type:'image/webp'}));await tick();await tick();
  assert.equal(first.src,'blob:kept');assert.equal(f.browser.dialog.querySelectorAll('.dr-browse-product').length,2);
  f.finish();checks++;
 }
 {
  let next=null;const f=fixture(async()=>next?next.promise:{items:[{...card}]});
  f.browser.filters.q='Luffy';await f.browser.load();next=deferred();
  const refresh=f.browser.load(),first=f.browser.find('.dr-browse-product');
  next.resolve({items:[{...card}]});await refresh;
  assert.equal(f.browser.find('.dr-browse-product'),first,'Unchanged revalidation must preserve loaded cards');
  f.finish();checks++;
 }
 {
  const f=fixture(),row={...card,image_url:'https://assets.tcgdex.net/en/me/30th/002/high.webp'};
  const grid=f.browser.productImage(row),detail=f.browser.productImage(row,'dr-browse-detail-image');
  assert.equal(grid.querySelector('img').src,'https://assets.tcgdex.net/en/me/30th/002/low.webp');
  assert.equal(detail.querySelector('img').src,row.image_url);
  grid.querySelector('img').dispatchEvent(new f.w.Event('error'));
  assert.equal(grid.querySelector('img').src,row.image_url,'A missing thumbnail must retain the exact original fallback');
  f.browser.openProduct({...row,market_value_source:'CARDMARKET_BULK_SINGLES',market_value_minor:1234});
  assert.match(f.browser.sheet.textContent,/Value: £12.34/);assert.match(f.browser.sheet.textContent,/combines languages and conditions/);
  f.finish();checks++;
 }
 // Pokémon/Dragon Ball load from the provider first; when cross-site loading
 // fails, use the exact signed-in reference route with a bounded grid image.
 {
  const f=fixture(),calls=[];
  f.w.URL.createObjectURL=()=> 'blob:provider-relay';f.w.URL.revokeObjectURL=()=>{};
  f.browser.client.requestImage=async path=>{calls.push(path);return new f.w.Blob(['image'],{type:'image/webp'});};
  const row={...card,source_kind:'REFERENCE',provider:'TCGdex',system_code:'POKEMON_TCG',
    image_url:'https://assets.tcgdex.net/en/me/30th/001/high.webp',
    reference_image_path:'/api/v1/catalogue-browser/reference-image?provider=TCGdex&system_code=POKEMON_TCG&provider_id=me30-1'};
  const picture=f.browser.productImage(row);f.w.document.body.append(picture);
  const img=picture.querySelector('img');
  assert.equal(img.src,'https://assets.tcgdex.net/en/me/30th/001/low.webp');
  assert.equal(calls.length,0,'Do not proxy an image that loads from the provider');
  img.dispatchEvent(new f.w.Event('error'));await tick();await tick();
  assert.equal(calls.length,1);
  assert.ok(calls[0].endsWith('&size=grid'),'The fallback must not download the detail-size asset');
  assert.equal(img.src,'blob:provider-relay');
  f.finish();checks++;
 }
 {
  const f=fixture();
  f.browser.openProduct({...card,market_value_source:'TCGDEX_TCGPLAYER',market_quotes:[{source:'TCGDEX_TCGPLAYER',finish:'Normal',original_minor:42}]});
  assert.match(f.browser.sheet.textContent,/TCGplayer US context · \$0.42/);
  assert.match(f.browser.sheet.textContent,/Value unavailable/);
  assert.doesNotMatch(f.browser.sheet.textContent,/£0.42/);
  f.browser.openProduct({...card,key:'s:guide',product_type:'SEALED',market_value_source:'CARDMARKET_BULK',market_value_minor:8000,market_quotes:[]});
  assert.match(f.browser.sheet.textContent,/Value: £80.00/);
  assert.match(f.browser.sheet.textContent,/spans languages and conditions/);
  f.finish();checks++;
 }
 {
  const f=fixture(),waiting=deferred(),calls=[],revoked=[];
  f.w.URL.createObjectURL=()=> 'blob:catalogue-art';f.w.URL.revokeObjectURL=url=>revoked.push(url);
  f.browser.client.requestImage=async(path,options)=>{calls.push({path,...options});return waiting.promise;};
  const row={...card,image_url:'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png',reference_image_path:'/api/v1/catalogue-browser/reference-image?provider_id=OP16-077'};
  const pictures=Array.from({length:6},(_,i)=>f.browser.productImage({...row,reference_image_path:row.reference_image_path+'&copy='+i}));pictures.forEach(p=>f.w.document.body.append(p));
  await tick();
  assert.equal(calls.length,4,'Artwork requests must be bounded');
  waiting.resolve(new f.w.Blob(['image'],{type:'image/png'}));await tick();await tick();
  assert.equal(calls.length,6);
  const img=pictures[0].querySelector('img');assert.equal(img.src,'blob:catalogue-art');
  img.dispatchEvent(new f.w.Event('load'));assert.equal(pictures[0].querySelector('span').hidden,true);
  f.browser.clearArtwork();assert.equal(revoked.length,6);f.finish();checks++;
 }
 {
  const f=fixture(),waiting=deferred();let created=0;
  f.w.URL.createObjectURL=()=>{created++;return 'blob:stale';};f.w.URL.revokeObjectURL=()=>{};
  f.browser.client.requestImage=()=>waiting.promise;
  const picture=f.browser.productImage({...card,image_url:'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png',reference_image_path:'/api/v1/catalogue-browser/reference-image?provider_id=OP16-077'});
  f.w.document.body.append(picture);await tick();
  f.logout();waiting.resolve(new f.w.Blob(['image'],{type:'image/png'}));await tick();assert.equal(created,0);f.finish();checks++;
 }
 {
  const f=fixture();f.browser.client.requestImage=async()=>{throw new Error('Unavailable');};
  const picture=f.browser.productImage({...card,image_url:'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png',fallback_image_url:'https://cdn.shopify.com/exact-approved.png',reference_image_path:'/api/v1/catalogue-browser/reference-image?provider_id=OP16-077'});
  f.w.document.body.append(picture);const img=picture.querySelector('img');await tick();
  assert.equal(img.src,'https://cdn.shopify.com/exact-approved.png');img.dispatchEvent(new f.w.Event('error'));
  assert.equal(picture.textContent,'Image unavailable');f.finish();checks++;
 }
 {
  const waiting=deferred(),ref={...card,key:'r:'+'a'.repeat(32),provider:'TCGdex',source_kind:'REFERENCE',market_refresh_needed:true};
  const f=fixture(async(url,options)=>url.endsWith('/market-values')?waiting.promise:{items:[ref]});
  f.browser.filters.q='Seel';await f.browser.open();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Checking value/);
  f.browser.openProduct(ref);const select=f.browser.sheet.querySelector('select');select.value='Near Mint';select.dispatchEvent(new f.w.Event('change'));
  waiting.resolve({items:[{key:ref.key,market_value_minor:7,market_value_high_minor:19,market_value_source:'TCGDEX_CARDMARKET',market_refresh_needed:false,
    basis_condition:'Raw · Cardmarket',pricing_updated_at:'2026-10-08T12:00:00Z',market_quotes:[{finish:'Normal',price_gbp_minor:7},{finish:'Reverse Holofoil',price_gbp_minor:19}]}]});
  await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value: £0.07/);
  assert.match(f.browser.sheet.textContent,/Reverse Holofoil: £0.19/);
  assert.match(f.browser.sheet.textContent,/converted from EUR/);
  assert.equal(f.browser.sheet.querySelector('select'),select);assert.equal(select.value,'Near Mint');
  const request=f.calls.find(call=>call.url.endsWith('/market-values'));
  assert.equal(request.method,'POST');assert.deepEqual(JSON.parse(request.body).keys,[ref.key]);
  f.finish();checks++;
 }
 for (const outcome of ['empty', 'failed', 'current']) {
  const waiting=deferred(),history={status:'STALE',last_known_minor:800,last_known_high_minor:1200,
    checked_at:'2026-10-01T12:00:00Z',physical_valuation_eligible:false,reason:'Historical catalogue guide'};
  const ref={...card,key:'r:'+'e'.repeat(32),provider:'TCGdex',source_kind:'REFERENCE',
    market_refresh_needed:true,shared_price:history};
  const f=fixture(async url=>url.endsWith('/market-values')?waiting.promise:{items:[ref]});
  f.browser.filters.q='Stored guide';await f.browser.open();f.browser.openProduct(ref);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/market-values')).length,1,'Historical display must not suppress refresh');
  assert.match(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,/Value: £8.00/);
  waiting.resolve({items:[{key:ref.key,market_value_minor:outcome==='current'?1500:null,
    market_value_high_minor:outcome==='current'?1800:null,market_value_source:'TCGDEX_CARDMARKET',
    shared_price:null,provider_refresh_failed:outcome==='failed',market_refresh_needed:false}]});
  await tick();
  if(outcome==='current') {
    assert.equal(ref.shared_price,undefined);
    assert.match(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,/Value: £15.00/);
    assert.doesNotMatch(f.browser.find('[data-price-key]').textContent,/Last known/);
  } else {
    assert.equal(ref.market_value_minor,null,'History cannot become current money');
    assert.equal(ref.shared_price,history);
    assert.match(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,/Value: £8.00/);
    assert.match(f.browser.find('[data-price-key]').textContent,/Value: £8.00/);
  }
  f.finish();checks++;
 }
 {
  const waiting=deferred(),ref={...card,key:'r:'+'b'.repeat(32),market_refresh_needed:true};
  const f=fixture(async(url)=>url.endsWith('/market-values')?waiting.promise:{items:[ref]});
  f.browser.filters.q='Old search';await f.browser.open();f.browser.reset();
  waiting.resolve({items:[{key:ref.key,market_value_minor:900,market_refresh_needed:false}]});await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Browse cards, comics & manga/);
  assert.equal(ref.market_value_minor,null);f.finish();checks++;
 }
 {
  const ref={...card,key:'r:'+'c'.repeat(32),market_refresh_needed:true};
  const f=fixture(async(url)=>{if(url.endsWith('/market-values'))throw new Error('Provider down');return {items:[ref]};});
  f.browser.filters.q='Card';await f.browser.open();await tick();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value temporarily unavailable/);
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
  const f=fixture();await f.browser.open();assert.match(f.browser.find('.dr-browse-content').textContent,/Browse cards, comics & manga/);
  assert.equal(f.calls.length,1);f.browser.filters.product_type='SEALED';await f.browser.load();
  assert.match(f.calls.at(-1).url,/product_type=SEALED/);assert.match(f.browser.find('.dr-browse-chips').textContent,/Sealed Only/);
  f.browser.reset();assert.equal(f.browser.filters.product_type,'');assert.match(f.browser.find('.dr-browse-content').textContent,/Browse cards, comics & manga/);
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
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value unavailable/);
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
 // Cached navigation renders before revalidation, with isolation and bounded state.
 {
  let next=null;const f=fixture(()=>next?next.promise:Promise.resolve({items:[card]}));
  f.browser.filters.q='Luffy';await f.browser.load();next=deferred();
  const refresh=f.browser.load();assert.match(f.browser.find('.dr-browse-content').textContent,/Luffy/);
  next.resolve({items:[{...card,name:'Updated card'}]});await refresh;
  assert.match(f.browser.find('.dr-browse-content').textContent,/Updated card/);
  assert.equal(f.browser.pageCache.size,1);f.logout();assert.equal(f.browser.pageCache.size,0);f.finish();checks++;
 }
 // A return visit uses the session image cache, while logout destroys its bytes.
 {
  const f=fixture();let fetched=0;f.w.URL.createObjectURL=()=> 'blob:cached';f.w.URL.revokeObjectURL=()=>{};
  f.browser.client.requestImage=async()=>{fetched++;return new f.w.Blob(['image'],{type:'image/png'});};
  const row={...card,image_url:'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png',reference_image_path:'/api/v1/catalogue-browser/reference-image?provider_id=OP16-077'};
  let picture=f.browser.productImage(row);f.w.document.body.append(picture);await tick();await tick();
  assert.equal(fetched,1);assert.equal(picture.querySelector('img').src,'blob:cached');
  picture.remove();f.browser.clearArtwork();picture=f.browser.productImage(row);f.w.document.body.append(picture);await tick();
  assert.equal(fetched,1);assert.equal(picture.querySelector('img').src,'blob:cached');
  f.logout();assert.equal(f.browser.artworkCache.size,0);assert.equal(f.browser.artworkBytes,0);f.finish();checks++;
 }
 // Visible sealed navigation cannot inherit a card-checklist provider scope.
 {
  const f=fixture();f.browser.set={set_id:'OP11',provider:'Punk Records',system_code:'ONE_PIECE_CARD_GAME'};
  f.browser.find('[data-type="SEALED"]').click();await tick();
  assert.match(f.calls.at(-1).url,/product_type=SEALED/);assert.doesNotMatch(f.calls.at(-1).url,/provider=|set_id=/);
  assert.equal(f.browser.find('[data-type="SEALED"]').getAttribute('aria-pressed'),'true');f.finish();checks++;
 }
 // Sealed references require an explicit physical language and keep replay bodies stable.
 {
  const f=fixture(async(url,opts)=>url.endsWith('/intake')?{inventory:{inventory_code:'INV-SEALED'}}:{items:[]});
  const row={...card,key:'s:'+'a'.repeat(32),catalogue_id:null,product_type:'SEALED',source_kind:'SEALED_REFERENCE',language:'Unknown'};
  f.browser.openProduct(row);Object.assign(f.browser.edit,{confirmed:true});f.browser.validateAdd();
  assert.equal(f.browser.sheet.querySelector('[data-add]').disabled,true);
  const select=f.browser.sheet.querySelector('[aria-label="Product language"]');select.value='Japanese';select.dispatchEvent(new f.w.Event('change'));
  assert.equal(f.browser.sheet.querySelector('[data-add]').disabled,false);await f.browser.save();
  const body=JSON.parse(f.calls.find(c=>c.url.endsWith('/intake')).body);
  assert.equal(body.language,'Japanese');assert.equal(body.seal_status,'SEALED');assert.equal(body.condition,null);
  assert.equal(f.browser.sheet.querySelector('[aria-label="Product language"]').disabled,true);f.finish();checks++;
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
  await f.browser.open();f.browser.openProduct(card);assert.equal(f.browser.sheet.querySelector('[data-add]').disabled,false);
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
  for(const label of ['Cards Only','Items you own','Watchlist']){
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
 {
  const estimate={...card,market_value_minor:170,market_value_source:'CARDMARKET_ESTIMATE',market_refresh_needed:true,
    basis_condition:'Cardmarket guide · mixed languages and conditions',pricing_updated_at:'2026-10-09T10:00:00Z'};
  const f=fixture(async()=>({items:[estimate]}));f.browser.games=games;f.browser.filters.q='card';await f.browser.open();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value: £1.70/);
  f.browser.openProduct(estimate);assert.match(f.browser.sheet.textContent,/not a condition-adjusted UK sold value/);
  assert.equal(f.calls.filter(c=>c.url.includes('/market-values')).length,0);
  f.finish();checks++;
 }
 for(const kind of ['CARDMARKET_CATALOGUE','TCGDEX_CARDMARKET_VARIANT']){
  const row={...card,catalogue_id:null,source_kind:'REFERENCE',provider:'TCGdex',provider_id:'base1-4',set_id:'base1',
   market_value_minor:1200,market_value_source:kind,market_quotes:[{source:kind,variant_label:'Holofoil · unlimited',
    finish:'Holofoil',product_id:'273699',price_gbp_minor:1200,observed_at:'2026-10-10T00:00:00Z'}]};
  const f=fixture();f.browser.openProduct(row);
  assert.match(f.browser.sheet.textContent,/Value: £12.00/);
  assert.match(f.browser.sheet.textContent,/Card referenceTCGdex · base1-4/);
  assert.match(f.browser.sheet.textContent,/Set reference: base1 · English/);
  assert.match(f.browser.sheet.textContent,/Holofoil · unlimited: £12.00 · Cardmarket #273699/);
  if(kind==='CARDMARKET_CATALOGUE')assert.match(f.browser.sheet.textContent,/not an exact physical-copy valuation/);
  assert.equal(row.owned_quantity,0);f.finish();checks++;
 }
 // Set artwork is logo-first, equally structured and never a card or pack preview.
 {
  const f=fixture();
  f.browser.games=[{game:'Pokémon',system_code:'POKEMON_TCG',languages:['English']}];
  f.browser.filters.system_code='POKEMON_TCG';f.browser.page='sets';
  const base={system_code:'POKEMON_TCG',provider:'TCGdex',language:'English',
    owned_count:0,owned_value_minor:null,unknown_values:0,indexed_count:120,card_count:120};
  f.browser.rows=[
    {...base,set_id:'me05',set_name:'Pitch Black',release_date:'2026-09-16',image_url:'https://example.test/individual-card.png'},
    {...base,set_id:'B1a',set_name:'Crimson Blaze',source_kind:'REFERENCE',image_url:'https://example.test/bulbasaur-card.png'},
    {...base,set_id:'unknown-release',set_name:'Unmapped Long-Named Collection Without Official Logo',image_url:null}
  ];
  f.browser.productImage=()=>{throw new Error('Set tiles must never fetch individual card previews');};
  f.browser.renderRows();
  const tiles=[...f.browser.find('.dr-browse-content').querySelectorAll('.dr-browse-set')];
  assert.equal(tiles.length,3);
  assert.equal(f.browser.find('.dr-browse-set-grid').children.length,3);
  assert.equal(f.browser.find('.dr-browse-set-preview'),null);
  for(const tile of tiles){
    assert.equal(tile.querySelectorAll('.dr-browse-set-art').length,1);
    assert.equal(tile.querySelectorAll('.dr-browse-set-visual').length,1);
    assert.equal(tile.querySelectorAll('.dr-browse-set-info').length,1);
    assert.equal(tile.querySelectorAll('.dr-browse-set-stats').length,1);
    assert.equal(tile.querySelector('.dr-browse-set-game').textContent,'Pokémon');
    assert.match(tile.querySelector('.dr-browse-set-stats').textContent,/Progress: 0\/120/);
  }
  assert.match(tiles[0].querySelector('.dr-browse-set-logo').src,/pokemon-mega-evolution-pitch-black\.png$/);
  assert.equal(tiles[0].querySelector('.dr-browse-set-name').textContent,'Pitch Black');
  assert.match(tiles[1].querySelector('.dr-browse-set-logo').src,/\/assets\/title-art\/pokemon\.webp$/);
  assert.equal(tiles[1].querySelector('.dr-browse-set-name').textContent,'Crimson Blaze');
  assert.doesNotMatch(f.browser.find('.dr-browse-content').innerHTML,/bulbasaur-card|individual-card|Card preview|Product preview/i);
  assert.match(tiles[0].querySelector('.dr-browse-release').textContent,/16 Sep(?:t)? 2026/);
  const broken=tiles[1].querySelector('.dr-browse-set-logo');broken.dispatchEvent(new f.w.Event('error'));
  assert.equal(tiles[1].querySelector('img'),null,'Broken title art must expose the brand fallback, never a card');
  assert.equal(tiles[1].querySelector('.dr-browse-set-fallback').textContent,'✦');
  assert.equal(tiles[1].querySelector('.dr-browse-set-name').textContent,'Crimson Blaze');
  f.finish();checks++;
 }

 // The backend owns set artwork selection. Client validates its typed, safe sources.
 {
  const f=fixture();
  f.browser.games=[{game:'Pokémon',system_code:'POKEMON_TCG',languages:['English']}];
  f.browser.filters.system_code='POKEMON_TCG';f.browser.page='sets';
  const base={system_code:'POKEMON_TCG',provider:'TCGdex',language:'English',
    owned_count:0,owned_value_minor:null,indexed_count:107,card_count:107};
  f.browser.rows=[
    {...base,set_id:'A3b',set_name:'Eevee Grove',artwork:{
      type:'GAME_LOGO',status:'SET_LOGO_MISSING',file:'pokemon.webp',source:'OFFICIAL_GAME_MARK'}},
    {...base,set_id:'base1',set_name:'Base Set',artwork:{
      type:'SET_LOGO',status:'SOURCE_INDEXED',url:'https://assets.tcgdex.net/en/base/base1/logo.webp',source:'TCGDEX'}},
    {...base,set_id:'unsafe',set_name:'No official logo',artwork:{
      type:'SET_LOGO',status:'SOURCE_INDEXED',url:'https://untrusted.example/evil-card.png',source:'TCGDEX'}},
    {...base,set_id:'missing',set_name:'Missing title artwork',artwork:{
      type:'BRANDED_FALLBACK',status:'SET_LOGO_MISSING',source:'DROP_RATE_FALLBACK'}}
  ];
  f.browser.productImage=()=>{throw new Error('Must never display a reference-card preview for sets');};
  f.browser.renderRows();
  const tiles=[...f.browser.find('.dr-browse-set-grid').children];
  assert.equal(tiles.length,4);
  assert.equal(tiles[0].dataset.artworkStatus,'SET_LOGO_MISSING');
  assert.match(tiles[0].querySelector('img').src,/\/assets\/title-art\/pokemon\.webp$/);
  assert.equal(tiles[1].dataset.artworkStatus,'SOURCE_INDEXED');
  assert.equal(tiles[1].querySelector('img').src,'https://assets.tcgdex.net/en/base/base1/logo.webp');
  assert.doesNotMatch(f.browser.find('.dr-browse-content').innerHTML,/untrusted\.example|evil-card/);
  assert.equal(tiles[3].querySelector('img'),null);
  assert.equal(tiles[3].querySelector('.dr-browse-set-fallback').textContent,'✦');
  for(const tile of tiles)assert.ok(tile.querySelector('.dr-browse-set-name').textContent.length);
  f.finish();checks++;
 }
 // Curated publisher references never imply manufacturer image rights, price,
 // stock ownership or automatically confirmed product language.
 {
  const manufacturer={...card,key:'s:'+'d'.repeat(32),provider:'Kayou Official',
    provider_id:'NR-RDIV-Z001-NA',source_kind:'SEALED_REFERENCE',
    system_code:'NARUTO_KAYOU',game:'Naruto Kayou',
    name:'Naruto Heaven Scroll Series 1 · Version A Booster Box (24 packs)',
    set_name:'Heaven Scroll · Series 1',
    product_type:'SEALED',language:'Unknown',image_url:null,market_value_minor:null,
    source_url:'https://www.kayouofficial.com/en-US/series/series-5zdty4vj'};
  const f=fixture(async()=>({items:[manufacturer],has_more:false}));
  f.browser.filters.system_code='NARUTO';f.browser.filters.product_type='SEALED';
  await f.browser.load();
  assert.match(f.browser.find('.dr-browse-content').textContent,/Verified Kayou product/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value unavailable/);
  assert.equal(f.browser.find('.dr-browse-status').textContent,'');
  f.browser.openProduct(manufacturer);
  const link=f.browser.sheet.querySelector('.dr-browse-publisher-source');
  assert.ok(link,'Official source link should be visible rather than unlicensed pack art');
  assert.equal(link.href,manufacturer.source_url);
  assert.equal(link.rel,'noopener noreferrer');
  assert.equal(link.target,'_blank');
  assert.match(f.browser.sheet.textContent,/Packaging photo pending/);
  assert.match(f.browser.sheet.textContent,/Check the packaging, edition, pack count and language/);
  assert.equal(f.browser.sheet.querySelector('[data-add]').disabled,true);
  f.finish();checks++;
 }
 // Never link to another publisher or untrusted spoofed Kayou URL.
 {
  const f=fixture();
  f.browser.openProduct({...card,source_kind:'SEALED_REFERENCE',provider:'Kayou Official',
    source_url:'https://www.kayouofficial.com.evil.test/en-US/series/series-5zdty4vj'});
  assert.equal(f.browser.sheet.querySelector('.dr-browse-publisher-source'),null);
  f.finish();checks++;
 }
 // A missing TCGdex image is not a licence to borrow another variant's
 // photo. The local Pokémon *game logo* is expressly labelled as a fallback.
 {
  const f=fixture();
  const row={...card,source_kind:'REFERENCE',provider:'TCGdex',provider_id:'SV11B-001',language:'Japanese',
    system_code:'POKEMON_TCG',image_url:null,display_image_url:null,fallback_image_url:null};
  const panel=f.browser.productImage(row);
  assert.equal(panel.querySelector('img'),null);
  assert.equal(panel.classList.contains('dr-browse-reference-photo-pending'),true);
  assert.match(panel.textContent,/Card image not yet available/);
  assert.match(panel.textContent,/Reference only/);
  assert.equal(row.image_url,null);
  f.finish();checks++;
 }
 // An exact old TCGdex URL that genuinely fails rendering takes the same
 // truthful path, but never substitutes the English card for Japanese.
 {
  const f=fixture();
  const row={...card,source_kind:'REFERENCE',provider:'TCGdex',provider_id:'SV11B-001',language:'Japanese',
    system_code:'POKEMON_TCG',image_url:'https://assets.tcgdex.net/ja/sv11b/SV11B-001/high.webp'};
  const panel=f.browser.productImage(row);
  panel.querySelector('img').dispatchEvent(new f.w.Event('error')); // low thumbnail
  panel.querySelector('img').dispatchEvent(new f.w.Event('error')); // exact full source
  assert.equal(panel.querySelector('img'),null);
  assert.ok(panel.classList.contains('dr-browse-reference-photo-pending'));
  assert.match(panel.textContent,/Reference only/);
  f.finish();checks++;
 }
 // Comics and manga are first-class empty catalogue sections. Neither
 // invents book stock or sends a CARD-intake request from the book UI.
 {
  const f=fixture(async()=>({items:[],has_more:false}));
  f.browser.games=[{system_code:'COMICS',game:'Comics',languages:[],products:0,sets:0},
    {system_code:'MANGA',game:'Manga',languages:[],products:0,sets:0}];
  f.browser.gamesLoaded=true;
  let opened=0;f.browser.options.books=()=>{opened++;};
  await f.browser.open();
  const tiles=f.browser.find('.dr-browse-game-grid');
  assert.equal(tiles.querySelectorAll('button').length,2);
  assert.match(tiles.textContent,/COMICS/);
  assert.match(tiles.textContent,/MANGA/);
  tiles.querySelector('button[data-system="COMICS"]').click();await tick();
  const url=new URL(f.calls.at(-1).url,'https://example.test');
  assert.equal(url.searchParams.get('system_code'),'COMICS');
  assert.equal(url.searchParams.get('product_type'),'COMIC');
  assert.match(f.browser.find('.dr-browse-status').textContent,/No books have been added yet/);
  assert.match(f.browser.find('.dr-browse-chips').textContent,/Comics & Manga/);
  const btn=[...f.browser.find('.dr-browse-content').querySelectorAll('button')]
    .find(x=>x.textContent==='Add a comic or manga');
  assert.ok(btn);btn.click();await tick();
  assert.equal(opened,1);
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
  f.finish();checks++;
 }
 {
  const book={...card,key:'c:00000000-0000-0000-0000-000000000025',
    product_type:'COMIC',system_code:'MANGA',game:'Manga',
    name:'One Piece Volume 1',set_name:'One Piece',card_number:'1',
    variant:'Manga',language:'English',market_value_minor:null,reference_value:null,
    source_kind:'CATALOGUE',book_details:{system_code:'MANGA',series_title:'One Piece',issue_number:'1',barcode_gtin:'9781569319017',printing_number:null},
    publisher_source_url:'https://www.viz.com/manga-books/manga/one-piece-volume-1/product/139',
    image_url:null,display_image_url:null,artwork_kind:'PUBLISHER_REFERENCE',
    reference_image_path:'/api/v1/catalogue-browser/reference-image?provider=Official+Publisher&system_code=MANGA&language=English&provider_id=00000000-0000-0000-0000-000000000025&reference_kind=book',
    book_market_status:'PRINTING_REVIEW_REQUIRED',
    book_sold_search_url:'https://www.ebay.co.uk/sch/i.html?_nkw=9781569319017&LH_Sold=1&LH_Complete=1'};
  const f=fixture(async()=>({items:[book],has_more:false}));
  const images=[];f.browser.loadReferenceImage=(image,path)=>images.push({image,path});
  let opened=0,bookOptions;f.browser.options.books=options=>{opened++;bookOptions=options;};
  f.browser.filters.system_code='MANGA';f.browser.filters.product_type='COMIC';
  await f.browser.open();
  await f.browser.load();
  assert.match(f.browser.find('.dr-browse-content').textContent,/One Piece Volume 1/);
  assert.match(f.browser.find('.dr-browse-content').textContent,/Value pending/);
  assert.ok(images.some(entry=>entry.path===book.reference_image_path+'&size=grid'));
  assert.match(images[0].image.alt,/publisher reference cover/);
  const cardButton=f.browser.find('.dr-browse-product-open');
  cardButton.click();
  assert.match(f.browser.sheet.textContent,/9781569319017/);
  assert.equal(f.browser.sheet.querySelector('a').href,book.publisher_source_url);
  assert.ok(images.some(entry=>entry.path===book.reference_image_path));
  assert.match(f.browser.sheet.textContent,/printing and cover need confirmation/);
  assert.match(f.browser.sheet.textContent,/Publisher reference cover/);
  assert.equal([...f.browser.sheet.querySelectorAll('a')].find(a=>a.textContent.includes('sold listings')).href,book.book_sold_search_url);
  assert.match(f.browser.sheet.textContent,/Check the cover and edition/);
  assert.equal(f.browser.sheet.querySelector('select[aria-label="Condition"]'),null,
    'Book must never use CARD raw/graded intake');
  assert.equal(f.browser.sheet.querySelector('[data-add]'),null);
  const btn=[...f.browser.sheet.querySelectorAll('button')].find(x=>x.textContent==='Add to collection');
  assert.ok(btn);btn.click();await tick();
  assert.equal(opened,1);
  assert.deepEqual(bookOptions.book,book.book_details);
  assert.equal(f.calls.filter(x=>x.url?.endsWith('/intake')).length,0);
  f.finish();checks++;
 }
 console.log('Catalogue browser: '+checks+' search, navigation, filter, ownership, session and retry scenarios passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
