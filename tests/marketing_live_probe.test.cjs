'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const {wrappers,sameWorkflow,endpoint,signedPost,SEED,IDS}=require('../automation/n8n/marketing/live_probe.cjs');
const env={DROP_RATE_API_AUTOMATION_CONTROL_URL:'https://drop-rate-api-live-production.up.railway.app/api/v1/automation/control/receipt',DROP_RATE_AUTOMATION_COMMAND_SECRET:'test-only-long-fixture-secret-12345678'};
test('only fixed production/private backend destinations are allowed',()=>{
 assert.equal(endpoint(env),env.DROP_RATE_API_AUTOMATION_CONTROL_URL);
 for(const bad of ['https://example.com/api/v1/automation/control/receipt','https://drop-rate-api-live-production.up.railway.app.evil.test/api/v1/automation/control/receipt','http://127.0.0.1:80/api/v1/automation/control/receipt','https://user:pass@drop-rate-api-live-production.up.railway.app/api/v1/automation/control/receipt'])assert.throws(()=>endpoint({...env,DROP_RATE_API_AUTOMATION_CONTROL_URL:bad}));
});
test('exact posted bytes are signed and redirects/timeouts stay bounded',async()=>{
 let calls=0;
 const body={actor_user_id:'00000000-0000-4000-8000-000000000001'};
 const out=await signedPost(env,'catalog',body,async(url,options)=>{
  calls++;assert(url.endsWith('/automation/commands/marketing/catalog'));assert.equal(options.redirect,'error');assert(options.signal);
  assert.equal(options.body,JSON.stringify(body));
  const wanted='sha256='+crypto.createHmac('sha256',env.DROP_RATE_AUTOMATION_COMMAND_SECRET).update(options.headers['X-Drop-Rate-Timestamp']+'.'+options.body).digest('hex');
  assert.equal(options.headers['X-Drop-Rate-Signature'],wanted);
  return {status:200,text:async()=>'{"enabled":false}'};
 });
 assert.equal(out.enabled,false);assert.equal(calls,1);
});
test('unauthorised routes, short secrets, HTTP errors and oversized responses fail',async()=>{
 await assert.rejects(signedPost(env,'run',{},()=>{throw Error('must not call');}));
 await assert.rejects(signedPost({...env,DROP_RATE_AUTOMATION_COMMAND_SECRET:'short'},'read',{},()=>{throw Error('must not call');}));
 await assert.rejects(signedPost(env,'read',{},async()=>({status:401,text:async()=>''})));
 await assert.rejects(signedPost(env,'read',{},async()=>({status:200,text:async()=>'x'.repeat(524289)})));
});
test('all probe workflows are version-controlled inert manual wrappers',()=>{
 const all=wrappers();assert.equal(all.length,3);assert.equal(new Set(all.map(w=>w.id)).size,3);
 const exported=JSON.parse(fs.readFileSync(path.join(__dirname,'../automation/n8n/marketing/probe-workflows.json'),'utf8'));
 assert.deepEqual(exported,all);
 for(const w of all){assert.equal(w.active,false);assert.equal(w.settings.errorWorkflow,'DR90GlobalErrorV1');assert.equal(w.settings.saveManualExecutions,false);assert.equal(w.nodes[0].type,'n8n-nodes-base.manualTrigger');assert(!JSON.stringify(w).includes('BUFFER_API_KEY'));assert(!w.nodes.some(n=>/scheduleTrigger|webhook|httpRequest/.test(n.type)));}
 assert.equal(IDS.length,7);assert.equal(SEED.metrics.length,0);assert(SEED.evidence.every(e=>e.rights==='reference_only'));
});
test('drift check refuses changed nodes/connections/settings before activation',()=>{
 const w=wrappers()[0];sameWorkflow({...w,active:true},w);
 for(const section of ['nodes','connections','settings']){const x=structuredClone(w);x[section]={};assert.throws(()=>sameWorkflow(x,w));}
});
test('normal startup with no explicit probe mode performs no calls',()=>{
 const r=spawnSync(process.execPath,[path.join(__dirname,'../automation/n8n/marketing/live_probe.cjs')],{env:{PATH:process.env.PATH},encoding:'utf8'});
 assert.equal(r.status,0);assert.equal(r.stdout.trim(),'MARKETING_PROBE_DISABLED');
});
