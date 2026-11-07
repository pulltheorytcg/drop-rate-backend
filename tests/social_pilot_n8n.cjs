'use strict';
// Executed only in a disposable Docker --network none fixture.
const http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {promisify}=require('node:util'),execFile=promisify(require('node:child_process').execFile);
const secret='ci-only-approved-pilot-signature-123456789012345';
assert.equal(process.env.DROP_RATE_AUTOMATION_COMMAND_SECRET,secret);
assert.equal(process.env.DROP_RATE_API_AUTOMATION_CONTROL_URL,'http://drop-rate-api-live.railway.internal:8765/api/v1/automation/control/receipt');
let calls=[];
const server=http.createServer((req,res)=>{
 let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{
  try{
   assert.equal(req.url,'/api/v1/automation/commands/approved-social-pilot/execute');
   assert.equal(req.method,'POST');
   assert.equal(req.headers['x-drop-rate-signature'],'sha256='+crypto.createHmac('sha256',secret).update(req.headers['x-drop-rate-timestamp']+'.'+raw).digest('hex'));
   const c=JSON.parse(raw);assert.equal(c.pilot_id,'6d3c3d1e-0ec0-4fc8-b5fb-5f9d4eeb925a');
   assert.equal(c.actor_user_id,'6e8291db-0975-4acf-9ce4-f2f25a87d88d');
   assert.equal(c.revision_sha256,process.env.DROP_RATE_APPROVED_PILOT_HASH);
   assert(['instagram','tiktok'].includes(c.channel));assert(['check','publish','status'].includes(c.operation));
   calls.push(c.channel+':'+c.operation);
   const state={check:'READY',publish:'ACCEPTED',status:'DELIVERED'}[c.operation];
   res.writeHead(200,{'Content-Type':'application/json'});
   res.end(JSON.stringify({...c,state,published:state==='DELIVERED',post_id:state==='READY'?null:'fixture-'+c.channel}));
  }catch{res.writeHead(400,{'Content-Type':'application/json'});res.end('{"error":"fixture_rejected"}');}
 });
});
(async()=>{
 await new Promise(resolve=>server.listen(8765,'127.0.0.1',resolve));
 try{
  for(const op of ['check','publish','status']){
   calls=[];
   const {stdout}=await execFile('node',['/opt/drop-rate/pilot/run-approved-pilot.cjs'],{env:{...process.env,DROP_RATE_APPROVED_PILOT_OPERATION:op},timeout:100000,maxBuffer:100000});
   const line=stdout.split('\n').find(l=>l.startsWith('DROP_RATE_APPROVED_PILOT_RESULT '));
   assert(line);const out=JSON.parse(line.slice('DROP_RATE_APPROVED_PILOT_RESULT '.length));
   assert.equal(out.operation,op);assert.equal(out.results.length,2);
   assert.deepEqual(calls.sort(),['instagram:'+op,'tiktok:'+op]);
   assert(out.results.every(r=>r.state==={check:'READY',publish:'ACCEPTED',status:'DELIVERED'}[op]));
   assert(!stdout.includes(secret));assert(!stdout.includes('sha256='));
  }
  console.log('PASS: actual n8n signed check/publish/status orchestration with only local fixtures; temporary DB, safe summaries and two exact channels. No Buffer request or real social post.');
 }finally{server.close();}
})().catch(error=>{console.error('Pilot fixture failed:',error.message);process.exitCode=1;});
