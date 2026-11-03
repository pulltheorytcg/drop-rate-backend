// Collection controls and rows use the real portal module with a synthetic owner.
const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.resolve(__dirname,'../../backend/app/static'),tick=()=>new Promise(resolve=>setImmediate(resolve));
const item={id:'11111111-1111-4111-8111-111111111111',catalogue_id:'catalogue-a',inventory_code:'INV-ONE',version:1,
 name:'Deadpool / Batman #1',game:'Marvel Comics',product_type:'COMIC',set_name:'Deadpool / Batman',language:'English',
 condition:'Mint',status:'INSPECTION',sale_intent:'FOR_SALE',store_price_minor:1000,market_value_minor:null,
 reference_value:{status:'NEEDS_DETAILS'},grouped_quantity:1};
function fixture(){
 const dom=new JSDOM(fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script\b[^>]*>.*?<\/script>/gs,''),{url:'https://collection.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,run=code=>vm.runInContext(code,dom.getInternalVMContext()),calls=[];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
 w.scrollTo=()=>{};w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};
 w.fetch=async()=>({ok:false,blob:async()=>new w.Blob([])});
 for(const name of ['hub-session.js','reference-value-display.js','inventory-groups.js','owner-inventory.js','owner-portal.js'])run(fs.readFileSync(path.join(base,name),'utf8').replace(/\ninitialise\(\);\s*$/,''));
 run("state.session={access_token:'synthetic',user:{id:'owner-a'}};document.body.classList.remove('hub-restoring');byId('owner-auth-view').classList.add('hidden');byId('owner-portal-view').classList.remove('hidden');activateOwnerView('inventory',false)");
 let handler=async()=>({items:[item],total:1,copy_total:1,facets:{games:['Marvel Comics','One Piece'],languages:['English','Japanese'],combinations:[{category:'COMICS',game:'Marvel Comics'},{category:'TCG',game:'One Piece'}]}});
 w.request=async(url,options={})=>{calls.push({url,...options});return handler(url,options);};run('apiRequest=window.request');
 return {w,run,calls,handle:value=>handler=value,close:()=>w.close()};
}
(async()=>{
 let checks=0;
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  const options=[...f.w.document.querySelector('#owner-inventory-status').options];
  assert.equal(options.find(option=>option.value==='').textContent,'Active collection');
  assert.equal(options.some(option=>option.value==='WITHDRAWN'),false);
  assert.equal(options.some(option=>option.value==='SOLD'),true,'Past sales remain available through explicit history');
  assert.equal(new URL(f.calls.at(-1).url,'https://collection.test').searchParams.has('status'),false);
  f.w.sessionStorage.setItem('drop_rate_collection_view:owner-a',JSON.stringify({status:'WITHDRAWN',offset:50,layout:'list'}));
  f.run('collectionOwner=null;restoreCollectionView()');
  assert.equal(f.run('state.inventory.status'),'');assert.equal(f.run('state.inventory.offset'),0);
  assert.equal(f.run('state.inventory.layout'),'list');f.close();checks++;
 }
 for(const remaining of [0,50]){
  const f=fixture();f.run('state.inventory.offset=50');
  f.handle(async(url)=>{const offset=Number(new URL(url,'https://collection.test').searchParams.get('offset'));return {items:remaining&&offset===0?[item]:[],total:remaining,copy_total:remaining};});
  await f.run('loadOwnerInventory()');
  assert.equal(f.run('state.inventory.offset'),0,'Removing the last copy on a page returns to a real page or the empty Collection');
  assert.equal(f.calls.length,remaining?2:1);
  assert.equal(f.w.document.querySelectorAll('.owner-inventory-card').length,remaining?1:0);
  assert.equal(f.w.document.querySelector('#owner-inventory-prev').disabled,true);
  f.close();checks++;
 }
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  const doc=f.w.document,dialog=doc.querySelector('#owner-collection-filter-dialog'),trigger=doc.querySelector('#owner-collection-filter-trigger');
  assert.equal(trigger.closest('.owner-inventory-toolbar')!==null,true);
  assert.equal(doc.querySelector('#owner-inventory-status').closest('dialog'),dialog);
  assert.equal(doc.querySelector('#owner-collection-sort').closest('dialog'),dialog);
  assert.equal(doc.querySelector('.owner-collection-filters'),null,'Filters must not expand the collection page');
  const before=f.calls.length;trigger.click();assert.equal(dialog.open,true);assert.equal(trigger.getAttribute('aria-expanded'),'true');
  dialog.dispatchEvent(new f.w.Event('cancel',{cancelable:true}));assert.equal(dialog.open,false);assert.equal(trigger.getAttribute('aria-expanded'),'false');
  assert.equal(f.calls.length,before,'Opening and closing filters must not write or refetch');
  f.close();checks++;
 }
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  await f.w.DropRateCollection.setFilters({category:'TCG',language:'Japanese',search:'Luffy',sort:'name'});
  const doc=f.w.document,query=new URL(f.calls.at(-1).url,'https://collection.test').searchParams;
  assert.equal(query.get('category'),'TCG');assert.equal(query.get('language'),'Japanese');assert.equal(query.get('search'),'Luffy');assert.equal(query.get('sort'),'name');
  assert.equal(query.get('group_copies'),'true');assert.ok(f.calls.at(-1).signal,'Collection requests retain cancellation');
  assert.equal(doc.querySelector('#owner-collection-filter-count').textContent,'2');
  assert.match(doc.querySelector('#owner-collection-context').textContent,/1 product found · Name A–Z/);
  assert.deepEqual([...doc.querySelector('#owner-collection-game').options].map(option=>option.value),['','One Piece']);
  const clearLanguage=doc.querySelector('[aria-label="Clear language filter"]');clearLanguage.click();await tick();
  assert.equal(new URL(f.calls.at(-1).url,'https://collection.test').searchParams.has('language'),false);
  assert.equal(doc.querySelector('#owner-collection-filter-count').textContent,'1');
  assert.equal(f.calls.some(call=>call.method),false);f.close();checks++;
 }
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  f.w.document.querySelector('#owner-inventory-list-toggle').click();
  await f.w.DropRateCollection.setFilters({category:'COMICS',language:'English',sort:'value_desc'});
  await f.w.DropRateCollection.clearFilters();
  assert.equal(f.run('state.inventory.layout'),'list');assert.equal(f.run('state.inventory.sort'),'value_desc');
  const query=new URL(f.calls.at(-1).url,'https://collection.test').searchParams;
  assert.equal(query.get('sort'),'value_desc');assert.equal(query.has('category'),false);assert.equal(query.has('language'),false);
  assert.equal(f.w.document.querySelector('#owner-inventory-list-toggle').getAttribute('aria-pressed'),'true');
  assert.equal(f.w.document.querySelector('#owner-inventory-grid-toggle').getAttribute('aria-pressed'),'false');
  assert.equal(f.w.document.querySelector('#owner-inventory-table-wrap').classList.contains('hidden'),false);
  assert.equal(f.w.document.querySelector('#owner-collection-filter-count').hidden,true);f.close();checks++;
 }
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  await f.w.DropRateCollection.setFilters({category:'FIGURES'});
  assert.equal(f.w.document.querySelector('#owner-collection-grading').disabled,true);
  assert.equal(f.w.document.querySelector('#owner-collection-format').disabled,true);
  f.w.document.querySelector('#owner-collection-filter-trigger').click();
  f.run('activateOwnerView("selling",false)');assert.equal(f.w.document.querySelector('#owner-collection-filter-dialog').open,false);
  f.w.document.querySelector('#owner-collection-filter-trigger').click();
  f.run('clearSession()');assert.equal(f.w.document.querySelector('#owner-collection-filter-dialog').open,false);
  f.close();checks++;
 }
 {
  const f=fixture(),historical={...item,id:'22222222-2222-4222-8222-222222222222',name:'<img src=x onerror=alert(1)>',
   product_type:'CARD',condition:'Near Mint',sale_intent:'PERSONAL_COLLECTION',store_price_minor:9900,
   grouped_quantity:3,group_valued_count:2,reference_value:{status:'STALE',last_known_minor:866,checked_at:'2026-10-08T12:00:00Z'}};
  f.run(`renderInventoryRows(${JSON.stringify([item,historical])})`);
  const rows=f.w.document.querySelectorAll('#owner-inventory-body tr');
  assert.equal(rows.length,2);assert.equal(rows[0].children.length,4);
  assert.equal(rows[0].querySelector('td:last-child').textContent,'£10.00');
  assert.equal(rows[1].querySelector('td:last-child').textContent,'—','A personal copy must not expose an irrelevant asking price');
  assert.equal(rows[1].querySelector('.owner-list-quantity').textContent,'×3');
  assert.match(rows[1].querySelector('.owner-list-copy-details').textContent,/English · Near Mint/);
  assert.match(rows[1].querySelector('.owner-collection-market-cell').textContent,/£8.66Historical value2\/3 copies valued/);
  assert.equal(rows[1].querySelector('img[src="x"]'),null);
  let opened;f.w.DropRateInventory.open=(copy,options)=>opened={copy,options};
  f.run('state.inventory.selling=true');rows[0].querySelector('.owner-inventory-open').click();
  assert.equal(opened.copy.id,item.id);assert.equal(opened.options.selling,true);assert.equal(f.calls.length,0);
  f.close();checks++;
 }
 {
  const f=fixture();await f.run('loadOwnerInventory()');
  f.handle(async()=>{throw new Error('This collection is too large for value sorting');});
  await f.w.DropRateCollection.setFilters({sort:'value_desc'});
  assert.equal(f.run('state.inventory.sort'),'updated');assert.equal(f.w.document.querySelector('#owner-collection-sort').value,'updated');
  assert.match(f.w.document.querySelector('#owner-portal-message').textContent,/too large/);
  f.close();checks++;
 }
 console.log(`PASS: ${checks} collection interaction contracts; scoped queries, exact-copy navigation, readable values and independent filter/order/view state.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
