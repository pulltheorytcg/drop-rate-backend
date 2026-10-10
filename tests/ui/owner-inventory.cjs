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
  assert.match(f.w.document.querySelector('.owner-card-prices').textContent,/£8.66/);
  f.w.document.querySelector('.owner-card-image-wrap').click();await tick();
  assert.equal(f.w.document.querySelector('dialog').open,true);assert.match(f.w.document.querySelector('dialog').textContent,/INV-EXACT-COPY/);
  f.w.DropRateInventory.close();f.w.document.querySelector('.owner-inventory-open').click();await tick();assert.equal(f.w.document.querySelector('dialog').open,true);
  assert.match(f.w.document.querySelector('dialog').textContent,/Drop Rate intake review/);assert.equal(btn(f.w,'Sync to Shopify').disabled,true);
  assert.equal(f.calls.filter(c=>c.method).length,0);f.finish();checks++;
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
 for(const override of [{status:'SOLD'},{status:'RESERVED'},{status:'WITHDRAWN'},{sale_intent:'PERSONAL_COLLECTION',status:'APPROVED'},{shopify_sync_enabled:false,status:'APPROVED'}]){
  const f=fixture(override);await f.open();assert.equal(btn(f.w,'Sync to Shopify').disabled,true);
  if(override.status!=='APPROVED'){assert.equal(btn(f.w,'Save selling price').disabled,true);assert.equal(btn(f.w,'−').disabled,true);assert.equal(btn(f.w,'+').disabled,true);}
  f.finish();checks++;
 }
 {
  const f=fixture({product_type:'CARD',grading_company:'PSA',grade:'10',certificate_number:'123'});await f.open();assert.equal(btn(f.w,'+').disabled,true);assert.match(f.w.document.querySelector('dialog').textContent,/own certificate/);f.finish();checks++;
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
