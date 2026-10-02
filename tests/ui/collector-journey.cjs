const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
function page(name,script=name){
 const dom=new JSDOM(fs.readFileSync(path.join(base,name+'.html'),'utf8').replace(/<script[^>]*><\/script>/g,''),{url:'https://example.test/'+(name==='index'?'app':name==='owner'?'owner':name==='owner-join'?'owner/join':'join'),runScripts:'outside-only'});
 const w=dom.window,run=code=>vm.runInContext(code,dom.getInternalVMContext());w.scrollTo=()=>{};w.navigate=url=>w.lastRoute=url;w.fetch=async()=>({ok:true,json:async()=>({})});
 run(fs.readFileSync(path.join(base,'hub-session.js'),'utf8'));
 run(fs.readFileSync(path.join(base,script+'.js'),'utf8').replace(/\ninitialise\(\);\s*$/,'\n').replaceAll('window.location.replace(','window.navigate(').replaceAll('window.location.assign(','window.navigate('));
 return {w,run,close:()=>w.close()};
}
(async()=>{
 let checks=0;
 // Exercise the actual registration writer, then open a fresh seller document.
 for(const invited of [false,true]){
  const join=page('owner-join');join.run(`state.token=${invited?"'test-invitation'":'null'};state.invite={invited_name:'Test seller'};state.config={};localStorage.setItem('drop_rate_pending_owner_ack','1');authenticatedUser=async()=>({id:'seller',email:'seller@example.test'});`);
  const session={access_token:'registration-access',refresh_token:'registration-refresh'};
  await join.run(`finishAuthenticatedOnboarding(${JSON.stringify(session)},'Test seller')`);
  assert.equal(join.w.lastRoute,'/owner?welcome=1');assert.equal(join.w.sessionStorage.getItem('drop_rate_owner_session'),null);
  const stored=join.w.sessionStorage.getItem('drop_rate_hub_session');assert.equal(JSON.parse(stored).access_token,session.access_token);
  const hub=page('owner','owner-portal');hub.w.sessionStorage.setItem('drop_rate_hub_session',stored);
  hub.run(`apiRequest=async()=>({access:{access_role:'OWNER',portal:'OWNER_PORTAL',display_name:'Test seller'}});reloadOwnerDashboard=async()=>{};`);
  await hub.run('initialise()');assert.equal(hub.w.lastRoute,undefined);assert.equal(hub.w.document.getElementById('owner-portal-view').classList.contains('hidden'),false);
  assert.equal(hub.run('state.session.user.id'),'seller');join.close();hub.close();checks++;
 }
 // Founder invitation redemption writes the same key too.
 {
  const f=page('join');f.run(`state.token='invitation';`);await f.run(`redeem({access_token:'founder',user:{id:'founder-id'}},'Founder','founder@example.test')`);
  assert.equal(f.w.PullTheoryHubSession.read().access_token,'founder');assert.equal(f.w.sessionStorage.getItem('drop_rate_founder_session'),null);f.close();checks++;
 }
 // Public existing-account entry must not invoke registration again.
 {
  const f=page('owner-join');f.w.document.getElementById('owner-show-existing-login').click();assert.equal(f.w.lastRoute,'/app');
  f.run(`state.token='invitation'`);f.w.lastRoute=undefined;f.w.document.getElementById('owner-show-existing-login').click();assert.equal(f.w.lastRoute,undefined);assert.equal(f.w.document.getElementById('owner-existing-login-form').classList.contains('hidden'),false);f.close();checks++;
 }
 // Migrate a single legacy session without ever guessing between accounts.
 for(const conflict of [false,true]){
  const f=page('owner','owner-portal');f.w.sessionStorage.setItem('drop_rate_owner_session',JSON.stringify({access_token:'old-owner'}));
  if(conflict)f.w.sessionStorage.setItem('drop_rate_founder_session',JSON.stringify({access_token:'other-account'}));
  const session=f.w.PullTheoryHubSession.read();assert.equal(session?.access_token,conflict?undefined:'old-owner');assert.equal(f.w.sessionStorage.getItem('drop_rate_owner_session'),null);assert.equal(f.w.sessionStorage.getItem('drop_rate_founder_session'),null);f.close();checks++;
 }
 console.log(`Collector journey: ${checks} registration handoff, invitation, shared-entry and legacy-session scenarios passed.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
