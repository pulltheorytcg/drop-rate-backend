'use strict';

// Explicit, pre-start upgrade of four already-observed inactive workflows.
// Supported n8n CLI writes the workflow/history rows; SQLite is read-only here.
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { createHash } = require('node:crypto');
const { spawn, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const inspector = require('./inspect-stored-metadata.cjs');
const PLAN = require('./control-plane-upgrade-20261027.json');
const FLAG = 'DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT';
const PUBLISH_FLAG = 'DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_REVIEWED_UPGRADE';
const SOURCE_DIRECTORY = path.resolve(__dirname, '..', 'workflows');
const EXPECTED_IDS = ['DR90GlobalErrorV1', 'DR92RuntimeHeartbeatV1', 'DR93ObjectStorageHealthV1', 'DR94R2ApprovedMediaMirrorV1'];
const HEALTH_IDS = ['DR92RuntimeHeartbeatV1', 'DR93ObjectStorageHealthV1'];
const MEDIA_IDS = ['DR94R2ApprovedMediaMirrorV1'];
const SAFE_CODES = new Set(['PLAN_INVALID', 'SOURCE_DRIFT', 'STORED_DRIFT', 'WORKFLOW_NOT_INACTIVE',
  'SOURCE_NOT_VERIFIED', 'DRAFT_HISTORY_UNVERIFIED', 'DATABASE_UNAVAILABLE', 'DATABASE_CONFIGURATION_UNSUPPORTED',
  'INSTANCE_RUNNING', 'OFFLINE_STATE_UNVERIFIED', 'RUNTIME_VERSION_MISMATCH', 'CLI_FAILED',
  'BACKUP_UNVERIFIED', 'BACKUP_LIMIT_EXCEEDED', 'LOCK_UNAVAILABLE', 'IMPORT_UNVERIFIED',
  'INVALID_OPERATOR_FLAG', 'UPGRADE_TIMEOUT', 'UPGRADE_OUTPUT_INVALID', 'OPERATION_UNVERIFIED',
  'PHASE_CONFLICT', 'ERROR_HANDLER_UNPUBLISHED', 'HEALTH_SCHEDULES_UNPUBLISHED', 'PUBLICATION_UNVERIFIED']);
const exec = promisify(execFile);

function fail(code) { const error = new Error(code); error.safeCode = code; throw error; }
function result(status, extra = {}) {
  return { event: EVENT, schema_version: 1, plan_id: PLAN.plan_id, status, ...extra };
}
function safeFailure(error, phase, backup) {
  return result('BLOCKED', { phase, reason: SAFE_CODES.has(error?.safeCode)
    ? error.safeCode : 'OPERATION_UNVERIFIED', ...(backup ? { backup } : {}) });
}
function validatePlan() {
  if (PLAN.schema_version !== 1 || PLAN.n8n_version !== '2.32.6'
    || PLAN.error_workflow.id !== 'DR90GlobalErrorV1'
    || PLAN.targets.map(x => x.id).join(',') !== EXPECTED_IDS.join(',')
    || PLAN.targets[0].source_sha256 !== PLAN.error_workflow.sha256
    || !/^[a-z0-9-]{1,80}$/.test(PLAN.plan_id)
    || ![PLAN.error_workflow.sha256, ...PLAN.targets.flatMap(x => [x.source_sha256, x.observed_stored_sha256])]
      .every(x => /^[a-f0-9]{64}$/.test(x))) fail('PLAN_INVALID');
}
function readSources(sourceDirectory) {
  validatePlan();
  const sources = new Map();
  // DR91 is inspected separately, but has no observed production definition in
  // this plan. Neither read-only inspection nor a source fix authorizes its write.
  for (const [id, file] of inspector.WORKFLOWS.filter(([id]) => EXPECTED_IDS.includes(id))) {
    const filename = path.join(sourceDirectory, file);
    const stat = fs.lstatSync(filename);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1024 * 1024) fail('SOURCE_DRIFT');
    const source = JSON.parse(fs.readFileSync(filename, 'utf8'));
    const target = PLAN.targets.find(x => x.id === id);
    const expected = target.source_sha256;
    if (source.id !== id || source.active !== false || source.activeVersionId != null
      || inspector.definitionHash(source) !== expected) fail('SOURCE_DRIFT');
    if (id === PLAN.error_workflow.id) {
      if (source.settings?.errorWorkflow) fail('SOURCE_DRIFT');
    } else {
      if (source.settings?.errorWorkflow !== PLAN.error_workflow.id) fail('SOURCE_DRIFT');
    }
    const previous = structuredClone(source);
    delete previous.settings.errorWorkflow;
    const requests = previous.nodes.filter(node => node.type === 'n8n-nodes-base.httpRequest');
    if (requests.length !== 1 || requests[0].parameters.contentType !== 'raw'
      || requests[0].parameters.options?.response?.response?.responseFormat !== 'autodetect') fail('SOURCE_DRIFT');
    // Exactly undo the reviewed response parser repair and the three routing
    // links. The resulting bytes must match the actually observed old hash.
    requests[0].parameters.options.response.response.responseFormat = 'json';
    if (inspector.definitionHash(previous) !== target.observed_stored_sha256) fail('SOURCE_DRIFT');
    sources.set(id, source);
  }
  return sources;
}
function readState(databasePath, sourceDirectory, prefix) {
  let db;
  try {
    const stat = fs.lstatSync(databasePath);
    if (!stat.isFile() || stat.isSymbolicLink()) fail('DATABASE_UNAVAILABLE');
    db = inspector.openDatabase(databasePath);
    db.exec('BEGIN');
    return inspector.inspectDatabase(db, sourceDirectory, prefix).workflows
      .filter(item => EXPECTED_IDS.includes(item.id));
  } finally {
    try { db?.exec('ROLLBACK'); } catch {}
    try { db?.close(); } catch {}
  }
}
function assess(workflows, { requireCurrent = false, allowPublished = false } = {}) {
  const pending = [];
  if (!Array.isArray(workflows) || workflows.length !== 4) fail('STORED_DRIFT');
  for (const item of workflows) {
    if (item.status !== 'COMPLETE') fail('STORED_DRIFT');
    if (!allowPublished && (item.active !== false || item.published !== false)) fail('WORKFLOW_NOT_INACTIVE');
    if (allowPublished && ((item.active && !item.published)
      || (item.published && item.published_sha256 !== item.source_sha256))) fail('SOURCE_NOT_VERIFIED');
    const target = PLAN.targets.find(x => x.id === item.id);
    if (!target || item.source_sha256 !== target.source_sha256) fail('SOURCE_DRIFT');
    const expectedHandler = item.id === PLAN.error_workflow.id ? null : PLAN.error_workflow.id;
    if (item.stored_sha256 === target.source_sha256
      && item.errorWorkflow === expectedHandler) continue;
    if (requireCurrent) fail('SOURCE_NOT_VERIFIED');
    if (item.stored_sha256 !== target.observed_stored_sha256 || item.errorWorkflow !== null) fail('STORED_DRIFT');
    pending.push(item.id);
  }
  return pending;
}
function stateIdentity(workflows) {
  return JSON.stringify(workflows.map(x => [x.id, x.source_sha256, x.stored_sha256,
    x.errorWorkflow, x.active, x.published]));
}
function verifyDraftHistory(databasePath, prefix) {
  const db = inspector.openDatabase(databasePath);
  try {
    db.exec('BEGIN');
    for (const target of PLAN.targets) {
      const row = db.prepare('SELECT e.id, e.name, e.settings, h.nodes, h.connections, h.nodeGroups'
        + ' FROM "' + prefix + 'workflow_entity" e JOIN "' + prefix + 'workflow_history" h'
        + ' ON h.workflowId=e.id AND h.versionId=e.versionId WHERE e.id=?'
        + ' AND length(CAST(h.nodes AS BLOB))<=1048576'
        + ' AND length(CAST(h.connections AS BLOB))<=1048576 LIMIT 1').get(target.id);
      if (!row) fail('DRAFT_HISTORY_UNVERIFIED');
      const workflow = { id: row.id, name: row.name, nodes: JSON.parse(row.nodes),
        connections: JSON.parse(row.connections), settings: row.settings == null ? {} : JSON.parse(row.settings),
        nodeGroups: row.nodeGroups == null ? [] : JSON.parse(row.nodeGroups) };
      if (inspector.definitionHash(workflow) !== target.source_sha256) fail('DRAFT_HISTORY_UNVERIFIED');
    }
  } finally { try { db.exec('ROLLBACK'); } finally { db.close(); } }
}
async function digestFile(filename) {
  const hash = createHash('sha256');
  for await (const chunk of fs.createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}
async function createBackup(config, sourceDirectory, before) {
  const parent = path.join(path.dirname(config.databasePath), 'drop-rate-control-plane-backups');
  if (!fs.existsSync(parent)) fs.mkdirSync(parent, { mode: 0o700 });
  const parentStat = fs.lstatSync(parent);
  if (!parentStat.isDirectory() || parentStat.isSymbolicLink() || (parentStat.mode & 0o077)) fail('BACKUP_UNVERIFIED');
  const directory = fs.mkdtempSync(path.join(parent, PLAN.plan_id + '-'));
  fs.chmodSync(directory, 0o700);
  const filename = path.join(directory, 'database.sqlite');
  fs.closeSync(fs.openSync(filename, 'wx', 0o600));
  let source, copy;
  try {
    source = inspector.openDatabase(config.databasePath);
    const pages = source.prepare('PRAGMA page_count').get().page_count;
    const pageSize = source.prepare('PRAGMA page_size').get().page_size;
    if (pages * pageSize > 512 * 1024 * 1024) fail('BACKUP_LIMIT_EXCEEDED');
    await require('node:sqlite').backup(source, filename, { rate: 100 });
    source.close(); source = null;
    copy = inspector.openDatabase(filename);
    const check = copy.prepare('PRAGMA quick_check(1)').get();
    if (Object.values(check).join() !== 'ok') fail('BACKUP_UNVERIFIED');
    copy.close(); copy = null;
    const backedUp = readState(filename, sourceDirectory, config.tablePrefix);
    if (stateIdentity(backedUp) !== stateIdentity(before)) fail('BACKUP_UNVERIFIED');
    const handle = fs.openSync(filename, 'r');
    try { fs.fsyncSync(handle); } finally { fs.closeSync(handle); }
    const receipt = { id: path.basename(directory), verified: true,
      sha256: await digestFile(filename), size_bytes: fs.statSync(filename).size };
    fs.writeFileSync(path.join(directory, 'manifest.json'), JSON.stringify({
      plan_id: PLAN.plan_id, created_at: new Date().toISOString(), ...receipt,
      workflows: before.map(x => ({ id: x.id, stored_sha256: x.stored_sha256,
        active: x.active, published: x.published })),
    }, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    return { directory, receipt };
  } finally {
    try { source?.close(); } catch {}
    try { copy?.close(); } catch {}
  }
}
function ensureOffline(env) {
  return new Promise((resolve, reject) => {
    // n8n's server config uses N8N_PORT, not a generic platform PORT variable.
    const port = Number(env.N8N_PORT || 5678);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return reject({ safeCode: 'OFFLINE_STATE_UNVERIFIED' });
    const socket = net.createConnection({ host: '127.0.0.1', port });
    socket.setTimeout(500);
    socket.once('connect', () => { socket.destroy(); reject({ safeCode: 'INSTANCE_RUNNING' }); });
    socket.once('timeout', () => { socket.destroy(); reject({ safeCode: 'OFFLINE_STATE_UNVERIFIED' }); });
    socket.once('error', error => {
      socket.destroy();
      if (error.code === 'ECONNREFUSED') resolve();
      else reject({ safeCode: 'OFFLINE_STATE_UNVERIFIED' });
    });
  });
}
async function cli(args, env) {
  const childEnv = { ...env, N8N_DIAGNOSTICS_ENABLED: 'false',
    N8N_VERSION_NOTIFICATIONS_ENABLED: 'false', N8N_TEMPLATES_ENABLED: 'false' };
  delete childEnv.NODE_OPTIONS;
  try {
    return await exec('n8n', args, { env: childEnv, timeout: 25000,
      maxBuffer: 512 * 1024, killSignal: 'SIGKILL' });
  } catch { fail('CLI_FAILED'); }
}
async function applyUpgrade({ env = process.env, sourceDirectory = SOURCE_DIRECTORY,
  command = cli, offline = ensureOffline, makeBackup = createBackup } = {}) {
  let phase = 'PREFLIGHT', backup, lock, lockPath;
  try {
    if (env[FLAG] !== 'true') fail('INVALID_OPERATOR_FLAG');
    if ((env[PUBLISH_FLAG] && env[PUBLISH_FLAG] !== 'false')
      || env.DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT === 'true') fail('PHASE_CONFLICT');
    const config = inspector.runtimeConfig(env);
    if (config.reason) fail('DATABASE_CONFIGURATION_UNSUPPORTED');
    readSources(sourceDirectory);
    await offline(env);
    const before = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    const pending = assess(before);
    if (!pending.length) {
      verifyDraftHistory(config.databasePath, config.tablePrefix);
      return result('SOURCE_MATCH_VERIFIED', { changed_count: 0, workflows: before });
    }
    lockPath = path.join(path.dirname(config.databasePath), 'control-plane-upgrade.lock');
    try { lock = fs.openSync(lockPath, 'wx', 0o600); } catch { fail('LOCK_UNAVAILABLE'); }
    fs.writeFileSync(lock, PLAN.plan_id + '\n');
    if (stateIdentity(readState(config.databasePath, sourceDirectory, config.tablePrefix))
      !== stateIdentity(before)) fail('STORED_DRIFT');
    phase = 'VERSION';
    if ((await command(['--version'], env)).stdout.trim() !== PLAN.n8n_version) fail('RUNTIME_VERSION_MISMATCH');
    phase = 'BACKUP';
    const saved = await makeBackup(config, sourceDirectory, before);
    backup = saved.receipt;
    phase = 'RECHECK';
    await offline(env);
    const sources = readSources(sourceDirectory);
    const rechecked = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    assess(rechecked);
    if (stateIdentity(rechecked) !== stateIdentity(before)) fail('STORED_DRIFT');
    const input = path.join(saved.directory, 'reviewed-workflows.json');
    fs.writeFileSync(input, JSON.stringify(pending.map(id => sources.get(id))), { flag: 'wx', mode: 0o600 });
    phase = 'IMPORT';
    // One supported CLI transaction; explicit false never activates a trigger.
    await command(['import:workflow', '--input=' + input, '--activeState=false'], env);
    phase = 'READBACK';
    const after = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    assess(after, { requireCurrent: true });
    verifyDraftHistory(config.databasePath, config.tablePrefix);
    return result('SOURCE_MATCH_VERIFIED', { changed_count: pending.length, backup, workflows: after });
  } catch (error) {
    return safeFailure(error, phase, backup);
  } finally {
    if (lock !== undefined) {
      try { fs.closeSync(lock); } catch {}
      try { fs.unlinkSync(lockPath); } catch {}
    }
  }
}
async function applyPublication({ env = process.env, sourceDirectory = SOURCE_DIRECTORY,
  command = cli, offline = ensureOffline, makeBackup = createBackup } = {}) {
  let phase = 'PUBLICATION_PREFLIGHT', backup, lock, lockPath;
  try {
    const mode = env[PUBLISH_FLAG];
    if (!['error-handler', 'health-schedules', 'media-schedule'].includes(mode)) fail('INVALID_OPERATOR_FLAG');
    if (env[FLAG] === 'true' || env.DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT === 'true') fail('PHASE_CONFLICT');
    const config = inspector.runtimeConfig(env);
    if (config.reason) fail('DATABASE_CONFIGURATION_UNSUPPORTED');
    readSources(sourceDirectory);
    await offline(env);
    const before = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    assess(before, { requireCurrent: true, allowPublished: true });
    verifyDraftHistory(config.databasePath, config.tablePrefix);
    if (mode !== 'error-handler' && before.find(x => x.id === PLAN.error_workflow.id)?.published !== true) {
      fail('ERROR_HANDLER_UNPUBLISHED');
    }
    if (mode === 'media-schedule' && HEALTH_IDS.some(id => before.find(x => x.id === id)?.published !== true)) {
      fail('HEALTH_SCHEDULES_UNPUBLISHED');
    }
    const selected = mode === 'error-handler' ? [PLAN.error_workflow.id]
      : mode === 'health-schedules' ? HEALTH_IDS : MEDIA_IDS;
    const pending = selected.filter(id => !before.find(x => x.id === id)?.published);
    if (!pending.length) return result('PUBLICATION_VERIFIED', {
      publication_mode: mode, changed_count: 0, workflows: before });
    lockPath = path.join(path.dirname(config.databasePath), 'control-plane-upgrade.lock');
    try { lock = fs.openSync(lockPath, 'wx', 0o600); } catch { fail('LOCK_UNAVAILABLE'); }
    fs.writeFileSync(lock, PLAN.plan_id + '\n');
    phase = 'VERSION';
    if ((await command(['--version'], env)).stdout.trim() !== PLAN.n8n_version) fail('RUNTIME_VERSION_MISMATCH');
    phase = 'BACKUP';
    const saved = await makeBackup(config, sourceDirectory, before);
    backup = saved.receipt;
    phase = 'PUBLICATION_RECHECK';
    await offline(env);
    readSources(sourceDirectory);
    const rechecked = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    assess(rechecked, { requireCurrent: true, allowPublished: true });
    if (stateIdentity(rechecked) !== stateIdentity(before)) fail('STORED_DRIFT');
    for (const id of pending) {
      phase = 'PUBLISH';
      // These modes publish only the fixed reviewed IDs, never all workflows.
      await command(['publish:workflow', '--id=' + id], env);
      const checkpoint = readState(config.databasePath, sourceDirectory, config.tablePrefix);
      assess(checkpoint, { requireCurrent: true, allowPublished: true });
      if (checkpoint.find(x => x.id === id)?.published !== true) fail('PUBLICATION_UNVERIFIED');
    }
    return result('PUBLICATION_VERIFIED', { publication_mode: mode, changed_count: pending.length,
      backup, workflows: readState(config.databasePath, sourceDirectory, config.tablePrefix) });
  } catch (error) {
    return safeFailure(error, phase, backup);
  } finally {
    if (lock !== undefined) {
      try { fs.closeSync(lock); } catch {}
      try { fs.unlinkSync(lockPath); } catch {}
    }
  }
}
function verifyBeforePublish(env = process.env, sourceDirectory = SOURCE_DIRECTORY) {
  try {
    const config = inspector.runtimeConfig(env);
    if (config.reason) fail('DATABASE_CONFIGURATION_UNSUPPORTED');
    readSources(sourceDirectory);
    const workflows = readState(config.databasePath, sourceDirectory, config.tablePrefix);
    assess(workflows, { requireCurrent: true, allowPublished: true });
    if (workflows.find(x => x.id === PLAN.error_workflow.id)?.published !== true) fail('ERROR_HANDLER_UNPUBLISHED');
    if (HEALTH_IDS.some(id => workflows.find(x => x.id === id)?.published !== true)) fail('HEALTH_SCHEDULES_UNPUBLISHED');
    verifyDraftHistory(config.databasePath, config.tablePrefix);
    return result('SOURCE_MATCH_VERIFIED', { changed_count: 0, workflows });
  } catch (error) { return safeFailure(error, 'VERIFY'); }
}
function runBounded(mode, env = process.env) {
  return new Promise(resolve => {
    if (mode === '--apply' && (!env[FLAG] || env[FLAG] === 'false')) return resolve(result('DISABLED'));
    if (mode === '--apply' && env[FLAG] !== 'true') return resolve(safeFailure({ safeCode: 'INVALID_OPERATOR_FLAG' }, 'CONFIG'));
    if (mode === '--publish' && (!env[PUBLISH_FLAG] || env[PUBLISH_FLAG] === 'false')) return resolve(result('DISABLED'));
    if (!['--apply', '--publish', '--verify'].includes(mode)) return resolve(safeFailure({ safeCode: 'INVALID_OPERATOR_FLAG' }, 'CONFIG'));
    const child = spawn(process.execPath, ['--no-warnings', __filename, '--worker', mode], {
      env, detached: true, stdio: ['ignore', 'pipe', 'ignore'],
    });
    let output = '', finished = false;
    const finish = value => { if (!finished) { finished = true; clearTimeout(timer); resolve(value); } };
    const kill = () => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
    const timer = setTimeout(() => { kill(); finish(safeFailure({ safeCode: 'UPGRADE_TIMEOUT' }, 'WORKER')); }, 60000);
    child.stdout.on('data', chunk => {
      output += chunk.toString('utf8');
      if (Buffer.byteLength(output) > 65536) {
        kill(); finish(safeFailure({ safeCode: 'UPGRADE_OUTPUT_INVALID' }, 'WORKER'));
      }
    });
    child.once('error', () => finish(safeFailure(null, 'WORKER')));
    child.once('close', () => {
      try {
        const parsed = JSON.parse(output);
        if (parsed.event !== EVENT || parsed.schema_version !== 1 || parsed.plan_id !== PLAN.plan_id) throw new Error();
        finish(parsed);
      } catch { finish(safeFailure({ safeCode: 'UPGRADE_OUTPUT_INVALID' }, 'WORKER')); }
    });
  });
}
if (require.main === module) {
  const operation = process.argv[2] === '--worker'
    ? (process.argv[3] === '--verify' ? Promise.resolve(verifyBeforePublish())
      : process.argv[3] === '--publish' ? applyPublication() : applyUpgrade())
    : runBounded(process.argv[2] || '--apply');
  operation.then(value => {
    process.stdout.write(JSON.stringify(value) + '\n');
    if (!['SOURCE_MATCH_VERIFIED', 'PUBLICATION_VERIFIED', 'DISABLED'].includes(value.status)) process.exitCode = 1;
  }).catch(() => { process.stdout.write(JSON.stringify(safeFailure(null, 'WORKER')) + '\n'); process.exitCode = 1; });
}
module.exports = { PLAN, FLAG, PUBLISH_FLAG, readSources, readState, assess, createBackup, ensureOffline,
  applyUpgrade, applyPublication, verifyBeforePublish };
