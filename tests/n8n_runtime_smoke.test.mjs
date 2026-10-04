import test from 'node:test';
import assert from 'node:assert/strict';
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
test('runtime cannot inherit production database, automation secrets or user folder',()=>{
  const env=isolatedEnv('/tmp/smoke',{PATH:'/bin',BUFFER_API_KEY:'test-only',DATABASE_URL:'production',DB_SQLITE_DATABASE:'/home/node/.n8n/database.sqlite',DROP_RATE_AUTOMATION_COMMAND_SECRET:'never-copy',N8N_USER_FOLDER:'/production'});
  assert.equal(env.HOME,'/tmp/smoke'); assert.equal(env.N8N_USER_FOLDER,'/tmp/smoke'); assert.equal(env.DB_TYPE,'sqlite');
  assert.equal(env.DATABASE_URL,undefined); assert.equal(env.DB_SQLITE_DATABASE,undefined); assert.equal(env.DROP_RATE_AUTOMATION_COMMAND_SECRET,undefined);
  assert.equal(env.BUFFER_API_KEY,'test-only');
});
test('hash mismatch refuses execution before spawning or writing',()=>{
  assert.throws(()=>runSmoke({id:'malicious'},'mismatched'),/workflow_hash_mismatch/);
});
