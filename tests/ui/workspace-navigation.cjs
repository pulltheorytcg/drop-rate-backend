const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static'),tick=()=>new Promise(r=>setImmediate(r));
function fixture(role){
 const html=fs.readFileSync(path.join(base,role==='founder'?'index.html':'owner.html'),'utf8').replace(/<script[^>]*><\/script>/g,'');
 const dom=new JSDOM(html,{url:'https://example.test/'+(role==='founder'?'app':'owner'),runScripts:'outside-only',pretendToBeVisual:true});const w=dom.window,ctx=dom.getInternalVMContext();
 w.scrollTo=()=>{};w.testNavigate=url=>w.lastRoute=url;w.fetch=async()=>({ok:true,json:async()=>({})});
 const run=code=>vm.runInContext(code,ctx);
 run(fs.readFileSync(path.join(base,'hub-session.js'),'utf8'));
 const text=fs.readFileSync(path.join(base,role==='founder'?'app.js':'owner-portal.js'),'utf8').replace(/\ninitialise\(\);\s*$/,'\n').replaceAll('window.location.replace(', 'window.testNavigate(');
 run(text);run(`state.session={access_token:'current',refresh_token:'refresh',user:{id:'account'}};window.PullTheoryHubSession.save(state.session);`);
 return {w,run,finish:()=>w.close()};
}
(async()=>{
 let checks=0;
 // One refresh request for simultaneous API failures; logout during refresh cannot resurrect a session.
 for(const role of ['founder','seller']){
  const f=fixture(role);f.run(`window.refreshCalls=0;authRequest=()=>{window.refreshCalls++;return new Promise(resolve=>{window.finishRefresh=resolve;});};`);
  const one=f.run('refreshSession()'),two=f.run('refreshSession()');await tick();assert.equal(f.w.refreshCalls,1);
  f.w.finishRefresh({access_token:'new',refresh_token:'next',user:{id:'account'}});assert.deepEqual(await Promise.all([one,two]),['new','new']);
  const pending=f.run('refreshSession()');await tick();f.run('clearSession()');f.w.finishRefresh({access_token:'late',refresh_token:'late'});
  await assert.rejects(pending,/account changed/);assert.equal(f.run('state.session'),null);f.finish();checks++;
 }
 // A verified founder opens the workspace; panel errors retain login and show a retryable message.
 {
  const f=fixture('founder');f.run(`apiRequest=async url=>url.endsWith('/access/me')?{access:{founder_hq_allowed:true}}:{owner:{display_name:'Founder'}};reloadDashboard=async()=>{throw Error('Network interrupted');};`);
  await f.run('openDashboard()');assert.equal(f.run('state.session.access_token'),'current');assert.equal(f.w.document.getElementById('dashboard-view').classList.contains('hidden'),false);assert.match(f.w.document.getElementById('inventory-message').textContent,/Refresh/);f.finish();checks++;
 }
 // Owner role routes once; generic administrator without the founder roster cannot open Founder HQ.
 {
  const f=fixture('founder');f.run(`apiRequest=async()=>({access:{access_role:'OWNER',portal:'OWNER_PORTAL'}});`);await f.run('openDashboard()');assert.equal(f.w.lastRoute,'/owner');
  f.run(`apiRequest=async()=>({access:{access_role:'PLATFORM_ADMIN',founder_hq_allowed:false}});`);await f.run('openDashboard()');assert.equal(f.run('state.session'),null);f.finish();checks++;
 }
 // A transient access check must not clear a valid session in either workspace.
 for(const role of ['founder','seller']){
  const f=fixture(role);f.run(`apiRequest=async()=>{const e=Error('Unavailable');e.status=503;throw e;};loadSocialProviders=async()=>{};`);
  if(role==='founder')await f.run('openDashboard()');else await f.run('initialise()');
  assert.equal(f.run('state.session.access_token'),'current');assert.equal(f.w.PullTheoryHubSession.read().access_token,'current');f.finish();checks++;
 }
 // Legacy seller URL is not a second login page.
 {
  const f=fixture('seller');f.run('clearSession()');await f.run('initialise()');assert.equal(f.w.lastRoute,'/app');f.finish();checks++;
 }
 // Embedded catalogue paints before delayed metadata, survives navigation away/back and cancels stale results.
 {
  const dom=new JSDOM('<header class="topbar"></header><section id="host"></section>',{url:'https://example.test/app',runScripts:'outside-only'}),w=dom.window;
  w.eval(fs.readFileSync(path.join(base,'catalogue-browser.js'),'utf8'));let release,requests=0;
  const browser=new w.DropRateCatalogue.Browser({host:w.document.getElementById('host'),client:{owner:'a',active:()=>true,request:async()=>{requests++;return new Promise(r=>release=r);}}});
  const first=browser.open();assert.equal(browser.dialog.tagName,'SECTION');assert.equal(browser.dialog.querySelectorAll('.dr-browse-game').length,6);
  browser.close();const again=browser.open();assert.equal(browser.dialog.hidden,false);assert.equal(requests,1);
  release({items:[{system_code:'POKEMON_TCG',game:'Pokémon',languages:['English']}]});await Promise.all([first,again]);
  assert.equal(browser.dialog.hidden,false);assert.match(browser.dialog.textContent,/Pokémon/);
  browser.openSheet('Test');assert.equal(w.document.querySelector('.topbar').inert,true);browser.destroy();assert.notEqual(w.document.querySelector('.topbar').inert,true);w.close();checks++;
 }
 console.log(`Workspace navigation: ${checks} session, role-routing, failure and immediate-search cases passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
