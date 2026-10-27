'use strict';

// Separate, opt-in repair/publication of the actually observed DR91 definition.
// Core workflows may already be published; preserve their exact reviewed state.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const inspector = require('./inspect-stored-metadata.cjs');
const core = require('./guarded-control-plane-upgrade.cjs');
const PLAN = require('./success-receipt-upgrade-20261027.json');
const FLAG = 'DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT';
const PUBLISH_FLAG = 'DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE';
const SOURCE_DIRECTORY = path.resolve(__dirname, '..', 'workflows');
const CORE_IDS = core.PLAN.targets.map(target => target.id);
const IDS = inspector.WORKFLOWS.map(([id]) => id);
const SAFE_CODES = new Set(['PLAN_INVALID', 'SOURCE_DRIFT', 'STORED_DRIFT', 'WORKFLOW_NOT_INACTIVE',
  'SOURCE_NOT_VERIFIED', 'DRAFT_HISTORY_UNVERIFIED', 'DATABASE_UNAVAILABLE', 'DATABASE_CONFIGURATION_UNSUPPORTED',
  'INSTANCE_RUNNING', 'OFFLINE_STATE_UNVERIFIED', 'RUNTIME_VERSION_MISMATCH', 'CLI_FAILED',
  'BACKUP_UNVERIFIED', 'BACKUP_LIMIT_EXCEEDED', 'LOCK_UNAVAILABLE', 'IMPORT_UNVERIFIED',
  'INVALID_OPERATOR_FLAG', 'UPGRADE_TIMEOUT', 'UPGRADE_OUTPUT_INVALID', 'OPERATION_UNVERIFIED',
  'PHASE_CONFLICT', 'ERROR_HANDLER_UNPUBLISHED', 'PUBLICATION_UNVERIFIED', 'CORE_STATE_CHANGED']);

