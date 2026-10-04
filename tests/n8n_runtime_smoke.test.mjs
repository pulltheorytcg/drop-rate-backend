import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {extractSummary,isolatedEnv,runSmoke} from '../automation/n8n/runtime-smoke.mjs';

const record=summary=>({finished:true,data:{resultData:{lastNodeExecuted:'Final',runData:{Final:[{data:{main:[[{json:summary}]]}}]}}}});
test('execution proof requires terminal final-node data and omits raw data',()=>{
  const raw=record({ok:true,queue_complete:true,queue_empty:true,scheduled_posts:0,secret:'do-not-log'});
  assert.deepEqual(extractSummary('startup\n'+JSON.stringify(raw),'Final'),{ok:true,queue_complete:true,queue_empty:true,scheduled_posts:0,publishing_verified:false,automatic_posting_active:false});
  raw.finished=false;
  assert.throws(()=>extractSummary(JSON.stringify(raw),'Final'));
});
test('provider failures and pagination remain unsuccessful or incomplete',()=>{
  assert.equal(extractSummary(JSON.stringify(record({ok:false,queue_complete:false})),'Final').ok,false);
  assert.equal(extractSummary(JSON.stringify(record({ok:true,queue_complete:false})),'Final').scheduled_posts,null);
  const raw=record({ok:true}); raw.data.resultData.error={message:'secret'};
  assert.throws(()=>extractSummary(JSON.stringify(raw),'Final'));
  assert.throws(()=>extractSummary('token-or-provider-error','Final'));
});
test('queue failures expose only fixed reason codes, never provider text',()=>{
  const known=extractSummary(JSON.stringify(record({ok:false,reason:'buffer_auth_rejected'})),'Final');
  assert.equal(known.reason,'buffer_auth_rejected');
  const unknown=extractSummary(JSON.stringify(record({ok:false,reason:'secret-provider-payload'})),'Final');
  assert.equal(unknown.reason,'queue_check_failed');
  assert.equal(JSON.stringify(unknown).includes('secret-provider-payload'),false);
});
test('readiness and counts omit raw channels, post details and extra fields',()=>{
  const raw=record({ok:true,all_connections_ready:false,
    channels:[{connection_ready:true,id:'private-id'},{connection_ready:false},{connection_ready:true}],
    counts:{scheduled:0,sending:0,error:0,needs_approval:0,draft:2,secret:'private-data'},
    posts:[{text:'private-post'}]});
  const result=extractSummary(JSON.stringify(raw),'Final');
  assert.equal(result.all_connections_ready,false);
  assert.equal(result.channels_total,3); assert.equal(result.channels_ready,2);
  assert.deepEqual(result.counts,{scheduled:0,sending:0,error:0,needs_approval:0,draft:2});
  assert.equal(JSON.stringify(result).includes('private'),false);
  raw.data.resultData.runData.Final[0].data.main[0][0].json.counts.draft=-1;
  assert.equal(extractSummary(JSON.stringify(raw),'Final').counts,undefined);
});
test('runtime cannot inherit production database, automation secrets or user folder',()=>{
  const env=isolatedEnv('/tmp/smoke',{PATH:'/bin',BUFFER_API_KEY:'test-only',DATABASE_URL:'production',DB_SQLITE_DATABASE:'/home/node/.n8n/database.sqlite',DROP_RATE_AUTOMATION_COMMAND_SECRET:'never-copy',N8N_USER_FOLDER:'/production'});
  assert.equal(env.HOME,'/tmp/smoke'); assert.equal(env.N8N_USER_FOLDER,'/tmp/smoke'); assert.equal(env.DB_TYPE,'sqlite');
  assert.equal(env.DATABASE_URL,undefined); assert.equal(env.DB_SQLITE_DATABASE,undefined); assert.equal(env.DROP_RATE_AUTOMATION_COMMAND_SECRET,undefined);
  assert.equal(env.BUFFER_API_KEY,'test-only');
  assert.equal(env.N8N_LOG_LEVEL,'info','n8n 2.32.6 rawOutput is emitted by logger.info');
});
test('hash mismatch refuses execution before spawning or writing',()=>{
  assert.throws(()=>runSmoke({id:'malicious'},'mismatched'),/workflow_hash_mismatch/);
});
test('runtime refuses raw-stream requests and mutations before spawning',()=>{
  const workflow={id:'DR32BufferQueueCheckV1',active:false,nodes:[
    {type:'n8n-nodes-base.executeWorkflowTrigger'},
    {type:'n8n-nodes-base.httpRequest',parameters:{url:'https://api.buffer.com',contentType:'raw',
      body:JSON.stringify({query:'query DropRateBufferQueue { channels { id } }'})}},
    {type:'n8n-nodes-base.code'},
  ]};
  const check=()=>runSmoke(workflow,createHash('sha256').update(JSON.stringify(workflow)).digest('hex'));
  assert.throws(check,/unexpected_request/);
  workflow.nodes[1].parameters={url:'https://api.buffer.com',contentType:'json',specifyBody:'json',
    jsonBody:JSON.stringify({query:'mutation DropRateBufferQueue { createPost { id } }'})};
  assert.throws(check,/unexpected_request/);
});
