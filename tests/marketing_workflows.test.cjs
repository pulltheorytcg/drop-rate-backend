const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');
const workflows = JSON.parse(fs.readFileSync(path.join(__dirname,'../automation/n8n/marketing/workflows.json'),'utf8'));
const secret = 'fixture-only-no-real-credential-123456789';
const input = {job_id:'00000000-0000-4000-8000-000000000001',actor_user_id:'00000000-0000-4000-8000-000000000002',revision:1,expected_input_sha256:'a'.repeat(64)};
function execute(code, json=input, env={}, more={}) {
  const sandbox = {require:(name)=>{assert.equal(name,'crypto');return crypto;},$input:{all:()=>[{json}],first:()=>({json})},$env:{DROP_RATE_MARKETING_SPECIALISTS_ENABLED:'true',DROP_RATE_AUTOMATION_COMMAND_SECRET:secret,DROP_RATE_API_AUTOMATION_CONTROL_URL:'https://drop-rate-api-live-production.up.railway.app/api/v1/automation/control/receipt',...env},...more};
  return vm.runInNewContext('(function(){'+code+'})()',sandbox,{timeout:1000});
}
function signer(w){return w.nodes.find(n=>n.name==='Sign Command').parameters.jsCode;}
test('seven unique inactive workflows, no schedule or embedded provider keys',()=>{
  assert.equal(workflows.length,7);
  assert.equal(new Set(workflows.map(w=>w.id)).size,7);
  for(const w of workflows){
    assert.equal(w.active,false);
    assert.equal(w.settings.saveDataErrorExecution,'none');
    assert.equal(w.settings.saveDataSuccessExecution,'none');
    assert.equal(w.settings.saveManualExecutions,false);
    assert.equal(w.settings.errorWorkflow,'DR90GlobalErrorV1');
    for(const n of w.nodes) assert(!/scheduleTrigger|webhook|openAi|agent/i.test(n.type));
    assert(!JSON.stringify(w).includes('BUFFER_API_KEY'));
  }
});
for(const w of workflows.slice(0,6)) {
  test(w.id+' signs exact body and ignores caller-controlled destinations/stages',()=>{
    const result=execute(signer(w),{...input,url:'https://attacker.invalid',stage:'replace-stage'})[0].json;
    assert.equal(result.command_url,'https://drop-rate-api-live-production.up.railway.app/api/v1/automation/commands/marketing/run');
    const sig='sha256='+crypto.createHmac('sha256',secret).update(result.command_timestamp+'.'+result.command_body,'utf8').digest('hex');
    assert.equal(result.command_signature,sig);
    assert(!result.command_body.includes('attacker'));
    assert.notEqual(result.command.stage,'replace-stage');
    assert(!JSON.stringify(result).includes(secret));
    const request=w.nodes.find(n=>n.type.endsWith('.httpRequest'));
    assert.equal(request.retryOnFail,false);
    assert.equal(request.parameters.options.redirect.redirect.followRedirects,false);
  });
}
for(const [name,env] of [
  ['disabled',{DROP_RATE_MARKETING_SPECIALISTS_ENABLED:'false'}],
  ['missing secret',{DROP_RATE_AUTOMATION_COMMAND_SECRET:''}],
  ['untrusted host',{DROP_RATE_API_AUTOMATION_CONTROL_URL:'https://evil.invalid/api/v1/automation/control/receipt'}],
]) test(name+' fails closed',()=>assert.throws(()=>execute(signer(workflows[0]),input,env)));
for(const change of [{revision:2},{job_id:'not-a-uuid'},{expected_input_sha256:'wrong'}])
  test('reject invalid '+JSON.stringify(change),()=>assert.throws(()=>execute(signer(workflows[0]),{...input,...change})));
test('verifier rejects wrong job, state, authority and HTTP failure',()=>{
  const w=workflows[0], command=execute(signer(w))[0].json.command;
  const code=w.nodes.find(n=>n.name==='Verify Result').parameters.jsCode;
  const b={...command,state:'PREPARED',published:false,publishable:false};
  const more={$:()=>({first:()=>({json:{command}})})};
  assert.equal(execute(code,{statusCode:200,body:b},{},more)[0].json.state,'PREPARED');
  for(const mutate of [{published:true},{job_id:input.actor_user_id},{state:'SENT'}])
    assert.throws(()=>execute(code,{statusCode:200,body:{...b,...mutate}},{},more));
  assert.throws(()=>execute(code,{statusCode:500,body:{secret:'private'}},{},more));
});
test('parent routes only prepared outputs and stops on failures/review',()=>{
  const p=workflows[6];
  const calls=p.nodes.filter(n=>n.type.endsWith('.executeWorkflow'));
  assert.deepEqual(calls.map(n=>n.parameters.workflowId.value),workflows.slice(0,4).map(w=>w.id));
  for(const gate of p.nodes.filter(n=>n.type.endsWith('.code'))){
    assert.equal(execute(gate.parameters.jsCode,{state:'PREPARED'})[0].json.state,'PREPARED');
    for(const state of ['BLOCKED','FAILED','UNKNOWN','NEEDS_REVIEW','RUNNING'])
      assert.throws(()=>execute(gate.parameters.jsCode,{state}));
  }
});

test('JSON request mode preserves parsed JSON responses for signed handoffs',()=>{
  for(const w of workflows.slice(0,6)){
    const p=w.nodes.find(n=>n.type.endsWith('.httpRequest')).parameters;
    assert.equal(p.contentType,'json');
    assert.equal(p.specifyBody,'json');
    assert.equal(p.jsonBody,'={{ $json.command_body }}');
    assert.equal(p.body,undefined);
    assert.equal(p.rawContentType,undefined);
  }
});
