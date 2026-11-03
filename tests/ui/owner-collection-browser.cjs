// Actual Collection HTML/CSS/JS with synthetic records. No account or live API.
const {chromium,webkit}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const engine=process.env.INVENTORY_BROWSER||'chromium',base=path.resolve(__dirname,'../../backend/app/static');
const out=path.join('/tmp/inventory-layout',engine,'collection-review');
const samples=[
 {id:'11111111-1111-4111-8111-111111111111',catalogue_id:'comic-a',inventory_code:'INV-SYNTHETIC-1',version:1,
  name:'Deadpool / Batman #1',game:'Marvel Comics',product_type:'COMIC',set_name:'Second printing · Cover A',language:'English',condition:'Mint',
  status:'INSPECTION',sale_intent:'FOR_SALE',store_price_minor:1000,market_value_minor:null,reference_value:{status:'NEEDS_DETAILS'},image_url:'https://cdn.shopify.com/synthetic-comic.webp'},
 {id:'22222222-2222-4222-8222-222222222222',catalogue_id:'sealed-a',inventory_code:'INV-SYNTHETIC-2',version:1,
  name:"Booster Pack: World's Strongest Warriors [OP-17]",game:'One Piece',product_type:'SEALED',set_name:"World's Strongest Warriors",language:'Japanese',seal_status:'SEALED',
  status:'DRAFT',sale_intent:'PERSONAL_COLLECTION',store_price_minor:null,market_value_minor:726,reference_value:{status:'AVAILABLE',market_value_minor:726},image_url:'https://cdn.shopify.com/synthetic-pack.webp'},
 {id:'33333333-3333-4333-8333-333333333333',catalogue_id:'card-a',inventory_code:'INV-SYNTHETIC-3',version:1,
  name:'Umbreon VMAX · Alternate Art Secret Rare',game:'Pokémon',product_type:'CARD',set_name:'Evolving Skies',card_number:'215/203',language:'English',condition:'Near Mint',
  status:'APPROVED',sale_intent:'FOR_SALE',store_price_minor:85000,market_value_minor:null,
  reference_value:{status:'STALE',last_known_minor:82500,checked_at:'2026-10-08T12:00:00Z'},image_url:'https://cdn.shopify.com/synthetic-card.webp'},
];
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await ({chromium,webkit})[engine].launch({headless:true}),results=[];
 try{
  for(const viewport of [{width:320,height:800},{width:390,height:844},{width:430,height:932},{width:768,height:1000},{width:1440,height:1000},{width:390,height:460}]){
   const page=await browser.newPage({viewport,deviceScaleFactor:1}),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await page.route(/^https?:\/\//,async route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='cdn.shopify.com'){
     assert.equal(route.request().headers().authorization,undefined,'Fixture artwork must not receive owner credentials');
     const file=url.pathname.includes('comic')?'collection-photos/comics-collection.webp':url.pathname.includes('pack')?'collection-photos/one-piece-op17-sealed.webp':'grail-art/umbreon-vmax-215.webp';
     return route.fulfill({path:path.join(base,file)});
    }
    if(url.hostname!=='collection.test')return route.abort();
    if(url.pathname==='/owner')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script\b[^>]*>.*?<\/script>/gs,'')});
    if(url.pathname.startsWith('/assets/')){const file=path.resolve(base,url.pathname.slice(8));assert.ok(file.startsWith(base+'/'));return route.fulfill({path:file});}
    return route.abort();
   });
   await page.goto('https://collection.test/owner');
   for(const name of ['hub-session.js','reference-value-display.js','inventory-groups.js','owner-inventory.js','owner-portal.js','workspace-shell.js','collector-worlds.js','hub-experience.js'])await page.addScriptTag({content:fs.readFileSync(path.join(base,name),'utf8').replace(/\ninitialise\(\);\s*$/,'')});
   await page.evaluate(async items=>{
    window.fixtureItems=items;window.fixtureCalls=[];
    state.session={access_token:'isolated-collection-fixture',user:{id:'fixture-owner'}};
    apiRequest=async(url,options={})=>{
     fixtureCalls.push({url,method:options.method||'GET'});
     if(url.startsWith('/api/v1/owner/inventory?')){
      const query=new URL(url,location.origin).searchParams;
      let rows=fixtureItems.filter(item=>(!query.get('category') || (item.product_type==='COMIC'?'COMICS':'TCG')===query.get('category')) && (!query.get('language') || item.language===query.get('language')));
      if(query.get('sort')==='name')rows=rows.slice().sort((a,b)=>a.name.localeCompare(b.name));
      return {items:rows,total:rows.length,copy_total:rows.length,grouped:true,facets:{games:['Marvel Comics','One Piece','Pokémon'],languages:['English','Japanese'],combinations:[{category:'COMICS',game:'Marvel Comics'},{category:'TCG',game:'One Piece'},{category:'TCG',game:'Pokémon'}]}};
     }
     const item=fixtureItems.find(item=>url.endsWith('/'+item.id));
     if(item)return {item,copies:[item]};
     return {items:[],summary:{}};
    };
    loadOwnerOverview=loadOwnerChannels=loadOwnerInsights=async()=>{};
    document.body.classList.remove('hub-restoring');document.querySelector('.hub-loading')?.remove();
    byId('owner-auth-view').classList.add('hidden');byId('owner-portal-view').classList.remove('hidden');
    activateOwnerView('inventory',false);await loadOwnerInventory();
   },samples);
   await page.getByRole('button',{name:'List view',exact:true}).click();
   const rows=page.locator('#owner-inventory-body .owner-collection-row');
   assert.equal(await rows.count(),3);
   await page.locator('#owner-inventory-table-wrap').scrollIntoViewIfNeeded();
   await page.waitForFunction(()=>[...document.querySelectorAll('#owner-inventory-body img')].every(image=>image.complete&&image.naturalWidth>0));
   const geometry=await rows.evaluateAll(rows=>rows.map(row=>({height:row.getBoundingClientRect().height,left:row.getBoundingClientRect().left,right:row.getBoundingClientRect().right,cells:row.children.length})));
   assert.ok(geometry.every(row=>row.left>=0&&row.right<=viewport.width+1&&row.height<=160),JSON.stringify({viewport,geometry}));
   assert.ok(geometry.every(row=>row.cells===4),'The desktop value/asking-price columns must stay distinct');
   if(viewport.width<=760)assert.equal(await rows.locator('td').evaluateAll(cells=>cells.every(cell=>getComputedStyle(cell).borderBottomWidth==='0px')),true,'Mobile rows must have one row divider, not individual cell borders');
   assert.equal(await page.locator('#owner-inventory-table-wrap').evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,'List requires horizontal scrolling');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Collection overflows viewport');
   assert.match(await rows.nth(0).innerText(),/Deadpool \/ Batman #1[\s\S]*English · Mint[\s\S]*Listing review/);
   assert.match(await rows.nth(2).innerText(),/£825.00[\s\S]*Historical value/);
   assert.equal(await page.getByRole('button',{name:'List view',exact:true}).getAttribute('aria-pressed'),'true');
   assert.equal(await page.getByRole('button',{name:'Grid view',exact:true}).getAttribute('aria-pressed'),'false');
   const toolbar=page.locator('#owner-view-inventory .owner-inventory-toolbar'),toolbarBox=await toolbar.boundingBox();
   assert.ok(toolbarBox.height<=130,`Toolbar is too tall: ${toolbarBox.height}`);
   for(const control of await toolbar.locator('button:visible,input:visible').all()){
    const box=await control.boundingBox();assert.ok(box.width>=44&&box.height>=44,JSON.stringify(box));
   }
   await page.evaluate(()=>scrollTo(0,0));
   const tag=`${viewport.width}x${viewport.height}`;
   await page.screenshot({path:path.join(out,`collection-list-${tag}.png`),fullPage:true});
   // The list's native item action preserves the exact-copy detail handoff.
   await rows.first().locator('.owner-inventory-open').click();
   await page.locator('.owner-item-dialog[open]').waitFor();
   assert.match(await page.locator('.owner-item-dialog').innerText(),/Deadpool \/ Batman #1/);
   await page.getByRole('button',{name:'Close item details',exact:true}).click();
   await page.getByRole('button',{name:'Filter and sort collection',exact:true}).click();
   const dialog=page.getByRole('dialog',{name:'Filter & sort',exact:true});await dialog.waitFor();
   await dialog.evaluate(async node=>{await Promise.all(node.getAnimations().map(animation=>animation.finished.catch(()=>{})));});
   assert.equal(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,'Filter sheet overflows');
   const box=await dialog.boundingBox();assert.ok(box.x>=-1&&box.y>=-1&&box.x+box.width<=viewport.width+1&&box.y+box.height<=viewport.height+1,JSON.stringify(box));
   const close=dialog.getByRole('button',{name:'Close collection filters',exact:true}),done=dialog.getByRole('button',{name:'Show collection',exact:true});
   for(const control of [close,done]){const rect=await control.boundingBox();assert.ok(rect.y>=0&&rect.y+rect.height<=viewport.height+1&&rect.height>=44&&rect.width>=44,JSON.stringify(rect));}
   await dialog.getByRole('combobox',{name:'Sort collection',exact:true}).selectOption('name');
   await dialog.getByRole('combobox',{name:'Filter collection by category',exact:true}).selectOption('COMICS');
   assert.equal(await dialog.locator('#owner-collection-format').isVisible(),false,'Comics must not show a card/sealed filter');
   await dialog.getByRole('combobox',{name:'Filter collection by language',exact:true}).selectOption('English');
   await page.waitForFunction(()=>document.querySelector('#owner-collection-context').textContent==='1 product found · Name A–Z');
   await dialog.locator('.owner-collection-filter-body').evaluate(node=>node.scrollTop=0);
   await page.screenshot({path:path.join(out,`collection-filters-${tag}.png`)});
   await done.click();
   assert.equal(await dialog.isVisible(),false);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'owner-collection-filter-trigger');
   assert.equal(await page.locator('#owner-collection-filter-count').innerText(),'2');
   await page.screenshot({path:path.join(out,`collection-filtered-${tag}.png`),fullPage:true});
   await page.getByRole('button',{name:'Clear language filter',exact:true}).click();
   await page.waitForFunction(()=>!state.inventory.language);
   await page.getByRole('button',{name:/^Filter and sort collection/}).click();
   await dialog.getByRole('button',{name:'Clear filters',exact:true}).click();
   await page.waitForFunction(()=>!state.inventory.category&&state.inventory.total===3);
   assert.equal(await page.evaluate(()=>state.inventory.sort),'name');
   assert.equal(await page.evaluate(()=>state.inventory.layout),'list');
   await close.click();
   await page.getByRole('button',{name:'Grid view',exact:true}).click();
   assert.equal(await page.locator('#owner-inventory-grid').isVisible(),true);
   assert.equal(await page.locator('#owner-inventory-table-wrap').isVisible(),false);
   assert.equal(await page.evaluate(()=>fixtureCalls.some(call=>call.method!=='GET')),false);
   assert.deepEqual(errors,[]);
   results.push({engine,...viewport,rows:geometry.length,passed:true});await page.close();
  }
 }finally{await browser.close();}
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,2));
 console.log(`PASS: ${results.length} ${engine} collection layouts and journeys; compact rows, 44px controls, responsive filter sheet, exact-copy handoff and independent sort/view state.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
