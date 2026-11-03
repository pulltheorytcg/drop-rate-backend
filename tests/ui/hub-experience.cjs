const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const tick=()=>new Promise(resolve=>setTimeout(resolve,30));
function fixture({reduced=false,motionOff=false,cachedOverview=null}={}){
  const html=fs.readFileSync(path.join(base,'owner.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'');
  const dom=new JSDOM(html,{url:'https://example.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,doc=w.document,ctx=dom.getInternalVMContext();
  const run=source=>vm.runInContext(source,ctx);
  w.scrollTo=()=>{};w.fetch=async()=>({ok:true,json:async()=>({items:[],summary:{}})});
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const media={matches:reduced,addEventListener:(_,cb)=>{media.change=cb;}};
  w.matchMedia=()=>media;
  const animations=[];
  w.Element.prototype.animate=function(frames,options){
    const record={frames,options,cancelled:false,finished:new Promise(()=>{}),cancel(){this.cancelled=true;}};
    animations.push(record);return record;
  };
  if(motionOff)w.localStorage.setItem('drop-rate-interface-motion','off');
  for(const file of ['hub-session.js','owner-portal.js','workspace-shell.js','collector-worlds.js']){
    run(fs.readFileSync(path.join(base,file),'utf8').replace(/\ninitialise\(\);\s*$/,'\n'));
  }
  run(`state.session={access_token:'fixture',user:{id:'a'}};apiRequest=async()=>({items:[],summary:{}});loadOwnerInventory=loadOwnerOverview=loadOwnerChannels=async()=>{};`);
  if(cachedOverview)run(`state.hubOverview=${JSON.stringify(cachedOverview)};`);
  doc.body.classList.remove('hub-restoring');doc.getElementById('owner-portal-view').classList.remove('hidden');
  const actions=[];
  w.DropRateBooks={open:()=>actions.push('books')};
  w.DropRateCollectibles={open:()=>actions.push('collectibles')};
  w.openDropRateCatalogue=()=>actions.push('catalogue');
  run(fs.readFileSync(path.join(base,'hub-experience.js'),'utf8'));
  return {w,doc,run,actions,animations,media,close:()=>w.close()};
}
(async()=>{
  let checks=0;
  for(const userId of ['a','other']){
    const f=fixture({cachedOverview:{userId,summary:{total_inventory_count:5,collection_states:{review:2,for_sale:2}}}});
    assert.equal(f.doc.querySelector('.hub-attention').hidden,userId!=='a');
    if(userId==='a')assert.match(f.doc.querySelector('.hub-attention').textContent,/2 listings in review/);
    f.close();checks++;
  }
  {
    const f=fixture();
    assert.deepEqual([...f.doc.querySelectorAll('.owner-nav-item')].map(n=>n.dataset.ownerView),['overview','inventory','scan','search','selling']);
    f.run("activateOwnerView('sales',false)");
    assert.equal(f.doc.querySelector('.owner-nav-item.active').dataset.ownerView,'selling');
    f.run("activateOwnerView('profile',false)");
    assert.equal(f.doc.querySelector('.owner-nav-item.active'),null);
    assert.ok(f.doc.querySelector('.hub-account-menu #owner-logout-button'));
    const trigger=f.doc.querySelector('.workspace-account-trigger');trigger.click();
    assert.equal(trigger.getAttribute('aria-expanded'),'true');
    const first=f.doc.activeElement;assert.equal(first.getAttribute('role'),'menuitem');
    first.dispatchEvent(new f.w.KeyboardEvent('keydown',{key:'End',bubbles:true}));
    assert.equal(f.doc.activeElement.id,'owner-logout-button');
    f.doc.activeElement.dispatchEvent(new f.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    assert.equal(trigger.getAttribute('aria-expanded'),'false');assert.equal(f.doc.activeElement,trigger);
    f.close();checks++;
  }
  {
    const f=fixture();const trigger=f.doc.querySelector('#owner-view-inventory [data-hub-add]');trigger.focus();trigger.click();
    const dialog=f.doc.getElementById('hub-add-dialog');assert.ok(dialog.open);
    assert.match(dialog.textContent,/You choose separately whether to sell/);
    assert.equal(dialog.querySelectorAll('.hub-add-choice').length,5);
    [...dialog.querySelectorAll('button')].find(n=>n.textContent.includes('Search the catalogue')).click();
    assert.equal(dialog.open,false);assert.deepEqual(f.actions,['catalogue']);
    trigger.click();[...dialog.querySelectorAll('button')].find(n=>n.textContent.includes('sports cards or figures')).click();
    assert.deepEqual(f.actions,['catalogue','collectibles']);
    trigger.click();dialog.dispatchEvent(new f.w.Event('cancel',{cancelable:true}));
    assert.equal(dialog.open,false);assert.equal(f.doc.activeElement,trigger);
    f.close();checks++;
  }
  {
    const f=fixture();f.w.DropRateHub.openAdd();assert.ok(f.animations.length);
    f.media.matches=true;f.media.change();
    assert.equal(f.doc.body.dataset.hubMotion,'off');assert.ok(f.animations.every(a=>a.cancelled));
    const before=f.animations.length;f.run("activateOwnerView('inventory',false)");assert.equal(f.animations.length,before);
    assert.equal(f.doc.querySelector('[data-hub-motion]').disabled,true);
    f.close();checks++;
  }
  for(const options of [{reduced:true},{motionOff:true}]){
    const f=fixture(options);f.w.DropRateHub.openAdd();f.run("activateOwnerView('inventory',false)");
    assert.equal(f.animations.length,0);assert.equal(f.doc.body.dataset.hubMotion,'off');
    f.close();checks++;
  }
  {
    const f=fixture();
    f.run(`renderSales([{sold_at:'2026-11-01',name:'Synthetic item',source:'SHOPIFY',order_number:'#TEST',net_sale_minor:10000,commission_minor:500,owner_proceeds_minor:9500,financials_complete:true}]);`);
    await tick();
    const card=f.doc.querySelector('#owner-view-sales .hub-transaction-card');assert.ok(card);
    assert.equal(card.querySelector('.hub-transaction-amount').textContent,'£95.00');
    assert.match(card.textContent,/Synthetic item/);assert.match(card.textContent,/Complete/);
    const original=[...f.doc.querySelector('#owner-sales-body tr').cells].map(cell=>cell.textContent);
    assert.deepEqual([...card.querySelectorAll('dd')].map(cell=>cell.textContent),original);
    const details=card.querySelector('details');details.open=true;
    f.doc.querySelector('#owner-sales-body td').textContent='2 Nov 2026';await tick();
    assert.equal(f.doc.querySelector('#owner-view-sales .hub-transaction-amount').textContent,'£95.00');
    f.run(`renderSales([{sold_at:'2026-11-02',name:'Old account sale',owner_proceeds_minor:1234}]);`);
    f.w.DropRateHub.openAdd();f.run('state.session=null');f.w.dispatchEvent(new f.w.Event('hub-session-cleared'));
    await tick();
    assert.equal(f.doc.querySelector('#hub-add-dialog').open,false);
    assert.equal(f.doc.querySelectorAll('.hub-transaction-card').length,0);
    f.close();checks++;
  }
  {
    const f=fixture();
    f.doc.dispatchEvent(new f.w.CustomEvent('hub:overview-updated',{detail:{summary:{total_inventory_count:0,inspection_count:0}}}));
    assert.match(f.doc.querySelector('.collector-headline').textContent,/starts here/);
    assert.equal(f.doc.querySelector('.hub-attention').hidden,true);
    f.doc.dispatchEvent(new f.w.CustomEvent('hub:overview-updated',{detail:{summary:{total_inventory_count:5,collection_states:{review:2}}}}));
    assert.match(f.doc.querySelector('.hub-attention').textContent,/2 listings in review/);
    f.close();checks++;
  }
  console.log(`Hub experience: ${checks} navigation, add, keyboard, motion, finance and account reset groups passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
