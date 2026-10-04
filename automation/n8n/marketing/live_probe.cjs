'use strict';
// Explicit operator-run release probe. Never invoked by the normal startup script.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {promisify} = require('node:util');
const execFile = promisify(require('node:child_process').execFile);
const IDS = ['DRMktResearchV1','DRMktBriefV1','DRMktCopyV1','DRMktDesignV1','DRMktPublishV1','DRMktManageV1','DRMktPrepareV1'];
const EXPECTED_STAGES = ['research','brief','copywriting','design'];
const ROOT = '/opt/drop-rate/marketing';
const SEED = {
  topic: 'Internal nonpublishing preparation test: a compact three-slide educational guide to what PSA 10 means. Explain the small printing-imperfection allowance without promising grades, prices, profits or stock. End with a collector discussion question. Use only the supplied PSA facts.',
  evidence: [{id:'psa_standards_20261004',url:'https://www.psacard.com/gradingstandards',observed_at:'2026-10-04T13:36:00Z',rights:'reference_only',excerpt:'Researcher paraphrase of PSA grading standards checked 4 October 2026: PSA describes Gem Mint 10 as virtually perfect. Its criteria include sharp corners, clear focus, original gloss and no staining. A slight printing imperfection may be allowed when it does not impair overall appeal. This source does not establish any inventory, asking price or completed-sale value.'}],
  metrics: [],
};
function wrappers() {
  return [['DRMktLivePrepProbeV1','DRMktPrepareV1'],['DRMktLivePublishProbeV1','DRMktPublishV1'],['DRMktLiveErrorProbeV1',null]].map(([id,target])=>{
    const nodes=[{id:'manual',name:'Start',type:'n8n-nodes-base.manualTrigger',typeVersion:1,position:[0,0],parameters:{}},
      {id:'input',name:'Probe Input',type:'n8n-nodes-base.code',typeVersion:2,position:[240,0],parameters:{jsCode:target?"if ($env.DROP_RATE_MARKETING_PROBE_MODE !== 'prepare') throw new Error('marketing_probe_disabled'); return [{json:{job_id:$env.DROP_RATE_MARKETING_PROBE_JOB_ID,actor_user_id:$env.DROP_RATE_MARKETING_PROBE_ACTOR_USER_ID,revision:1,expected_input_sha256:$env.DROP_RATE_MARKETING_PROBE_INPUT_SHA256}}];":"throw new Error('MARKETING_RELEASE_CONTROLLED_FAILURE');"}}];
    if(target) nodes.push({id:'call',name:'Run Existing Specialist Workflow',type:'n8n-nodes-base.executeWorkflow',typeVersion:1.2,position:[480,0],parameters:{workflowId:{__rl:true,value:target,mode:'id'},mode:'each',options:{waitForSubWorkflow:true}}});
    const connections={};
    for(let i=0;i<nodes.length-1;i++)connections[nodes[i].name]={main:[[{node:nodes[i+1].name,type:'main',index:0}]]};
    return {id,name:'Drop Rate Marketing Live '+(target?(target==='DRMktPrepareV1'?'Preparation':'Publishing Boundary'):'Error')+' Probe V1',active:false,nodes,connections,pinData:{},settings:{executionOrder:'v1',errorWorkflow:'DR90GlobalErrorV1',saveDataErrorExecution:'none',saveDataSuccessExecution:'none',saveManualExecutions:false,saveExecutionProgress:false,executionTimeout:240},meta:{dropRate:{role:'explicit-release-probe',noSchedule:true,publishable:false}}};
  });
}
function sameWorkflow(actual, expected) {
  assert(actual, 'workflow_missing');
  assert.deepEqual(actual.nodes,expected.nodes,'workflow_nodes_drifted');
  assert.deepEqual(actual.connections,expected.connections,'workflow_connections_drifted');
  for(const key of Object.keys(expected.settings))assert.deepEqual(actual.settings[key],expected.settings[key],'workflow_settings_drifted');
}
function endpoint(env) {
  const value=String(env.DROP_RATE_API_AUTOMATION_CONTROL_URL||'');
  assert(value==='https://drop-rate-api-live-production.up.railway.app/api/v1/automation/control/receipt'||/^http:\/\/drop-rate-api-live\.railway\.internal:[0-9]{1,5}\/api\/v1\/automation\/control\/receipt$/.test(value),'backend_url_not_allowed');
  return value;
}
async function signedPost(env,route,value,fetcher=fetch) {
  const secret=String(env.DROP_RATE_AUTOMATION_COMMAND_SECRET||'');
  assert(secret.length>=32,'command_credential_missing');
  const url=route==='receipt'?endpoint(env):endpoint(env).replace('/automation/control/receipt','/automation/commands/marketing/'+route);
  assert(['catalog','create','read','receipt'].includes(route),'unsupported_route');
  const body=JSON.stringify(value),timestamp=String(Math.floor(Date.now()/1000));
  const response=await fetcher(url,{method:'POST',redirect:'error',signal:AbortSignal.timeout(30000),headers:{'Content-Type':'application/json','X-Drop-Rate-Timestamp':timestamp,'X-Drop-Rate-Signature':'sha256='+crypto.createHmac('sha256',secret).update(timestamp+'.'+body).digest('hex')},body});
  assert.equal(response.status,200,'backend_http_'+response.status);
  const text=await response.text();
  assert(Buffer.byteLength(text)<=524288,'backend_response_too_large');
  return JSON.parse(text);
}
async function main(env=process.env) {
  const mode=env.DROP_RATE_MARKETING_PROBE_MODE;
  if(!mode||mode==='off'){console.log('MARKETING_PROBE_DISABLED');return;}
  assert(['inspect','prepare','error'].includes(mode),'invalid_probe_mode');
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'drop-rate-marketing-release-'));
  fs.chmodSync(dir,0o700);
  const cli=async(args,extra={})=>execFile('n8n',args,{env:{...env,...extra},timeout:300000,maxBuffer:8*1024*1024});
  const read=async()=>{const output=path.join(dir,'export.json');await cli(['export:workflow','--all','--output='+output]);return JSON.parse(fs.readFileSync(output,'utf8'));};
  const reset=[];
  try {
    const expected=JSON.parse(fs.readFileSync(path.join(ROOT,'workflows.json'),'utf8'));
    assert.deepEqual(expected.map(w=>w.id).sort(),[...IDS].sort());
    let actual=await read();
    for(const w of expected)sameWorkflow(actual.find(a=>a.id===w.id),w);
    const handler=actual.find(w=>w.id==='DR90GlobalErrorV1');
    assert(handler,'global_error_workflow_missing');
    console.log('MARKETING_INSTALLED_VERIFIED '+JSON.stringify({ids:IDS,active:actual.filter(w=>IDS.includes(w.id)&&w.active).map(w=>w.id),errorHandlerPresent:true,errorHandlerActive:handler.active===true}));
    if(mode==='inspect')return;
    const probes=JSON.parse(fs.readFileSync(path.join(ROOT,'probe-workflows.json'),'utf8'));
    assert.deepEqual(probes,wrappers(),'probe_export_drifted');
    for(const w of probes){
      const old=actual.find(a=>a.id===w.id);
      if(old){sameWorkflow(old,w);continue;}
      const input=path.join(dir,w.id+'.json');fs.writeFileSync(input,JSON.stringify(w),{mode:0o600});
      await cli(['import:workflow','--input='+input]);
    }
    actual=await read();for(const w of probes)sameWorkflow(actual.find(a=>a.id===w.id),w);
    if(mode==='error'){
      let expectedFailure=false;
      try{await cli(['execute','--id=DRMktLiveErrorProbeV1','--rawOutput']);}
      catch(e){expectedFailure=String(e.stdout||'').includes('MARKETING_RELEASE_CONTROLLED_FAILURE');console.log('MARKETING_ERROR_PROBE '+JSON.stringify({expectedFailure,responseDecodeFailure:String(e.stdout||'').includes('automation_control_receipt_not_accepted')}));}
      assert(expectedFailure,'controlled_failure_not_executed');return;
    }
    assert.equal(env.DROP_RATE_MARKETING_SPECIALISTS_ENABLED,'true','specialists_not_enabled');
    const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    const actor=env.DROP_RATE_MARKETING_PROBE_ACTOR_USER_ID,jobId=env.DROP_RATE_MARKETING_PROBE_JOB_ID;
    assert(uuid.test(actor||'')&&uuid.test(jobId||''),'probe_identity_invalid');
    const catalog=await signedPost(env,'catalog',{actor_user_id:actor});
    assert(catalog.enabled===true&&catalog.published===false&&catalog.specialists.length===6,'backend_catalog_not_ready');
    const job=await signedPost(env,'create',{actor_user_id:actor,job_id:jobId,revision:1,input:SEED});
    assert(job.job_id===jobId&&job.actor_user_id===actor&&job.publishable===false&&/^[0-9a-f]{64}$/.test(job.expected_input_sha256),'created_job_invalid');
    const runEnv={DROP_RATE_MARKETING_PROBE_INPUT_SHA256:job.expected_input_sha256};
    // Only the seven verified, triggerless specialist versions are made callable.
    for(const id of IDS){if(!actual.find(w=>w.id===id).active){reset.push(id);await cli(['publish:workflow','--id='+id]);}}
    actual=await read();for(const id of IDS)assert(actual.find(w=>w.id===id).active===true,'child_not_published');
    let executionFailed=false;
    try{await cli(['execute','--id=DRMktLivePrepProbeV1','--rawOutput'],runEnv);}catch{executionFailed=true;}
    const result=await signedPost(env,'read',{actor_user_id:actor,job_id:jobId,revision:1});
    assert(result.published===false&&result.publishable===false,'unexpected_public_authority');
    console.log('MARKETING_LIVE_RESULT '+JSON.stringify({jobId,executionFailed,stages:result.stages.map(s=>({stage:s.stage,state:s.state,usage:s.usage,error_code:s.output?.error_code||null})),published:false}));
    const ready=result.stages.length===4&&result.stages.every((s,i)=>s.stage===EXPECTED_STAGES[i]&&s.state===(i===3?'AWAITING_MEDIA':'PREPARED'));
    if(!ready){
      const receipt=await signedPost(env,'receipt',{workflow_key:'marketing-preparation-release',workflow_version:'v1',execution_id:jobId,status:'FAILED',idempotency_key:'marketing-preparation-release:'+jobId,occurred_at:new Date().toISOString(),error_code:'MARKETING_PREPARATION_REQUIRES_REVIEW',error_message:'The bounded nonpublishing release job stopped. Inspect its saved marketing stages; do not automatically retry model calls.'});
      assert(receipt.accepted===true,'failure_receipt_not_accepted');
      console.log('MARKETING_REVIEW_RECORDED');return;
    }
    assert(!executionFailed,'n8n_failed_despite_saved_results');
    await cli(['execute','--id=DRMktLivePrepProbeV1','--rawOutput'],runEnv);
    const replay=await signedPost(env,'read',{actor_user_id:actor,job_id:jobId,revision:1});
    assert.deepEqual(replay.stages,result.stages,'replay_changed_durable_results');
    const block=await cli(['execute','--id=DRMktLivePublishProbeV1','--rawOutput'],runEnv);
    assert(block.stdout.includes('PUBLISHER_NOT_IMPLEMENTED_AWAITING_APPROVED_MEDIA'),'publishing_boundary_not_blocked');
    console.log('MARKETING_LIVE_PREPARATION_PASS '+JSON.stringify({jobId,stages:4,replayUnchanged:true,publisherBlocked:true,published:false}));
  } finally {
    let restoreFailed=false;
    for(const id of reset.reverse()){try{await cli(['unpublish:workflow','--id='+id]);}catch{restoreFailed=true;}}
    if(reset.length){const saved=await read();for(const id of reset)if(saved.find(w=>w.id===id)?.active!==false)restoreFailed=true;}
    fs.rmSync(dir,{recursive:true,force:true});
    assert(!restoreFailed,'specialist_activation_restore_failed');
  }
}
module.exports={wrappers,sameWorkflow,endpoint,signedPost,SEED,IDS};
if(require.main===module){
  if(process.argv[2]==='--export')process.stdout.write(JSON.stringify(wrappers(),null,2)+'\n');
  else main().catch(()=>{console.error('MARKETING_RELEASE_PROBE_FAILED: inspect durable state and release logs; no automatic retry.');process.exitCode=1;});
}
