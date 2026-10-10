// Render the actual seller page/assets with isolated API fixtures; never mutate live stock.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=path.resolve(__dirname,'../../backend/app/static'),out='/tmp/inventory-layout';
const artwork='https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp';
const item={id:'d715b0e9-b3c4-451b-a909-5fa233f8a0e5',inventory_code:'INV-D715B0E9B3C4451BA9095FA233F8A0E5',version:3,status:'DRAFT',sale_intent:'FOR_SALE',product_type:'SEALED',game:'One Piece',language:'Japanese',seal_status:'SEALED',name:"Booster Pack: World's Strongest Warriors [OP-17]",set_name:"World's Strongest Warriors [OP-17]",market_value_minor:866,store_price_minor:null,reference_image_url:artwork,approval_blockers:['Drop Rate intake review','A selling price of at least £1','An approved listing photo'],shopify_sync_enabled:true};
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
   await page.screenshot({path:path.join(out,`inventory-${viewport.width}.png`),fullPage:true});
   await page.locator('.owner-card-image-wrap').click();await page.getByRole('dialog').waitFor();
   await page.getByRole('heading',{name:'Sell on Shopify',exact:true}).waitFor();
   assert.equal(await page.getByRole('button',{name:'Sync to Shopify',exact:true}).isDisabled(),true);
   const box=await page.getByRole('dialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=viewport.width+1);
   assert.equal(await page.getByRole('dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),true,'Details overflow');
   await page.screenshot({path:path.join(out,`details-${viewport.width}.png`)});
   await page.getByRole('button',{name:'Increase quantity by one',exact:true}).click();
   await page.getByRole('button',{name:'Confirm additional copy',exact:true}).waitFor();
   await page.screenshot({path:path.join(out,`quantity-${viewport.width}.png`)});
   await page.getByRole('button',{name:'Close item details',exact:true}).click();
   await page.getByRole('button',{name:'List view',exact:true}).click();
   await page.locator('.owner-inventory-open').click();await page.getByRole('heading',{name:'Sell on Shopify',exact:true}).waitFor();
   assert.deepEqual(errors,[]);await page.close();
  }
 }finally{await browser.close();}
 console.log('Real Chromium: mobile/desktop artwork, item details, readable widths, quantity confirmation and list opening passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
