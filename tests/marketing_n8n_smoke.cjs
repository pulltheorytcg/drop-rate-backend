// CI-only n8n execution smoke. Run only inside --network none container.
const fs = require('node:fs');
const http = require('node:http');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {promisify} = require('node:util');
const exec = promisify(require('node:child_process').execFile);
const secret = process.env.DROP_RATE_AUTOMATION_COMMAND_SECRET;
assert.equal(secret, 'disposable-marketing-smoke-signature-123456789');
assert.equal(process.env.N8N_USER_FOLDER, '/tmp/drop-rate-marketing-ci');
assert.equal(process.env.DROP_RATE_API_AUTOMATION_CONTROL_URL, 'http://drop-rate-api-live.railway.internal:8765/api/v1/automation/control/receipt');
let requests = [], mode = 'happy';
const input = {job_id:'00000000-0000-4000-8000-000000000001',actor_user_id:'00000000-0000-4000-8000-000000000002',revision:1,expected_input_sha256:'a'.repeat(64)};
const server = http.createServer((req,res)=>{
  let raw='';
  req.on('data',chunk=>raw+=chunk);
  req.on('end',()=>{
    try {
      assert.equal(req.method,'POST');
      assert.equal(req.url,'/api/v1/automation/commands/marketing/run');
      const timestamp=req.headers['x-drop-rate-timestamp'];
      const signature='sha256='+crypto.createHmac('sha256',secret).update(timestamp+'.'+raw).digest('hex');
      assert.equal(req.headers['x-drop-rate-signature'],signature);
      const command=JSON.parse(raw);
      for (const key of Object.keys(input)) assert.equal(command[key],input[key]);
      requests.push(command.stage);
      const state=command.stage==='publishing'?'BLOCKED':mode==='review'?'NEEDS_REVIEW':command.stage==='design'?'AWAITING_MEDIA':'PREPARED';
      res.writeHead(200,{'Content-Type':'application/json'});
      res.end(JSON.stringify({...command,state,publishable:false,published:false}));
    } catch {
      res.writeHead(400,{'Content-Type':'application/json'});
      res.end(JSON.stringify({error:'fixture_contract_invalid'}));
    }
  });
});
function wrapper(id,target){
  const nodes=[
    {id:'manual',name:'Start',type:'n8n-nodes-base.manualTrigger',typeVersion:1,position:[0,0],parameters:{}},
    {id:'seed',name:'Fixture',type:'n8n-nodes-base.code',typeVersion:2,position:[240,0],parameters:{jsCode:'return [{json:'+JSON.stringify(input)+'}];'}},
    {id:'call',name:'Actual Workflow',type:'n8n-nodes-base.executeWorkflow',typeVersion:1.2,position:[480,0],parameters:{workflowId:{__rl:true,mode:'id',value:target},mode:'each',options:{waitForSubWorkflow:true}}},
  ];
  return {id,name:id,active:false,nodes,connections:{Start:{main:[[{node:'Fixture',type:'main',index:0}]]},Fixture:{main:[[{node:'Actual Workflow',type:'main',index:0}]]}},settings:{executionOrder:'v1',saveDataErrorExecution:'none',saveDataSuccessExecution:'none',saveManualExecutions:false}};
}
async function command(args){return await exec('n8n',args,{timeout:90000,maxBuffer:4*1024*1024,env:process.env});}
(async()=>{
  await new Promise(resolve=>server.listen(8765,'127.0.0.1',resolve));
  try {
    fs.writeFileSync('/tmp/marketing-fixtures.json',JSON.stringify([wrapper('DRMarketingFixturePrep','DRMktPrepareV1'),wrapper('DRMarketingFixturePublish','DRMktPublishV1')]));
    await command(['import:workflow','--input=/tmp/marketing-fixtures.json']);
    // n8n 2.32.6 CLI mode resolves published child versions, unlike an editor
    // manual run. Publish the imported versions ONLY in this disposable,
    // network-isolated CI database. Source exports and production stay inactive.
    const ids=['DRMktResearchV1','DRMktBriefV1','DRMktCopyV1','DRMktDesignV1','DRMktPublishV1','DRMktManageV1','DRMktPrepareV1'];
    for(const id of ids) await command(['publish:workflow','--id='+id]);
    await command(['export:workflow','--all','--output=/tmp/published-fixture.json']);
    const saved=JSON.parse(fs.readFileSync('/tmp/published-fixture.json','utf8'));
    for(const id of ids){const item=saved.find(w=>w.id===id);assert(item);assert.equal(item.active,true);}
    const happy=await command(['execute','--id=DRMarketingFixturePrep','--rawOutput']);
    assert.deepEqual(requests,['research','brief','copywriting','design']);
    assert(happy.stdout.includes('AWAITING_MEDIA'));
    console.log('PASS: actual n8n preparation workflow completed all four signed stage handoffs and stopped awaiting media');
    requests=[]; mode='review';
    let rejected=false;
    try{await command(['execute','--id=DRMarketingFixturePrep','--rawOutput']);}catch(error){rejected=true;assert(String(error.stdout).includes('marketing_handoff_stopped_NEEDS_REVIEW'));}
    assert(rejected);
    assert.deepEqual(requests,['research']);
    console.log('PASS: actual n8n review gate stopped before brief/copy/design');
    requests=[]; mode='happy';
    const published=await command(['execute','--id=DRMarketingFixturePublish','--rawOutput']);
    assert.deepEqual(requests,['publishing']);
    assert(published.stdout.includes('BLOCKED'));
    console.log('PASS: publishing boundary returned BLOCKED, no external network or platform calls');
  } finally {server.close();}
})().catch(error=>{
  console.error('Marketing n8n CI smoke failed:',error.message);
  console.error('Fixture stages reached:', JSON.stringify(requests));
  if(error.stdout){
    const text=String(error.stdout);
    console.error('Nested diagnostics:',text.split('\n').filter(line=>/"message"|"description"|"cause"|Error|error:|Problem/.test(line)).slice(0,80).join('\n'));
    console.error('Execution prefix:',text.slice(0,4500));
  }
  if(error.stderr)console.error(String(error.stderr).slice(-2000));
  process.exitCode=1;
});
