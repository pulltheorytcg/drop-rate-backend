const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static'),tick=()=>new Promise(r=>setImmediate(r));
const id='d715b0e9-b3c4-451b-a909-5fa233f8a0e5';
const item={id,catalogue_id:'catalogue',inventory_code:'INV-EXACT-COPY',version:3,status:'DRAFT',sale_intent:'FOR_SALE',product_type:'SEALED',game:'One Piece',language:'Japanese',seal_status:'SEALED',name:"Booster Pack: World's Strongest Warriors [OP-17]",set_name:'OP-17',market_value_minor:866,store_price_minor:null,reference_image_url:'https://www.onepiece-cardgame.com/products/pack.webp',reference_image_path:`/api/v1/owner/inventory/${id}/reference-image`,approval_blockers:['Drop Rate intake review','An approved listing photo'],shopify_sync_enabled:true};
function fixture(override={}) {
 const dom=new JSDOM(fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script[^>]*><\/script>/g,''),{url:'https://example.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,run=s=>vm.runInContext(s,dom.getInternalVMContext()),calls=[];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.scrollTo=()=>{};w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};w.fetch=async()=>({ok:true,json:async()=>({}),blob:async()=>new w.Blob(['image'],{type:'image/webp'})});
 run(fs.readFileSync(path.join(base,'hub-session.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'reference-value-display.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'inventory-groups.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'owner-inventory.js'),'utf8'));
 run(fs.readFileSync(path.join(base,'owner-portal.js'),'utf8').replace(/\ninitialise\(\);\s*$/,''));
 run(`window.testLoadInventory=loadOwnerInventory;window.testLoadChannels=loadOwnerChannels;state.session={access_token:'secret-session',user:{id:'seller-a'}};loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=loadOwnerInventory=async()=>{};`);
 let current={...item,...override},handler;
 w.testRequest=async(url,options={})=>{calls.push({url,...options});if(handler)return handler(url,options);return {item:current,copies:[current]};};run('apiRequest=window.testRequest');
 return {w,run,calls,setHandler:f=>{handler=f;},setItem:x=>{current={...current,...x};},open:()=>w.DropRateInventory.open(current),finish:()=>w.close()};
}
function btn(w,text){return [...w.document.querySelectorAll('button')].find(b=>b.textContent===text);}
async function click(w,text){const b=btn(w,text);assert.ok(b,`Missing ${text}`);assert.equal(b.disabled,false);b.click();await tick();await tick();}
(async()=>{
 let checks=0;
 // Real dispatched events lose currentTarget before the debounce fires.
 for (const channel of [false,true]) {
  const f=fixture();f.run('loadOwnerInventory=window.testLoadInventory;loadOwnerChannels=window.testLoadChannels;');
  f.setHandler(async()=>({total:1,items:[{...item,name:'Borgos'}],channels:[]}));
  const input=f.w.document.querySelector(channel?'#owner-channels-search':'#owner-inventory-search');
  input.value='Old search';input.dispatchEvent(new f.w.Event('input',{bubbles:true}));
  input.value='  Borgos  ';const event=new f.w.Event('input',{bubbles:true});input.dispatchEvent(event);
  assert.equal(event.currentTarget,null);assert.equal(f.calls.length,0);
  await new Promise(resolve=>setTimeout(resolve,380));
  assert.equal(f.calls.length,1);assert.equal(new URL(f.calls[0].url,'https://example.test').searchParams.get('search'),'Borgos');
  assert.match(f.w.document.querySelector(channel?'#owner-channels-body':'#owner-inventory-grid').textContent,/Borgos/);
  f.finish();checks++;
 }
 // Condition is part of the group; sale intent is per physical copy.
 {
  const raw={...item,product_type:'CARD',seal_status:null,status:'APPROVED',condition:'Near Mint',store_price_minor:1000};
  const personal={...raw,id:'personal',sale_intent:'PERSONAL_COLLECTION',store_price_minor:9900};
  const played={...raw,id:'played',condition:'Lightly Played',store_price_minor:800};
  const f=fixture();const originals=JSON.stringify([personal,raw,played]);
  f.run(`const groups=ownerInventoryDisplayGroups(${originals});renderInventoryCards(groups);renderInventoryRows(groups);`);
  const cards=[...f.w.document.querySelectorAll('.owner-inventory-card')];
  assert.equal(cards.length,2);assert.match(cards[0].textContent,/Near Mint/);assert.match(cards[1].textContent,/Lightly Played/);
  assert.equal(cards[0].querySelector('.owner-card-quantity').textContent,'×2');
  assert.equal(cards[0].querySelector('.owner-status-pill').textContent,'Mixed availability');
  assert.match(cards[0].querySelector('.owner-status-pill').title,/1 in collection.*1 ready to sell/);
  assert.match(cards[0].textContent,/£10.00/);assert.doesNotMatch(cards[0].textContent,/£99.00/);
  assert.equal(f.w.document.querySelector('#owner-inventory-body tr td:last-child').textContent,'£10.00');
  assert.equal(JSON.stringify([personal,raw,played]),originals);f.finish();checks++;
 }
 {
  const f=fixture();f.run(`renderOwnerChannelSummary({channels:[{code:'EBAY',connected:true,connection_status:'READY',sync_enabled:false,sync_unavailable_reason:'Consignor eBay publishing is not enabled yet'}]});
   renderOwnerChannelsRows([${JSON.stringify({...item,product_type:'CARD',inventory_id:id,store_value_minor:100,recommended_retail_minor:100})}],[]);`);
  assert.equal(f.w.document.querySelector('#owner-channel-ebay-status').textContent,'Connected · publishing unavailable');
  assert.match(f.w.document.querySelector('#owner-channel-ebay-note').textContent,/Consignor/);
  assert.equal(f.w.document.querySelector('#owner-channels-body tr td:nth-child(5)').textContent,'Not set');
  assert.ok(btn(f.w,'Prepare for eBay'));assert.equal(f.calls.length,0);f.finish();checks++;
 }
 {
  const personal={...item,inventory_status:'APPROVED',sale_intent:'PERSONAL_COLLECTION',shopify_state:'PUBLISHED',shopify_test_mode:false,ebay_state:'LIVE'};
  const f=fixture();f.run(`renderOwnerChannelSummary({channels:[{code:'SHOPIFY',states:[{state:'PUBLISHED',count:1},{state:'REVIEW_REQUIRED',count:1}]},{code:'EBAY',states:[{state:'ERROR',count:2},{state:'REVIEW_REQUIRED',count:1}]}]});
    renderOwnerChannelsRows(${JSON.stringify([personal,{...personal,id:'test',shopify_test_mode:true},{...personal,id:'sale',sale_intent:'FOR_SALE'}])},[]);`);
  const rows=f.w.document.querySelectorAll('#owner-channels-body tr');
  assert.equal(rows[0].querySelector('td:nth-child(2) .owner-status-pill').textContent,'Listing needs review');
  assert.equal(rows[0].querySelector('td:nth-child(3) .owner-status-pill').textContent,'Listing needs review');
  assert.equal(rows[1].querySelector('td:nth-child(2) .owner-status-pill').textContent,'Test listing');
  assert.equal(rows[2].querySelector('td:nth-child(2) .owner-status-pill').textContent,'PUBLISHED');
  assert.equal(f.w.document.querySelector('#owner-channel-shopify-live').textContent,'1');
  assert.equal(f.w.document.querySelector('#owner-channel-shopify-errors').textContent,'1');
  assert.equal(f.w.document.querySelector('#owner-channel-ebay-errors').textContent,'3');
  assert.equal(f.calls.length,0);f.finish();checks++;
 }
 {
  for (const fails of [false,true]) {
   const f=fixture();const personal={...item,inventory_id:id,inventory_status:'APPROVED',sale_intent:'PERSONAL_COLLECTION',shopify_state:'PUBLISHED',shopify_test_mode:false};
   f.run(`renderOwnerChannelsRows([${JSON.stringify(personal)}],[]);`);
   f.setHandler(async()=>{if(fails)throw new Error('Channel withdrawal needs retry');return {action_required:false};});
   await click(f.w,'Retry removal');
   assert.equal(f.calls.length,1);assert.equal(f.calls[0].url,`/api/v1/inventory/${id}/sale-intent`);
   assert.deepEqual(JSON.parse(f.calls[0].body),{version:3,sale_intent:'PERSONAL_COLLECTION'});
   if(fails){assert.equal(btn(f.w,'Retry removal').disabled,false);assert.match(f.w.document.querySelector('#owner-channels-message').textContent,/needs retry/);}
   else assert.match(f.w.document.querySelector('#owner-channels-message').textContent,/Other sellable copies remain available/);
   f.finish();checks++;
  }
 }
 {
  const preparation={completed:1,scope_blocker:'Consignor eBay publishing is not enabled yet',checks:[
   {code:'language',label:'Language recorded',complete:true},
   {code:'photos',label:'Front and back photos approved',complete:false,next_step:'Drop Rate needs photos of this physical copy'}]};
  const f=fixture({product_type:'CARD',ebay_preparation:preparation});
  await f.w.DropRateInventory.open(item,{prepareEbay:true});
  assert.equal(f.w.document.querySelector('.owner-item-selling').open,true);
  const checklist=f.w.document.querySelector('.owner-ebay-preparation');
  assert.equal(f.w.document.activeElement,checklist);assert.match(checklist.textContent,/1 of 2 preparation steps complete/);
  assert.equal(checklist.querySelectorAll('.complete').length,1);assert.match(checklist.textContent,/physical copy/);
  assert.equal(f.calls.filter(c=>c.method).length,0);f.finish();checks++;
 }
 {
  const f=fixture({seller_approval_available:true,approval_blockers:[],image_url:'https://cdn.shopify.com/op17.webp'});await f.open();
  assert.match(f.w.document.querySelector('dialog').textContent,/Your stock stays with you/);
  assert.doesNotMatch(f.w.document.querySelector('dialog').textContent,/requests Drop Rate review/);
  f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value='10.00';await click(f.w,'List on Shopify');
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
  await tick();assert.equal(f.w.document.querySelector('.owner-card-thumb img').src,'blob:fixture');
  const tile=f.w.document.querySelector('.owner-inventory-card');
  assert.equal(tile.querySelector('.owner-card-meta'),null,'Quick inventory tiles must not expose detailed metadata');
  assert.equal(tile.querySelector('.owner-card-title strong').textContent,item.name);
  assert.match(tile.querySelector('.owner-status-pill').textContent,/Not listed/);
  assert.match(tile.querySelector('.owner-card-prices').textContent,/£8.66/);
  assert.match(tile.querySelector('.owner-card-prices').textContent,/Selling price/);
  assert.match(tile.querySelector('.owner-card-prices').textContent,/Not set/);
  assert.match(f.w.document.querySelector('#owner-inventory-body tr td:last-child').textContent,/Not set/);
  assert.doesNotMatch(tile.textContent,/INV-EXACT-COPY|Seal|Language|Type|Inventory ID/);
  assert.equal(tile.querySelector('.owner-inventory-details'),null,'No redundant Manage button');
  const openTile=tile.querySelector('.owner-card-open-overlay');
  assert.ok(openTile,'Whole card needs an accessible details button');
  assert.match(openTile.getAttribute('aria-label'),/View details for/);
  assert.equal(tile.querySelectorAll('button').length,1,'No duplicate image/Manage controls on a static tile');
  const inventoryRow=f.w.document.querySelector('#owner-inventory-body tr');
  assert.equal(inventoryRow.children.length,4,'List view should have only essential columns');
  assert.doesNotMatch(inventoryRow.textContent,/INV-EXACT-COPY|Japanese|\\bSeal\\b|\\bLanguage\\b/);
  assert.match(inventoryRow.textContent,/£8.66/);
  f.w.document.querySelector('.owner-card-open-overlay').click();await tick();
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
  assert.match(f.w.document.querySelector('dialog').textContent,/We need to check this item/);assert.equal(btn(f.w,'Check & sync to Shopify'),undefined);
  assert.equal(f.calls.filter(c=>c.method).length,0);f.finish();checks++;
 }
 // The screenshot showed a giant "Last known 08/10/2026" block. A
 // two-column card should show the GBP figure, never that dated caption.
 {
  const old={...item,reference_value:{status:'STALE',last_known_minor:866,
    checked_at:'2026-10-08T12:00:00Z'},store_price_minor:1000};
  const f=fixture(old);f.run(`renderInventoryCards([${JSON.stringify(old)}]);renderInventoryRows([${JSON.stringify(old)}]);`);
  const tile=f.w.document.querySelector('.owner-inventory-card');
  const prices=tile.querySelector('.owner-card-prices');
  assert.match(prices.textContent,/£8.66/);
  assert.ok(!prices.textContent.includes("Last known")&&!prices.textContent.includes("08/10/2026"));
  assert.match(prices.querySelector('.owner-card-historical-label').textContent,/Historical value/);
  const tableMarket=f.w.document.querySelector('#owner-inventory-body tr td:nth-child(3)');
  assert.ok(tableMarket,'List view must retain a separate market value column');
  assert.match(tableMarket.textContent,/£8.66/);
  assert.ok(!tableMarket.textContent.includes("Last known")&&!tableMarket.textContent.includes("08/10/2026"));
  assert.match(tableMarket.querySelector('.owner-table-historical-label').textContent,/Historical value/);
  assert.equal(tile.querySelector('.owner-inventory-details'),null);
  tile.querySelector('.owner-card-open-overlay').click();await tick();
  assert.ok(f.w.document.querySelector('.owner-item-dialog .owner-item-values').textContent.includes("Last known 08/10/2026"));
  f.finish();checks++;
 }
 // A stale near-mint comparison for an unfinished copy keeps its history badge.
 {
  const old={...item,market_value_minor:null,condition:null,product_type:'CARD',seal_status:null,
    reference_value:{status:'NEEDS_DETAILS',market_value_minor:null},
    catalogue_reference:{status:'STALE',last_known_minor:800,last_known_high_minor:1200,
      checked_at:'2026-10-14T12:00:00Z',physical_valuation_eligible:false}};
  const f=fixture(old);f.run(`renderInventoryCards([${JSON.stringify(old)}]);renderInventoryRows([${JSON.stringify(old)}]);`);
  assert.equal(f.w.DropRateReferenceValue.isHistorical(old),true);
  assert.match(f.w.document.querySelector('.owner-card-prices').textContent,/Value: £8.00/);
  assert.match(f.w.document.querySelector('.owner-card-historical-label').textContent,/Historical value/);
  assert.match(f.w.document.querySelector('.owner-table-historical-label').textContent,/Historical value/);
  f.w.document.querySelector('.owner-card-open-overlay').click();await tick();
  assert.match(f.w.document.querySelector('.owner-item-values').textContent,/Value: £8.00/);
  assert.match(f.w.document.querySelector('.owner-item-values').textContent,/Last known 14\/10\/2026/);
  assert.equal(old.market_value_minor,null);f.finish();checks++;
 }
 // Clicking a refresh button must never open the detail sheet, even when it
 // is laid above the stretched tile button.
 {
  const f=fixture({...item,can_refresh_market:true});
  let resolveRefresh;
  f.setHandler((url,options)=>new Promise((resolve,reject)=>{resolveRefresh=reject;}));
  f.run(`renderInventoryCards([${JSON.stringify({...item,can_refresh_market:true})}]);`);
  const tile=f.w.document.querySelector('.owner-inventory-card');
  assert.ok(tile.querySelector('.owner-market-refresh'));
  tile.querySelector('.owner-market-refresh').click();await tick();
  assert.equal(f.w.document.querySelector('.owner-item-dialog'),null);
  assert.equal(f.calls.length,1);
  resolveRefresh(new Error("Provider unavailable"));await tick();await tick();
  f.finish();checks++;
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
  f.w.document.querySelector('.owner-card-open-overlay').click();await tick();
  assert.match(f.w.document.querySelector('.owner-item-quantity').textContent,/2/);
  assert.equal(f.w.document.querySelector('[aria-label="Choose inventory copy"]').options.length,2);
  assert.equal(btn(f.w,'Sync to eBay'),undefined,'Unsupported eBay sealed publishing must not show a misleading action');
  assert.equal(f.w.document.querySelector('.owner-item-channel-ebay .owner-item-channel-availability').textContent,'Not available yet');
  assert.match(f.w.document.querySelector('.owner-item-channel-ebay').textContent,/Sealed packs aren't supported yet/);
  let opened=null;f.w.open=(url,target,options)=>{opened={url,target,options};};
  assert.equal(btn(f.w,'Set up'),undefined,'Seller must not be sent to Drop Rate Shopify');
  assert.equal(f.w.document.querySelector('.owner-item-channel-whatnot button'),null);
  assert.match(f.w.document.querySelector('.owner-item-channel-whatnot').textContent,/Not connected in Drop Rate — publishing unavailable/);
  assert.equal(f.w.document.querySelector('.owner-item-channel-whatnot .owner-item-channel-availability').textContent,'Not available yet');
  assert.equal(opened,null,'No unapproved Whatnot OAuth or Shopify install should open');
  assert.equal(f.w.document.querySelector('.owner-item-channel-shopify img').src,'https://upload.wikimedia.org/wikipedia/commons/0/0e/Shopify_logo_2018.svg');
  assert.equal(f.w.document.querySelector('.owner-item-channel-ebay img').src,'https://upload.wikimedia.org/wikipedia/commons/1/1b/EBay_logo.svg');
  assert.equal(f.w.document.querySelector('.owner-item-channel-whatnot img').src,'https://upload.wikimedia.org/wikipedia/commons/9/91/Whatnot_Logo_2025.svg');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0,'Channel setup must never claim a listing published');
  f.finish();checks++;
 }
 // Strict grouping invariants: cross-condition, language, type, ownership
 // and graded identities must never turn into an interchangeable pack pool.
 {
  const f=fixture();
  const base={...item,status:'APPROVED',store_price_minor:1000,market_value_minor:866,
    sale_intent:'FOR_SALE'};
  for(const variant of [
    {...base,id:'other',language:'English'},
    {...base,id:'other',seal_status:'UNSEALED'},
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
 // Raw duplicates include unknown-condition, personal, pending and approved copies.
 // Different exact physical states and all slabs remain individually visible.
 {
  const f=fixture();
  const raw={...item,product_type:'CARD',seal_status:null,condition:null,language:'English',
    market_value_minor:null,reference_value:{status:'NEEDS_DETAILS'},
    catalogue_reference:{status:'CONDITION_REFERENCE',market_value_minor:132,label:'Near-mint reference'}};
  const copies=[raw,{...raw,id:'copy-2',status:'APPROVED',sale_intent:'PERSONAL_COLLECTION',store_price_minor:200}];
  const extras=[{...raw,id:'nm',condition:'Near Mint'},
    {...raw,id:'jp',language:'Japanese'}, {...raw,id:'parallel',catalogue_id:'other-printing'},
    {...raw,id:'slab-1',grading_company:'PSA',grade:'10'}, {...raw,id:'slab-2',grading_company:'PSA',grade:'10'},
    {...raw,id:'certificate-1',certificate_number:'one'}, {...raw,id:'certificate-2',certificate_number:'two'},
    {...raw,id:'sold',status:'SOLD'}, {...raw,id:'foreign',owner_id:'other-owner'}];
  f.run(`renderInventoryCards(ownerInventoryDisplayGroups(${JSON.stringify([...copies,...extras])}));renderInventoryRows(ownerInventoryDisplayGroups(${JSON.stringify([...copies,...extras])}));`);
  assert.equal(f.w.document.querySelectorAll('.owner-inventory-card').length,10);
  assert.equal(f.w.document.querySelectorAll('#owner-inventory-body tr').length,10);
  const tile=f.w.document.querySelector('.owner-inventory-card');
  assert.equal(tile.querySelector('.owner-card-quantity').textContent,'×2');
  assert.match(tile.textContent,/Mixed availability/);assert.match(tile.textContent,/£1.32/);
  assert.match(tile.textContent,/Guide estimate · each/);assert.match(tile.textContent,/Selling priceNot set/);
  assert.doesNotMatch(tile.textContent,/Condition not specified/);
  assert.equal(raw.market_value_minor,null,'Grouping never writes a value into the physical copy');
  assert.equal(f.calls.filter(call=>call.method).length,0);
  f.finish();checks++;
 }
 for(const value of ['', '0', '0.99', '1.001']){
  const f=fixture();await f.open();f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value=value;
  await click(f.w,'Save selling price');assert.equal(f.calls.filter(c=>c.method).length,0);assert.match(f.w.document.querySelector('.owner-item-message').textContent,/at least £1/);f.finish();checks++;
 }
 for(const action of ['Save selling price','Request listing review']){
  const f=fixture();await f.open();f.w.document.querySelector('[aria-label="Your selling price in pounds"]').value='12.34';
  await click(f.w,action);const sent=f.calls.find(c=>c.method);assert.deepEqual(JSON.parse(sent.body),{version:3,store_price_minor:1234});
  assert.ok(sent.url.endsWith(action.startsWith('Save')?'/selling-price':'/approval-request'));assert.equal(sent.body.includes('identity'),false);f.finish();checks++;
 }
 {
  const f=fixture({status:'APPROVED',store_price_minor:1000});await f.open();await click(f.w,'Check & sync to Shopify');
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
  assert.equal(modal.querySelector('.owner-item-selling summary').textContent,'Manage listing');
  assert.equal(modal.querySelector('.owner-item-selling').open,false);
  assert.equal(btn(f.w,'List on Shopify'),undefined);
  assert.equal(btn(f.w,'Check & sync to Shopify'),undefined);
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
  const f=fixture(override);await f.open();assert.equal(btn(f.w,'Check & sync to Shopify'),undefined);
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
  assert.match(tile.querySelector('.owner-status-pill').textContent,/Ready to sell/);
  assert.ok(tile.querySelector('.owner-market-refresh'));
  tile.querySelector('.owner-card-open-overlay').click();await tick();
  assert.equal(f.w.document.querySelector('.owner-item-dialog').open,true);
  f.finish();checks++;
 }
 // A saved quantity is not a fake stepper: arrows preview ±1, cancel/undo
 // restores the saved count, and the owner-scoped POST happens only on confirm.
 {
  const first={...item,status:'APPROVED',sale_intent:'FOR_SALE',store_price_minor:1000,
    shopify_state:'PUBLISHED',seller_approval_available:true};
  const second={...first,id:'55fe97fc-7bfa-4a73-a269-664ec56d3004',
    inventory_code:'INV-SECOND-COPY'};
  const draft={...first,id:'22222222-3333-4444-8555-666666666666',
    inventory_code:'INV-NEW-DRAFT',status:'DRAFT',sale_intent:'PERSONAL_COLLECTION'};
  const f=fixture(first);
  let copies=[first,second],posted=0;
  f.setHandler(async(url,options)=>{
    if(url.endsWith('/copies')){
      posted++;copies=[...copies,draft];
      return {message:'One copy added. Review and approve it separately before selling.'};
    }
    return {item:first,copies};
  });
  await f.open();
  const counter=()=>f.w.document.querySelector('.owner-item-quantity-value');
  assert.equal(counter().textContent,'2');
  assert.equal(counter().getAttribute('aria-label'),'Saved quantity 2');
  await click(f.w,'+');
  assert.equal(counter().textContent,'3','+ must immediately show proposed quantity');
  assert.equal(counter().getAttribute('aria-label'),'Proposed quantity 3, not saved');
  assert.match(f.w.document.querySelector('.owner-item-quantity-feedback').textContent,/Not saved: 2 → 3/);
  assert.equal(btn(f.w,'+').disabled,true,'A second unsaved request must not silently create another copy');
  assert.equal(f.calls.filter(c=>c.method==='POST').length,0,'Preview must never mutate stock');
  await click(f.w,'−');
  assert.equal(counter().textContent,'2','The opposite arrow must undo the preview');
  assert.equal(f.w.document.querySelector('.owner-item-confirmation').textContent,'');
  await click(f.w,'−');
  assert.equal(counter().textContent,'1','− must immediately show proposed quantity');
  assert.match(f.w.document.querySelector('.owner-item-confirmation').textContent,/INV-EXACT-COPY/);
  assert.equal(f.calls.filter(c=>c.method==='POST').length,0);
  await click(f.w,'Cancel change');
  assert.equal(counter().textContent,'2');
  assert.equal(counter().getAttribute('aria-label'),'Saved quantity 2');
  await click(f.w,'+');
  assert.equal(counter().textContent,'3');
  await click(f.w,'Confirm additional copy');
  assert.equal(posted,1,'Exactly one extra physical record should be requested');
  assert.equal(counter().textContent,'3','Successful save must reflect server re-read, not optimistic state');
  assert.equal(counter().getAttribute('aria-label'),'Saved quantity 3');
  assert.match(f.w.document.querySelector('.owner-item-quantity-breakdown').textContent,/2 approved for sale · 1 awaiting approval/);
  assert.match(f.w.document.querySelector('.owner-item-message').textContent,/One copy added to your collection/);
  assert.equal(f.w.document.querySelector('.owner-item-confirmation').textContent,'');
  f.finish();checks++;
 }
 // Withdraw the selected physical item, not the entire grouped Shopify offer.
 {
  const first={...item,status:'APPROVED',sale_intent:'FOR_SALE',store_price_minor:1000,
    shopify_state:'PUBLISHED'};
  const second={...first,id:'55fe97fc-7bfa-4a73-a269-664ec56d3004',
    inventory_code:'INV-SECOND-COPY'};
  const f=fixture(first);let withdrawn=false;
  f.setHandler(async(url,options)=>{
    if(url.endsWith('/withdraw')){
      withdrawn=true;
      assert.deepEqual(JSON.parse(options.body),{version:3});
      return {message:'Copy withdrawn. Its history is retained.'};
    }
    return {item:withdrawn?{...first,status:'WITHDRAWN'}:first,
      copies:withdrawn?[second]:[first,second]};
  });
  await f.open();await click(f.w,'−');
  assert.equal(f.w.document.querySelector('.owner-item-quantity-value').textContent,'1');
  assert.equal(withdrawn,false,'Preview must not withdraw stock');
  await click(f.w,'Withdraw this copy');
  assert.equal(withdrawn,true);
  assert.equal(f.w.document.querySelector('.owner-item-quantity-value').textContent,'1');
  assert.equal(f.w.document.querySelector('.owner-item-quantity-value').getAttribute('aria-label'),'Saved quantity 1');
  assert.match(f.w.document.querySelector('.owner-item-message').textContent,/Copy withdrawn/);
  assert.equal(f.calls.filter(c=>c.method==='POST').length,1);
  f.finish();checks++;
 }
 {
  const f=fixture();let attempts=0;
  f.setHandler(async(url,options)=>{if(url.endsWith('/copies')){attempts++;if(attempts===1)throw new Error('Connection lost');return {message:'Copy added'};}return {item:{...item,version:attempts?4:3},copies:[item]};});
  await f.open();await click(f.w,'+');assert.equal(f.w.document.querySelector('.owner-item-quantity-value').textContent,'2');await click(f.w,'Confirm additional copy');assert.match(f.w.document.querySelector('.owner-item-message').textContent,/Connection lost/);assert.equal(f.w.document.querySelector('.owner-item-quantity-value').textContent,'1','Failed mutation must revert to saved stock');
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
  await tick();img.dispatchEvent(new f.w.Event('error'));await tick();assert.equal(img.src,'blob:safe');assert.equal(calls[0].url,`/api/v1/inventory/${id}/image`);
  assert.equal(calls.length,1);assert.equal(calls[0].options.headers.Authorization,'Bearer secret-session');img.dispatchEvent(new f.w.Event('load'));assert.deepEqual(revoked,['blob:safe']);assert.equal(picture.querySelector('span').hidden,true);f.finish();checks++;
 }
 {
  const f=fixture({name:'<img src=x onerror=alert(1)>',market_value_minor:null});await f.open();assert.match(f.w.document.querySelector('dialog').textContent,/Value unavailable/);assert.equal(f.w.document.querySelector('dialog img[src="x"]'),null);f.finish();checks++;
 }
 console.log(`Seller inventory: ${checks} detail, image, approval, sync, quantity, retry and isolation scenarios passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
