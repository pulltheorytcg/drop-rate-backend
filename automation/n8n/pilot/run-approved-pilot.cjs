'use strict';
// Explicit operator-run command. The ordinary n8n start.sh never invokes this.
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const crypto=require('node:crypto'), {promisify}=require('node:util');
const execFile=promisify(require('node:child_process').execFile);
const {classify}=require('./safe-diagnostics.cjs');
const HASH='880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d';
let phase='CONFIG';
async function run(){
 const op=process.env.DROP_RATE_APPROVED_PILOT_OPERATION;
 if(process.env.DROP_RATE_APPROVED_PILOT_HASH!==HASH||!['check','publish','status'].includes(op)) throw new Error('pilot_operator_configuration_missing');
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'drop-rate-approved-pilot-'));
 fs.chmodSync(temp,0o700);
 const env={...process.env};
 // Never inherit production database configuration into a CLI execution.
 for(const key of Object.keys(env)) if(key.startsWith('DB_')) delete env[key];
 Object.assign(env,{DB_TYPE:'sqlite',DB_SQLITE_DATABASE:path.join(temp,'database.sqlite'),N8N_USER_FOLDER:temp,N8N_ENCRYPTION_KEY:crypto.randomBytes(32).toString('hex'),N8N_DIAGNOSTICS_ENABLED:'false',N8N_VERSION_NOTIFICATIONS_ENABLED:'false',N8N_TEMPLATES_ENABLED:'false'});
 const workflow=path.join(__dirname,'approved-social-pilot.json');
 const w=JSON.parse(fs.readFileSync(workflow,'utf8'));
 if(w.id!=='DRApprovedSocialPilotV1'||w.active!==false||w.nodes.some(n=>/webhook|scheduleTrigger/.test(n.type))) throw new Error('pilot_workflow_contract_invalid');
 const cli=args=>execFile('n8n',args,{env,timeout:260000,maxBuffer:4*1024*1024});
 try{
  phase='IMPORT';
  await cli(['import:workflow','--input='+workflow]);
  phase='EXECUTE';
  const result=await cli(['execute','--id='+w.id,'--rawOutput']);
  phase='SUMMARY';
  const pattern=/"pilot_summary_json"\s*:\s*("(?:[^"\\]|\\.)*")/g;
  const matches=[...result.stdout.matchAll(pattern)];
  if(!matches.length) throw new Error('pilot_summary_missing');
  const summary=JSON.parse(JSON.parse(matches[matches.length-1][1]));
  if(summary.pilot_id!=='6d3c3d1e-0ec0-4fc8-b5fb-5f9d4eeb925a'||summary.operation!==op) throw new Error('pilot_summary_identity_mismatch');
  console.log('DROP_RATE_APPROVED_PILOT_RESULT '+JSON.stringify(summary));
  // Accepted does not mean delivered. The caller must run a separate status check.
 }finally{
  // Only delete our explicitly created disposable directory, never the volume.
  if(temp.startsWith(path.join(os.tmpdir(),'drop-rate-approved-pilot-'))) fs.rmSync(temp,{recursive:true,force:true});
 }
}
run().catch(error=>{console.error('DROP_RATE_APPROVED_PILOT_RESULT '+JSON.stringify(classify(error,phase)));process.exitCode=1;});
