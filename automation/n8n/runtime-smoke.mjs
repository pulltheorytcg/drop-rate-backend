// Run the reviewed DR-32 queue workflow in a disposable n8n database. No editor,
// persistent-volume import, scheduler, publishing or production DB access.
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes, createHash } from 'node:crypto';

export function extractSummary(output, finalNode) {
  const text = String(output);
  // n8n startup messages can precede --rawOutput. Parse only a JSON document
  // which reaches the end of stdout; never print raw execution/provider data.
  let execution;
  for (const match of text.matchAll(/(?:^|\n)(\{)/g)) {
    try { execution = JSON.parse(text.slice(match.index + match[0].length - 1)); break; }
    catch { /* try the next document boundary */ }
  }
  const data = execution?.data?.resultData;
  if (!data || data.error || execution.finished !== true || data.lastNodeExecuted !== finalNode) {
    throw Error('execution_not_verified');
  }
  const result = data.runData?.[finalNode]?.at(-1)?.data?.main?.[0]?.[0]?.json;
  if (!result || typeof result.ok !== 'boolean') throw Error('summary_missing');
  return {
    ok: result.ok,
    queue_complete: result.queue_complete === true,
    queue_empty: typeof result.queue_empty === 'boolean' ? result.queue_empty : null,
    scheduled_posts: Number.isSafeInteger(result.scheduled_posts) ? result.scheduled_posts : null,
    publishing_verified: false,
    automatic_posting_active: false,
  };
}

export function isolatedEnv(root, source=process.env) {
  return {
    PATH: source.PATH, HOME: root, N8N_USER_FOLDER: root, DB_TYPE:'sqlite',
    N8N_ENCRYPTION_KEY: randomBytes(32).toString('hex'),
    N8N_BLOCK_ENV_ACCESS_IN_NODE:'false', NODE_FUNCTION_ALLOW_BUILTIN:'crypto',
    N8N_DIAGNOSTICS_ENABLED:'false', N8N_VERSION_NOTIFICATIONS_ENABLED:'false',
    N8N_RUNNERS_MODE:'internal', N8N_RUNNERS_BROKER_PORT:'15679',
    EXECUTIONS_DATA_SAVE_ON_SUCCESS:'none', EXECUTIONS_DATA_SAVE_ON_ERROR:'none',
    EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS:'false', N8N_LOG_LEVEL:'error',
    BUFFER_API_KEY:source.BUFFER_API_KEY, NODE_ENV:'production', TZ:'Europe/London',
  };
}

export function runSmoke(workflow, expectedHash) {
  const serialized=JSON.stringify(workflow);
  if(createHash('sha256').update(serialized).digest('hex')!==expectedHash) throw Error('workflow_hash_mismatch');
  if(workflow.id!=='DR32BufferQueueCheckV1' || workflow.active!==false || workflow.nodes.length!==3) throw Error('unexpected_workflow');
  const http=workflow.nodes.find(n=>n.type==='n8n-nodes-base.httpRequest');
  const query=JSON.parse(http?.parameters?.body || '{}').query;
  if(http?.parameters?.url!=='https://api.buffer.com' || !/^query DropRateBufferQueue\b/.test(query) || /\bmutation\b/.test(query)) throw Error('unexpected_request');
  const root=mkdtempSync(join(tmpdir(),'drop-rate-n8n-smoke-'));
  const started=new Date().toISOString();
  let stage='import';
  try {
    const env=isolatedEnv(root);
    if(!env.BUFFER_API_KEY) throw Error('buffer_key_missing');
    const trigger=workflow.nodes.find(n=>n.type==='n8n-nodes-base.executeWorkflowTrigger');
    if(!trigger) throw Error('trigger_missing');
    trigger.type='n8n-nodes-base.manualTrigger'; trigger.typeVersion=1; trigger.parameters={};
    const file=join(root,'workflow.json');
    writeFileSync(file,JSON.stringify(workflow),{mode:0o600});
    const execute=args=>spawnSync('n8n',args,{env,encoding:'utf8',timeout:180000,maxBuffer:8*1024*1024,stdio:['ignore','pipe','pipe']});
    const imported=execute(['import:workflow',`--input=${file}`]);
    if(imported.status!==0 || imported.error) throw Error('cli_import_failed');
    stage='execute';
    const result=execute(['execute',`--id=${workflow.id}`,'--rawOutput']);
    if(result.status!==0 || result.error) throw Error('cli_execution_failed');
    const summary=extractSummary(result.stdout,workflow.nodes.at(-1).name);
    const report={test:'DR32_BUFFER_N8N_RUNTIME',started,finished:new Date().toISOString(),workflow_sha256:expectedHash,isolated_database:true,...summary};
    console.log('DROP_RATE_N8N_SMOKE '+JSON.stringify(report));
    return report;
  } catch(error) {
    const allowed=['buffer_key_missing','trigger_missing','cli_import_failed','cli_execution_failed','execution_not_verified','summary_missing'];
    const reason=allowed.includes(error.message)?error.message:'runtime_test_failed';
    console.log('DROP_RATE_N8N_SMOKE '+JSON.stringify({test:'DR32_BUFFER_N8N_RUNTIME',ok:false,stage,reason,publishing_verified:false}));
    return {ok:false,stage,reason};
  } finally {
    // root is the exact mkdtemp return value, never a provider/input path.
    rmSync(root,{recursive:true,force:true});
  }
}