function fail(code) { const error = new Error(code); error.safeCode = code; throw error; }
function report(status, extra = {}) {
  return { event: EVENT, schema_version: 1, plan_id: PLAN.plan_id, status, ...extra };
}
function blocked(error, phase, backup) {
  return report('BLOCKED', { phase, reason: SAFE_CODES.has(error?.safeCode)
    ? error.safeCode : 'OPERATION_UNVERIFIED', ...(backup ? { backup } : {}) });
}
function readSource(sourceDirectory = SOURCE_DIRECTORY) {
  if (PLAN.schema_version !== 1 || PLAN.n8n_version !== '2.32.6'
    || PLAN.id !== 'DR91SuccessReceiptV1'
    || !/^[a-z0-9-]{1,80}$/.test(PLAN.plan_id)
    || ![PLAN.observed_stored_sha256, PLAN.source_sha256].every(x => /^[a-f0-9]{64}$/.test(x))) fail('PLAN_INVALID');
  core.readSources(sourceDirectory);
  const filename = path.join(sourceDirectory, 'dr-91-success-receipt.json');
  const info = fs.lstatSync(filename);
  if (!info.isFile() || info.isSymbolicLink() || info.size > 1024 * 1024) fail('SOURCE_DRIFT');
  const source = JSON.parse(fs.readFileSync(filename, 'utf8'));
  if (source.id !== PLAN.id || source.active !== false || source.activeVersionId != null
    || source.settings?.errorWorkflow || inspector.definitionHash(source) !== PLAN.source_sha256) fail('SOURCE_DRIFT');
  const previous = structuredClone(source);
  const requests = previous.nodes.filter(node => node.type === 'n8n-nodes-base.httpRequest');
  if (requests.length !== 1 || requests[0].parameters.contentType !== 'raw'
    || requests[0].parameters.options?.response?.response?.responseFormat !== 'autodetect') fail('SOURCE_DRIFT');
  requests[0].parameters.options.response.response.responseFormat = 'json';
  if (inspector.definitionHash(previous) !== PLAN.observed_stored_sha256) fail('SOURCE_DRIFT');
  return source;
}
function coreState(rows) { return rows.filter(item => CORE_IDS.includes(item.id)); }
function assess(rows, { current = false, publication = false } = {}) {
  if (!Array.isArray(rows) || rows.length !== 5
    || new Set(rows.map(item => item.id)).size !== 5) fail('STORED_DRIFT');
  core.assess(coreState(rows), { requireCurrent: true, allowPublished: true });
  const item = rows.find(row => row.id === PLAN.id);
  if (!item || item.status !== 'COMPLETE' || item.source_sha256 !== PLAN.source_sha256
    || item.errorWorkflow !== null) fail('STORED_DRIFT');
  if (!publication && (item.active !== false || item.published !== false)) fail('WORKFLOW_NOT_INACTIVE');
  if (publication && ((item.active && !item.published)
    || (item.published && item.published_sha256 !== PLAN.source_sha256))) fail('SOURCE_NOT_VERIFIED');
  if (item.stored_sha256 === PLAN.source_sha256) return item;
  if (current) fail('SOURCE_NOT_VERIFIED');
  if (item.stored_sha256 !== PLAN.observed_stored_sha256) fail('STORED_DRIFT');
  return item;
}
function verifyHistory(config, item) {
  core.verifyDraftHistory(config.databasePath, config.tablePrefix);
  core.verifyDraftHistory(config.databasePath, config.tablePrefix,
    [{ id: PLAN.id, source_sha256: item.stored_sha256 }]);
}
function phaseFlags(env, publication) {
  const selected = publication ? PUBLISH_FLAG : FLAG;
  if (env[selected] !== 'true') fail('INVALID_OPERATOR_FLAG');
  const others = [publication ? FLAG : PUBLISH_FLAG, core.FLAG, core.PUBLISH_FLAG,
    'DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT', 'DROP_RATE_N8N_HEARTBEAT_PAUSE_ON_BOOT'];
  if (others.some(key => env[key] && env[key] !== 'false')) fail('PHASE_CONFLICT');
}
async function apply({ publication = false, env = process.env, sourceDirectory = SOURCE_DIRECTORY,
  command = core.cli, offline = core.ensureOffline, makeBackup = core.createBackup } = {}) {
  let phase = 'PREFLIGHT', backup, lock, lockPath;
  try {
    phaseFlags(env, publication);
    const config = inspector.runtimeConfig(env);
    if (config.reason) fail('DATABASE_CONFIGURATION_UNSUPPORTED');
    readSource(sourceDirectory);
    await offline(env);
    const read = () => core.readState(config.databasePath, sourceDirectory, config.tablePrefix, IDS);
    const before = read();
    const item = assess(before, { current: publication, publication });
    verifyHistory(config, item);
    if (publication && before.find(row => row.id === core.PLAN.error_workflow.id)?.published !== true) {
      fail('ERROR_HANDLER_UNPUBLISHED');
    }
    const finished = publication ? item.published : item.stored_sha256 === PLAN.source_sha256;
    const success = (count, workflows) => report(publication ? 'PUBLICATION_VERIFIED' : 'SOURCE_MATCH_VERIFIED', {
      ...(publication ? { publication_mode: 'success-receipt' } : {}), changed_count: count,
      ...(backup ? { backup } : {}), workflows,
    });
    if (finished) return success(0, before);
    lockPath = path.join(path.dirname(config.databasePath), 'control-plane-upgrade.lock');
    try { lock = fs.openSync(lockPath, 'wx', 0o600); } catch { fail('LOCK_UNAVAILABLE'); }
    fs.writeFileSync(lock, PLAN.plan_id + '\n');
    if (core.stateIdentity(read()) !== core.stateIdentity(before)) fail('STORED_DRIFT');
    phase = 'VERSION';
    if ((await command(['--version'], env)).stdout.trim() !== PLAN.n8n_version) fail('RUNTIME_VERSION_MISMATCH');
    phase = 'BACKUP';
    const saved = await makeBackup(config, sourceDirectory, before, { ids: IDS, planId: PLAN.plan_id });
    backup = saved.receipt;
    phase = 'RECHECK';
    await offline(env);
    const source = readSource(sourceDirectory);
    const rechecked = read();
    assess(rechecked, { current: publication, publication });
    if (core.stateIdentity(rechecked) !== core.stateIdentity(before)) fail('STORED_DRIFT');
    verifyHistory(config, item);
    if (publication) {
      phase = 'PUBLISH';
      await command(['publish:workflow', '--id=' + PLAN.id], env);
    } else {
      const input = path.join(saved.directory, 'reviewed-success-receipt.json');
      fs.writeFileSync(input, JSON.stringify([source]), { flag: 'wx', mode: 0o600 });
      phase = 'IMPORT';
      await command(['import:workflow', '--input=' + input, '--activeState=false'], env);
    }
    phase = 'READBACK';
    const after = read();
    const updated = assess(after, { current: true, publication });
    verifyHistory(config, updated);
    if (core.stateIdentity(coreState(after)) !== core.stateIdentity(coreState(before))) fail('CORE_STATE_CHANGED');
    if (publication && updated.published !== true) fail('PUBLICATION_UNVERIFIED');
    return success(1, after);
  } catch (error) { return blocked(error, phase, backup); }
  finally {
    if (lock !== undefined) {
      try { fs.closeSync(lock); } catch {}
      try { fs.unlinkSync(lockPath); } catch {}
    }
  }
}
function runBounded(mode = '--apply', env = process.env) {
  return new Promise(resolve => {
    if (!['--apply', '--publish'].includes(mode)) return resolve(blocked({ safeCode: 'INVALID_OPERATOR_FLAG' }, 'CONFIG'));
    const selected = mode === '--publish' ? PUBLISH_FLAG : FLAG;
    if (!env[selected] || env[selected] === 'false') return resolve(report('DISABLED'));
    if (env[selected] !== 'true') return resolve(blocked({ safeCode: 'INVALID_OPERATOR_FLAG' }, 'CONFIG'));
    const child = spawn(process.execPath, ['--no-warnings', __filename, '--worker', mode],
      { env, detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '', finished = false;
    const finish = value => { if (!finished) { finished = true; clearTimeout(timer); resolve(value); } };
    const kill = () => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
    const timer = setTimeout(() => { kill(); finish(blocked({ safeCode: 'UPGRADE_TIMEOUT' }, 'WORKER')); }, 60000);
    child.stdout.on('data', chunk => {
      output += chunk.toString('utf8');
      if (Buffer.byteLength(output) > 65536) { kill(); finish(blocked({ safeCode: 'UPGRADE_OUTPUT_INVALID' }, 'WORKER')); }
    });
    child.once('error', () => finish(blocked(null, 'WORKER')));
    child.once('close', () => {
      try {
        const value = JSON.parse(output);
        if (value.event !== EVENT || value.schema_version !== 1 || value.plan_id !== PLAN.plan_id) throw new Error();
        finish(value);
      } catch { finish(blocked({ safeCode: 'UPGRADE_OUTPUT_INVALID' }, 'WORKER')); }
    });
  });
}
if (require.main === module) {
  const operation = process.argv[2] === '--worker'
    ? apply({ publication: process.argv[3] === '--publish' }) : runBounded(process.argv[2]);
  operation.then(value => {
    process.stdout.write(JSON.stringify(value) + '\n');
    if (!['SOURCE_MATCH_VERIFIED', 'PUBLICATION_VERIFIED', 'DISABLED'].includes(value.status)) process.exitCode = 1;
  }).catch(() => { process.stdout.write(JSON.stringify(blocked(null, 'WORKER')) + '\n'); process.exitCode = 1; });
}
module.exports = { PLAN, FLAG, PUBLISH_FLAG, readSource, assess, apply, runBounded };
