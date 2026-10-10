// Render the actual seller page/assets with isolated API fixtures; never mutate live stock.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=path.resolve(__dirname,'../../backend/app/static'),out='/tmp/inventory-layout';
const artwork='https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp';
const item={id:'d715b0e9-b3c4-451b-a909-5fa233f8a0e5',catalogue_id:'verified-op17-catalogue',inventory_code:'INV-D715B0E9B3C4451BA9095FA233F8A0E5',version:3,status:'DRAFT',sale_intent:'FOR_SALE',product_type:'SEALED',game:'One Piece',language:'Japanese',seal_status:'SEALED',name:"Booster Pack: World's Strongest Warriors [OP-17]",set_name:"World's Strongest Warriors [OP-17]",market_value_minor:866,store_price_minor:null,reference_image_url:artwork,approval_blockers:['Drop Rate intake review','A selling price of at least £1','An approved listing photo'],shopify_sync_enabled:true};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const response=await fetch(artwork);assert.equal(response.ok,true,'Official pack image unavailable');const pack=Buffer.from(await response.arrayBuffer());
 const browser=await chromium.launch({headless:true});
 try{
  for(const viewport of [{width:430,height:932},{width:1440,height:1000}]){
   const page=await browser.newPage({viewport,deviceScaleFactor:1}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.href===artwork)return route.fulfill({body:pack,contentType:'image/webp'});
    if(u.hostname==='cdn.shopify.com')return route.fulfill({path:path.join(base,'brand-assets/drop-rate-seller-hub.png'),contentType:'image/png'});
    if(u.hostname==='upload.wikimedia.org')return route.fulfill({
      body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 130 36"><rect width="130" height="36" fill="none"/><path fill="#174b73" d="M10 6h110v24H10z"/></svg>',
      contentType:'image/svg+xml'
    });
    if(u.pathname==='/owner')return route.fulfill({body:fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script[^>]*><\/script>/g,''),contentType:'text/html'});
    if(u.pathname.startsWith('/assets/')){const file=path.resolve(base,u.pathname.slice(8));assert.ok(file.startsWith(base+'/'));return route.fulfill({path:file});}
    return route.abort();
   });
   await page.goto('http://127.0.0.1:4178/owner');
   for(const name of ['hub-session.js','owner-inventory.js','owner-portal.js'])await page.addScriptTag({content:fs.readFileSync(path.join(base,name),'utf8').replace(/\ninitialise\(\);\s*$/,'')});
   await page.evaluate(item=>{
    window.fixtureItem=item;
    state.session={access_token:'isolated-fixture',user:{id:'fixture-seller'}};
    apiRequest=async()=>({item:window.fixtureItem,copies:[window.fixtureItem]});
    loadOwnerInventory=loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=async()=>{};
    document.body.classList.remove('hub-restoring');
    byId('owner-auth-view').classList.add('hidden');byId('owner-portal-view').classList.remove('hidden');
    activateOwnerView('inventory',false);state.inventory.total=1;byId('owner-inventory-total-label').textContent='1';renderInventoryCards([item]);renderInventoryRows([item]);renderInventoryPagination();
   },item);
   await page.locator('.owner-card-thumb img').waitFor();
   await page.waitForFunction(()=>document.querySelector('.owner-card-thumb img')?.naturalWidth>0);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Inventory overflows viewport');
   assert.equal(await page.locator('.owner-page-header').isVisible(),false,'Redundant inventory heading still occupies space');
   assert.equal(await page.locator('#owner-view-inventory .owner-section-header h2').innerText(),'Inventory');
   assert.equal(await page.locator('#owner-view-inventory .owner-section-header p').innerText(),
     'Open an item to manage its copies and selling channels.');
   const top=await page.locator('#owner-view-inventory').boundingBox();
   assert.ok(top && top.y<250,'Inventory layout still wastes height above search and filters');
   const tile=page.locator('.owner-inventory-card');
   assert.equal(await tile.locator('.owner-card-meta').count(),0,'Inventory grid still shows redundant specifications');
   const tileText=await tile.innerText();
   assert.doesNotMatch(tileText,/INV-D715B0E9|\bLANGUAGE\b|\bSEAL\b|\bTYPE\b|\bGAME\b/i);
   assert.match(tileText,/Market value/);assert.match(tileText,/£8.66/);
   assert.match(tileText,/View details & manage/);
   const cardBox=await tile.boundingBox();
   assert.ok(cardBox&&cardBox.height<425,'Inventory tile still has an oversized metadata layout');
   await page.screenshot({path:path.join(out,`inventory-${viewport.width}.png`),fullPage:true});
   await page.locator('.owner-card-image-wrap').click();await page.getByRole('dialog').waitFor();
   await page.getByRole('heading',{name:'Selling price',exact:true}).waitFor();
   const facts=page.locator('.owner-item-facts');
   await facts.waitFor();
   const detail=await facts.innerText();
   for(const label of ['Game','One Piece','Language','Japanese','Seal','Sealed','Inventory ID',item.inventory_code])
    assert.ok(detail.includes(label),'Missing item detail: '+label);
   assert.equal(await page.getByRole('button',{name:'Sync to Shopify',exact:true}).count(),0);
   assert.equal(await page.locator('.owner-item-channel-logo').count(),3);
   const channelRects=await page.locator('.owner-item-channel-visual').evaluateAll(nodes=>
     nodes.map(n=>({height:Math.round(n.getBoundingClientRect().height),
                   background:getComputedStyle(n).backgroundColor})));
   assert.equal(new Set(channelRects.map(r=>r.height)).size,1,'Brandmark display frames must align');
   assert.ok(channelRects.every(r=>r.background==='rgba(0, 0, 0, 0)'),'Brandmarks must be on transparent image frames');
   assert.equal(await page.locator('.owner-item-channel-ebay button').count(),0);
   assert.match(await page.locator('.owner-item-channel-ebay').innerText(),/Not available yet/);
   const box=await page.getByRole('dialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=viewport.width+1);
   assert.equal(await page.getByRole('dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),true,'Details overflow');
   await page.screenshot({path:path.join(out,`details-${viewport.width}.png`)});
   const counter=page.locator('.owner-item-quantity-value');
   assert.equal(await counter.innerText(),'1','Fixture starts with one saved physical copy');
   await page.getByRole('button',{name:'Increase quantity by one',exact:true}).click();
   assert.equal(await counter.innerText(),'2','Mobile/desktop + must preview saved quantity plus one');
   assert.equal(await counter.getAttribute('aria-label'),'Proposed quantity 2, not saved');
   await page.getByRole('button',{name:'Confirm additional copy',exact:true}).waitFor();
   await page.screenshot({path:path.join(out,`quantity-${viewport.width}.png`)});
   await page.getByRole('button',{name:'Cancel change',exact:true}).click();
   assert.equal(await counter.innerText(),'1','Cancel must restore stored quantity');
   await page.getByRole('button',{name:'Decrease quantity by withdrawing this copy',exact:true}).click();
   assert.equal(await counter.innerText(),'0','Mobile/desktop − must preview saved quantity minus one');
   assert.equal(await page.getByRole('button',{name:'Withdraw this copy',exact:true}).count(),1);
   await page.getByRole('button',{name:'Cancel change',exact:true}).click();
   assert.equal(await counter.innerText(),'1');
   await page.getByRole('button',{name:'Close item details',exact:true}).click();
   await page.evaluate(existing=>{window.fixtureItem={...existing,status:'APPROVED',
       sale_intent:'FOR_SALE',shopify_state:'PUBLISHED',seller_approval_available:true,
       store_price_minor:1000,is_consignment:true};},item);
   await page.locator('.owner-inventory-details').click();
   await page.getByRole('heading',{name:'Selling price',exact:true}).waitFor();
   assert.equal(await page.getByRole('button',{name:'Approve for Shopify'}).count(),0);
   assert.equal(await page.getByRole('button',{name:'Sync to Shopify'}).count(),0);
   assert.match(await page.locator('.owner-item-channel-shopify').innerText(),/Published/);
   await page.screenshot({path:path.join(out,`channels-published-${viewport.width}.png`)});
   await page.getByRole('button',{name:'Close item details',exact:true}).click();
   await page.getByRole('button',{name:'List view',exact:true}).click();
   const headings=await page.locator('#owner-inventory-table-wrap thead th').allTextContents();
   assert.deepEqual(headings,['Product','Status','Market value','Store / recommended']);
   assert.equal(await page.locator('#owner-inventory-body tr:first-child td').count(),4);
   assert.doesNotMatch(await page.locator('#owner-inventory-body').innerText(),/INV-D715B0E9|Japanese/);
   await page.locator('.owner-inventory-open').click();await page.getByRole('heading',{name:'Selling price',exact:true}).waitFor();
   await page.getByRole('button',{name:'Close item details',exact:true}).click();
   await page.getByRole('button',{name:'Grid view',exact:true}).click();
   await page.evaluate(original=>{
    const one={...original,status:'APPROVED',sale_intent:'FOR_SALE',store_price_minor:1000,market_value_minor:866,is_consignment:true};
    const two={...one,id:'55fe97fc-7bfa-4a73-a269-664ec56d3004',
      inventory_code:'INV-55FE97FC7BFA4A73A269664EC56D3004',
      market_value_minor:null,can_refresh_market:true};
    window.fixtureItem=one;
    renderInventoryCards(ownerInventoryDisplayGroups([one,two]));
    renderInventoryRows(ownerInventoryDisplayGroups([one,two]));
   },item);
   assert.equal(await page.locator('.owner-inventory-card').count(),1);
   assert.equal(await page.locator('.owner-card-quantity').innerText(),'×2');
   assert.match(await page.locator('.owner-card-prices').innerText(),/1\/2 copies valued/);
   assert.match(await page.locator('.owner-card-prices').innerText(),/£10.00/);
   const groupedBox=await page.locator('.owner-inventory-card').boundingBox();
   assert.ok(groupedBox&&groupedBox.height<425);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Grouped inventory overflows viewport');
   await page.screenshot({path:path.join(out,`inventory-grouped-${viewport.width}.png`),fullPage:true});

   // Genuine Chromium tap: Scan launches the camera modal and calls
   // getUserMedia immediately. Keep permission unresolved to prove the UI
   // does not wait on camera approval or a recognition API response.
   for(const name of ['scanner-flow.js','owner-recognition.js']){
    await page.addScriptTag({content:fs.readFileSync(path.join(base,name),'utf8')});
   }
   await page.evaluate(()=>{
     window.__cameraRequests=[];
     const pending=new Promise(()=>{});
     Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{
       getUserMedia:constraints=>{window.__cameraRequests.push(constraints);return pending;}
     }});
     apiRequest=async(url)=>url==='/api/v1/recognition/status'
       ?{configured:true,vision_model:'isolated-test-vision'}
       :url==='/api/v1/grading-certificates/status'?{configured:true}
       :{item:window.fixtureItem,copies:[window.fixtureItem]};
   });
   await page.locator('.owner-nav-item[data-owner-view="scan"]').click();
   await page.locator('.dr-scanner').waitFor();
   assert.equal(await page.locator('.dr-scanner').evaluate(element=>element.open),true);
   assert.equal(await page.evaluate(()=>window.__cameraRequests.length),1,
      'Scan navigation did not immediately request the live camera');
   assert.equal(await page.evaluate(()=>window.__cameraRequests[0].video.facingMode.ideal),'environment');
   assert.match(await page.locator('.dr-scan-status').innerText(),/Opening camera/);
   await page.screenshot({path:path.join(out,`scan-camera-opening-${viewport.width}.png`)});
   await page.getByRole('button',{name:'Close scanner',exact:true}).click();
   assert.equal(await page.locator('.dr-scanner').evaluate(element=>element.open),false);

   assert.deepEqual(errors,[]);await page.close();
  }
 }finally{await browser.close();}
 console.log('Real Chromium: mobile/desktop artwork, item details, readable widths, quantity confirmation and list opening passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
