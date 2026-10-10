const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static'),tick=()=>new Promise(r=>setImmediate(r));
const id='d715b0e9-b3c4-451b-a909-5fa233f8a0e5';
const item={id,catalogue_id:'catalogue',inventory_code:'INV-EXACT-COPY',version:3,status:'DRAFT',sale_intent:'FOR_SALE',product_type:'SEALED',game:'One Piece',language:'Japanese',seal_status:'SEALED',name:"Booster Pack: World's Strongest Warriors [OP-17]",set_name:'OP-17',market_value_minor:866,store_price_minor:null,reference_image_url:'https://www.onepiece-cardgame.com/products/pack.webp',reference_image_path:`/api/v1/owner/inventory/${id}/reference-image`,approval_blockers:['Drop Rate intake review','An approved listing photo'],shopify_sync_enabled:true};
function fixture(override={}) {
 const dom=new JSDOM(fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script[^>]*><\/script>/g,''),{url:'https://example.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,run=s=>vm.runInContext(s,dom.getInternalVMContext()),calls=[];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.scrollTo=()=>{};w.fetch=async()=>({ok:true,json:async()=>({})});
 run(fs.readFileSync(path.join(base,'hub-session.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'owner-inventory.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'owner-portal.js'),'utf8').replace(/\ninitialise\(\);\s*$/,''));
 run(`window.testLoadInventory=loadOwnerInventory;state.session={access_token:'secret-session',user:{id:'seller-a'}};loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=loadOwnerInventory=async()=>{};`);
 let current={...item,...override},handler;
 w.testRequest=async(url,options={})=>{calls.push({url,...options});if(handler)return handler(url,options);return {item:current,copies:[current]};};run('apiRequest=window.testRequest');
 return {w,run,calls,setHandler:f=>{handler=f;},setItem:x=>{current={...current,...x};},open:()=>w.DropRateInventory.open(current),finish:()=>w.close()};
}
function btn(w,text){return [...w.document.querySelectorAll('button')].find(b=>b.textContent===text);}
async function click(w,text){const b=btn(w,text);assert.ok(b,`Missing ${text}`);assert.equal(b.disabled,false);b.click();await tick();await tick();}
(async()=>{
 let checks=0;
 {
  const f=fixture({seller_approval_available:true,approval_blockers:[],image_url:'https://cdn.shopify.com/op17.webp'});await f.open();
  assert.match(f.w.document.querySelector('dialog').textContent,/Your stock stays with you/);
  assert.doesNotMatch(f.w.document.querySelector('dialog').textContent,/requests Drop Rate review/);
  f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value='10.00';await click(f.w,'Approve for Shopify');
  assert.deepEqual(JSON.parse(f.calls.find(c=>c.method).body),{version:3,store_price_minor:1000});f.finish();checks++;
 }
 for(const change of ['refresh','account','logout']){
  const f=fixture();let resolve;f.setHandler(()=>new Promise(r=>{resolve=r;}));const pending=f.w.testLoadInventory();
  if(change==='logout')f.run(`clearSession();state.session={access_token:'new',user:{id:'seller-a'}};`);
  else f.run(`state.session={access_token:'new',user:{id:'${change==='refresh'?'seller-a':'seller-b'}'}};`);
  resolve({total:1,items:[item]});await pending;
  assert.equal(f.w.document.querySelectorAll('.owner-card-image-wrap').length,change==='refresh'?1:0);f.finish();checks++;
 }
 {
  const f=fixture();f.run(`renderInventoryCards([${JSON.stringify(item)}]);renderInventoryRows([${JSON.stringify(item)}]);`);
  assert.equal(f.w.document.querySelector('.owner-card-thumb img').src,item.reference_image_url);
  const tile=f.w.document.querySelector('.owner-inventory-card');
  assert.equal(tile.querySelector('.owner-card-meta'),null,'Quick inventory tiles must not expose detailed metadata');
  assert.equal(tile.querySelector('.owner-card-title strong').textContent,item.name);
  assert.match(tile.querySelector('.owner-status-pill').textContent,/DRAFT/);
  assert.match(tile.querySelector('.owner-card-prices').textContent,/£8.66/);
  assert.match(tile.querySelector('.owner-card-prices').textContent,/Store price/);
  assert.doesNotMatch(tile.textContent,/INV-EXACT-COPY|Seal|Language|Type|Inventory ID/);
  assert.ok(tile.querySelector('.owner-inventory-details'),'Manage action must stay available');
  const inventoryRow=f.w.document.querySelector('#owner-inventory-body tr');
  assert.equal(inventoryRow.children.length,4,'List view should have only essential columns');
  assert.doesNotMatch(inventoryRow.textContent,/INV-EXACT-COPY|Japanese|\\bSeal\\b|\\bLanguage\\b/);
  assert.match(inventoryRow.textContent,/£8.66/);
  f.w.document.querySelector('.owner-card-image-wrap').click();await tick();
  assert.equal(f.w.document.querySelector('dialog').open,true);assert.match(f.w.document.querySelector('dialog').textContent,/INV-EXACT-COPY/);
  const facts=f.w.document.querySelector('.owner-item-facts');
  assert.ok(facts,'Full inventory identity must be visible only inside details');
  const entries=[...facts.querySelectorAll('.owner-item-fact')].map(n=>[
    n.querySelector('dt').textContent,n.querySelector('dd').textContent]);
  for(const [label,value] of [['Game','One Piece'],['Language','Japanese'],['Seal','Sealed'],
    ['Type','Sealed product'],['Inventory ID','INV-EXACT-COPY']])
    assert.ok(entries.some(entry=>entry[0]===label&&entry[1]===value),label+' missing from item details');
  assert.equal(tile.querySelector('.owner-item-facts'),null);
  f.w.DropRateInventory.close();f.w.document.querySelector('.owner-inventory-open').click();await tick();assert.equal(f.w.document.querySelector('dialog').open,true);
  assert.match(f.w.document.querySelector('dialog').textContent,/Drop Rate intake review/);assert.equal(btn(f.w,'Sync to Shopify'),undefined);
  assert.equal(f.calls.filter(c=>c.method).length,0);f.finish();checks++;
 }
 // Two approved identical sealed physical copies become ONE quantity-2 card,
 // without mutating or losing distinct inventory IDs or inventing prices.
 {
  const first={...item,status:'APPROVED',store_price_minor:1000,market_value_minor:866,
    can_refresh_market:false,is_consignment:true};
  const second={...first,id:'55fe97fc-7bfa-4a73-a269-664ec56d3004',
    inventory_code:'INV-55FE97FC7BFA4A73A269664EC56D3004',market_value_minor:null,
    can_refresh_market:true};
  const f=fixture(first);
  f.setHandler(async(url,options)=>{
    if(url.startsWith('/api/v1/owner/inventory?'))return {total:2,items:[first,second]};
    if(url.startsWith('/api/v1/owner/channels?'))return {channels:[
      {code:'EBAY',connected:true,sync_enabled:true,connection_status:'READY'}]};
    return {item:first,copies:[first,second]};
  });
  await f.w.testLoadInventory();
  const cards=[...f.w.document.querySelectorAll('.owner-inventory-card')];
  assert.equal(cards.length,1);
  assert.equal(f.w.document.querySelectorAll('#owner-inventory-body tr').length,1);
  assert.equal(cards[0].querySelector('.owner-card-quantity').textContent,'×2');
  assert.match(cards[0].querySelector('.owner-card-prices').textContent,/£8.66/);
  assert.match(cards[0].querySelector('.owner-card-prices').textContent,/1\/2 copies valued/);
  assert.match(cards[0].querySelector('.owner-card-prices').textContent,/£10.00/);
  assert.equal(f.w.document.querySelector('#owner-inventory-total-label').textContent,'1');
  assert.match(f.w.document.querySelector('.owner-inventory-total').textContent,/1product · 2 copies/);
  assert.equal(first.market_value_minor,866);
  assert.equal(second.market_value_minor,null);
  f.w.document.querySelector('.owner-inventory-details').click();await tick();
  assert.match(f.w.document.querySelector('.owner-item-quantity').textContent,/2/);
  assert.equal(f.w.document.querySelector('[aria-label="Choose inventory copy"]').options.length,2);
  assert.equal(btn(f.w,'Sync to eBay'),undefined,'Unsupported eBay sealed publishing must not show a misleading action');
  assert.equal(f.w.document.querySelector('.owner-item-channel-ebay .owner-item-channel-availability').textContent,'Not available yet');
  assert.match(f.w.document.querySelector('.owner-item-channel-ebay').textContent,/Sealed listings not supported/);
  let opened=null;f.w.open=(url,target,options)=>{opened={url,target,options};};
  await click(f.w,'Set up');
  assert.deepEqual(opened,{url:'https://apps.shopify.com/whatnot',target:'_blank',options:'noopener,noreferrer'});
  assert.equal(f.w.document.querySelector('.owner-item-channel-shopify img').src,'https://upload.wikimedia.org/wikipedia/commons/0/0e/Shopify_logo_2018.svg');
  assert.equal(f.w.document.querySelector('.owner-item-channel-ebay img').src,'https://upload.wikimedia.org/wikipedia/commons/1/1b/EBay_logo.svg');
  assert.equal(f.w.document.querySelector('.owner-item-channel-whatnot img').src,'https://upload.wikimedia.org/wikipedia/commons/9/91/Whatnot_Logo_2025.svg');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0,'Channel setup must never claim a listing published');
  f.finish();checks++;
 }
 // Strict grouping invariants: cross-condition, language, price, type, ownership
 // and graded identities must never turn into an interchangeable pack pool.
 {
  const f=fixture();
  const base={...item,status:'APPROVED',store_price_minor:1000,market_value_minor:866,
    sale_intent:'FOR_SALE'};
  for(const variant of [
    {...base,id:'other',language:'English'},
    {...base,id:'other',store_price_minor:900},
    {...base,id:'other',seal_status:'UNSEALED'},
    {...base,id:'other',status:'RESERVED'},
    {...base,id:'other',product_type:'CARD'},
    {...base,id:'other',grade:'10',grading_company:'PSA'},
    {...base,id:'other',variant:'Other packaging'},
  ]){
    const items=[base,variant];
    f.run(`renderInventoryCards(ownerInventoryDisplayGroups(${JSON.stringify(items)}));`);
    assert.equal(f.w.document.querySelectorAll('.owner-inventory-card').length,2,
      'Different physical variants must remain separate');
  }
  f.finish();checks++;
 }
 for(const value of ['', '0', '0.99', '1.001']){
  const f=fixture();await f.open();f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value=value;
  await click(f.w,'Save selling price');assert.equal(f.calls.filter(c=>c.method).length,0);assert.match(f.w.document.querySelector('.owner-item-message').textContent,/at least £1/);f.finish();checks++;
 }
 for(const action of ['Save selling price','Approve sale & request review']){
  const f=fixture();await f.open();f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value='12.34';
  await click(f.w,action);const sent=f.calls.find(c=>c.method);assert.deepEqual(JSON.parse(sent.body),{version:3,store_price_minor:1234});
  assert.ok(sent.url.endsWith(action.startsWith('Save')?'/selling-price':'/approval-request'));assert.equal(sent.body.includes('identity'),false);f.finish();checks++;
 }
 {
  const f=fixture({status:'APPROVED',store_price_minor:1000});await f.open();await click(f.w,'Sync to Shopify');
  assert.ok(f.calls.some(c=>c.url.endsWith('/channels/shopify/sync')&&JSON.parse(c.body).version===3));f.finish();checks++;
 }
 // Already-published physical stock has a save-price control but must never
 // show a second approval or Shopify sync action.
 {
  const f=fixture({status:'APPROVED',sale_intent:'FOR_SALE',
    shopify_state:'PUBLISHED',seller_approval_available:true,
    is_consignment:true,store_price_minor:1000,shopify_sync_enabled:true});
  await f.open();
  const modal=f.w.document.querySelector('dialog');
  assert.ok(modal.querySelector('.owner-item-section h3').textContent==='Selling price');
  assert.equal(btn(f.w,'Approve for Shopify'),undefined);
  assert.equal(btn(f.w,'Sync to Shopify'),undefined);
  assert.ok(btn(f.w,'Save selling price'));
  assert.match(modal.querySelector('.owner-item-channel-shopify').textContent,/Published/);
  assert.equal(modal.querySelector('.owner-item-channel-shopify .owner-item-channel-availability').textContent,'Already live');
  assert.equal(modal.querySelector('.owner-item-channel-ebay button'),null);
  assert.match(modal.querySelector('.owner-item-channel-ebay').textContent,/Sealed packs aren't supported yet/);
  assert.match(modal.querySelector('.owner-item-channel-ebay .owner-item-channel-availability').textContent,/Not available yet/);
  assert.equal(f.calls.filter(call=>call.method==='POST').length,0);
  const allImages=[...modal.querySelectorAll('.owner-item-channel-logo')];
  assert.equal(allImages.length,3);
  assert.ok(allImages.every(img=>img.src.startsWith('https://upload.wikimedia.org/wikipedia/commons/')));
  f.finish();checks++;
 }
 for(const override of [{status:'SOLD'},{status:'RESERVED'},{status:'WITHDRAWN'},{sale_intent:'PERSONAL_COLLECTION',status:'APPROVED'},{shopify_sync_enabled:false,status:'APPROVED'}]){
  const f=fixture(override);await f.open();assert.equal(btn(f.w,'Sync to Shopify'),undefined);
  if(override.status!=='APPROVED'){assert.equal(btn(f.w,'Save selling price').disabled,true);assert.equal(btn(f.w,'−').disabled,true);assert.equal(btn(f.w,'+').disabled,true);}
  f.finish();checks++;
 }
 {
  const f=fixture({product_type:'CARD',grading_company:'PSA',grade:'10',certificate_number:'123'});await f.open();assert.equal(btn(f.w,'+').disabled,true);assert.match(f.w.document.querySelector('dialog').textContent,/own certificate/);f.finish();checks++;
 }
 {
  const f=fixture({product_type:'CARD',seal_status:null,condition:'Near Mint',
    grading_company:'PSA',grade:'10',certificate_number:'PSA-1234567'});await f.open();
  const specs=f.w.document.querySelector('.owner-item-facts');
  const entries=[...specs.querySelectorAll('.owner-item-fact')].map(n=>[
    n.querySelector('dt').textContent,n.querySelector('dd').textContent]);
  for(const [label,value] of [['Condition','PSA 10'],['Grading company','PSA'],['Grade','10'],
    ['Certificate','PSA-1234567'],['Inventory ID','INV-EXACT-COPY']])
    assert.ok(entries.some(row=>row[0]===label&&row[1]===value),label+' is not available in details');
  assert.equal(btn(f.w,'+').disabled,true);f.finish();checks++;
 }
 {
  const f=fixture({status:'APPROVED',store_price_minor:1000,can_refresh_market:true});
  f.run(`renderInventoryCards([${JSON.stringify({...item,status:'APPROVED',store_price_minor:1000,can_refresh_market:true})}]);`);
  const tile=f.w.document.querySelector('.owner-inventory-card');
  assert.match(tile.querySelector('.owner-card-prices').textContent,/£10.00/);
  assert.match(tile.querySelector('.owner-status-pill').textContent,/APPROVED/);
  assert.ok(tile.querySelector('.owner-market-refresh'));
  tile.querySelector('.owner-inventory-details').click();await tick();
  assert.equal(f.w.document.querySelector('.owner-item-dialog').open,true);
  f.finish();checks++;
 }
 {
  const f=fixture();let attempts=0;
  f.setHandler(async(url,options)=>{if(url.endsWith('/copies')){attempts++;if(attempts===1)throw new Error('Connection lost');return {message:'Copy added'};}return {item:{...item,version:attempts?4:3},copies:[item]};});
  await f.open();await click(f.w,'+');await click(f.w,'Confirm additional copy');assert.match(f.w.document.querySelector('.owner-item-message').textContent,/Connection lost/);
  await click(f.w,'+');await click(f.w,'Confirm additional copy');const posts=f.calls.filter(c=>c.url.endsWith('/copies'));
  assert.equal(posts.length,2);assert.equal(posts[0].headers['Idempotency-Key'],posts[1].headers['Idempotency-Key']);assert.equal(posts[0].body,posts[1].body);
  assert.deepEqual(JSON.parse(posts[0].body),{version:3,confirmed:true});f.finish();checks++;
 }
 {
  const f=fixture();await f.open();await click(f.w,'−');assert.equal(f.calls.filter(c=>c.method).length,0);
  assert.match(f.w.document.querySelector('.owner-item-confirmation').textContent,/INV-EXACT-COPY/);await click(f.w,'Withdraw this copy');
  const sent=f.calls.find(c=>c.method);assert.equal(sent.url,`/api/v1/owner/inventory/${id}/withdraw`);assert.deepEqual(JSON.parse(sent.body),{version:3});f.finish();checks++;
 }
 {
  const f=fixture();let resolve;f.setHandler(()=>new Promise(r=>{resolve=r;}));const waiting=f.open();f.run('clearSession()');resolve({item,copies:[item]});await waiting;
  assert.equal(f.w.document.querySelector('dialog').open,false);assert.equal(f.w.document.querySelector('.owner-item-content').textContent,'');f.finish();checks++;
 }
 {
  const f=fixture();let resolve;f.setHandler(()=>new Promise(r=>{resolve=r;}));const waiting=f.open();f.w.DropRateInventory.close();resolve({item,copies:[item]});await waiting;
  assert.equal(f.w.document.querySelector('dialog').open,false);assert.equal(f.w.document.querySelector('.owner-item-content').textContent,'');f.finish();checks++;
 }
 {
  const f=fixture(),calls=[],revoked=[];f.w.URL.createObjectURL=()=> 'blob:safe';f.w.URL.revokeObjectURL=x=>revoked.push(x);
  f.w.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,blob:async()=>new f.w.Blob(['image'],{type:'image/webp'})};};
  const picture=f.w.DropRateInventory.image({...item,image_url:'https://cdn.shopify.com/missing.png'},'owner-card-thumb');f.w.document.body.append(picture);const img=picture.querySelector('img');
  img.dispatchEvent(new f.w.Event('error'));assert.equal(img.src,item.reference_image_url);img.dispatchEvent(new f.w.Event('error'));await tick();assert.equal(img.src,'blob:safe');
  assert.equal(calls.length,1);assert.equal(calls[0].options.headers.Authorization,'Bearer secret-session');img.dispatchEvent(new f.w.Event('load'));assert.deepEqual(revoked,['blob:safe']);assert.equal(picture.querySelector('span').hidden,true);f.finish();checks++;
 }
 {
  const f=fixture({name:'<img src=x onerror=alert(1)>',market_value_minor:null});await f.open();assert.match(f.w.document.querySelector('dialog').textContent,/Value pending/);assert.equal(f.w.document.querySelector('dialog img[src="x"]'),null);f.finish();checks++;
 }
 console.log(`Seller inventory: ${checks} detail, image, approval, sync, quantity, retry and isolation scenarios passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
