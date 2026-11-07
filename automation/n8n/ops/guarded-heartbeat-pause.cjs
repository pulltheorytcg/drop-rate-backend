'use strict';

// Pause only the exact reviewed heartbeat, using the supported pinned CLI.
// This does not change workflow source/history, run a probe, or stop n8n.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const inspector = require('./inspect-stored-metadata.cjs');
const core = require('./guarded-control-plane-upgrade.cjs');
const FLAG = 'DROP_RATE_N8N_HEARTBEAT_PAUSE_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_HEARTBEAT_PAUSE';
const PLAN_ID = 'pause-dr92-heartbeat-20261027-v1';
const TARGET = 'DR92RuntimeHeartbeatV1';
const SOURCE_DIRECTORY = path.resolve(__dirname, '..', 'workflows');
const SAFE_CODES = new Set(['PLAN_INVALID', 'SOURCE_DRIFT', 'STORED_DRIFT', 'SOURCE_NOT_VERIFIED',
  'DRAFT_HISTORY_UNVERIFIED', 'DATABASE_UNAVAILABLE', 'DATABASE_CONFIGURATION_UNSUPPORTED',
  'INSTANCE_RUNNING', 'OFFLINE_STATE_UNVERIFIED', 'RUNTIME_VERSION_MISMATCH', 'CLI_FAILED',
  'BACKUP_UNVERIFIED', 'BACKUP_LIMIT_EXCEEDED', 'LOCK_UNAVAILABLE', 'INVALID_OPERATOR_FLAG',
  'PAUSE_TIMEOUT', 'PAUSE_OUTPUT_INVALID', 'OPERATION_UNVERIFIED', 'PHASE_CONFLICT',
  'PAUSE_UNVERIFIED', 'PROTECTED_STATE_CHANGED']);

function fail(code) { const error = new Error(code); error.safeCode = code; throw error; }
function report(status, extra = {}) {
  return { event: EVENT, schema_version: 1, plan_id: PLAN_ID, workflow_id: TARGET, status, ...extra };
}
function blocked(error, phase, backup) {
  return report('BLOCKED', { phase, reason: SAFE_CODES.has(error?.safeCode)
    ? error.safeCode : 'OPERATION_UNVERIFIED', ...(backup ? { backup } : {}) });
}
function assess(workflows) {
  core.assess(workflows, { requireCurrent: true, allowPublished: true });
  const target = workflows.find(item => item.id === TARGET);
  if (!target) fail('STORED_DRIFT');
  return target;
}
async function apply({ env = process.env, sourceDirectory = SOURCE_DIRECTORY,
  command = core.cli, offline = core.ensureOffline, makeBackup = core.createBackup } = {}) {
  let phase = 'PREFLIGHT', backup, lock, lockPath;
  try {
    if (env[FLAG] !== 'true') fail('INVALID_OPERATOR_FLAG');
    const conflicts = [core.FLAG, core.PUBLISH_FLAG, 'DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT',
      'DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT', 'DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT'];
    if (conflicts.some(key => env[key] && env[key] !== 'false')) fail('PHASE_CONFLICT');
    const config = inspector.runtimeConfig(env);
    if (config.reason) fail('DATABASE_CONFIGURATION_UNSUPPORTED');
    core.readSources(sourceDirectory);
    await offline(env);
    const read = () => core.readState(config.databasePath, sourceDirectory, config.tablePrefix);
    const before = read();
    const target = assess(before);
    core.verifyDraftHistory(config.databasePath, config.tablePrefix);
    if (!target.active && !target.published) return report('PAUSE_VERIFIED', { changed_count: 0, workflows: before });
    lockPath = path.join(path.dirname(config.databasePath), 'control-plane-upgrade.lock');
    try { lock = fs.openSync(lockPath, 'wx', 0o600); } catch { fail('LOCK_UNAVAILABLE'); }
    fs.writeFileSync(lock, PLAN_ID + '\n');
    if (core.stateIdentity(read()) !== core.stateIdentity(before)) fail('STORED_DRIFT');
    phase = 'VERSION';
    if ((await command(['--version'], env)).stdout.trim() !== '2.32.6') fail('RUNTIME_VERSION_MISMATCH');
    phase = 'BACKUP';
    const saved = await makeBackup(config, sourceDirectory, before, { planId: PLAN_ID });
    backup = saved.receipt;
    phase = 'RECHECK';
    await offline(env);
    core.readSources(sourceDirectory);
    const checked = read(); assess(checked);
    if (core.stateIdentity(checked) !== core.stateIdentity(before)) fail('STORED_DRIFT');
    core.verifyDraftHistory(config.databasePath, config.tablePrefix);
    phase = 'UNPUBLISH';
    await command(['unpublish:workflow', '--id=' + TARGET], env);
    phase = 'READBACK';
    const after = read(); const paused = assess(after);
    core.verifyDraftHistory(config.databasePath, config.tablePrefix);
    if (paused.active !== false || paused.published !== false) fail('PAUSE_UNVERIFIED');
    const protectedRows = rows => rows.filter(item => item.id !== TARGET);
    if (core.stateIdentity(protectedRows(after)) !== core.stateIdentity(protectedRows(before))) {
      fail('PROTECTED_STATE_CHANGED');
    }
    return report('PAUSE_VERIFIED', { changed_count: 1, backup, workflows: after });
  } catch (error) { return blocked(error, phase, backup); }
  finally {
    if (lock !== undefined) {
      try { fs.closeSync(lock); } catch {}
      try { fs.unlinkSync(lockPath); } catch {}
    }
  }
}
function runBounded(env = process.env) {
  return new Promise(resolve => {
    if (!env[FLAG] || env[FLAG] === 'false') return resolve(report('DISABLED'));
    if (env[FLAG] !== 'true') return resolve(blocked({ safeCode: 'INVALID_OPERATOR_FLAG' }, 'CONFIG'));
    const child = spawn(process.execPath, ['--no-warnings', __filename, '--worker'],
      { env, detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '', finished = false;
    const finish = value => { if (!finished) { finished = true; clearTimeout(timer); resolve(value); } };
    const kill = () => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
    const timer = setTimeout(() => { kill(); finish(blocked({ safeCode: 'PAUSE_TIMEOUT' }, 'WORKER')); }, 60000);
    child.stdout.on('data', chunk => {
      output += chunk.toString('utf8');
      if (Buffer.byteLength(output) > 65536) { kill(); finish(blocked({ safeCode: 'PAUSE_OUTPUT_INVALID' }, 'WORKER')); }
    });
    child.once('error', () => finish(blocked(null, 'WORKER')));
    child.once('close', () => {
      try {
        const value = JSON.parse(output);
        if (value.event !== EVENT || value.schema_version !== 1 || value.plan_id !== PLAN_ID) throw new Error();
        finish(value);
      } catch { finish(blocked({ safeCode: 'PAUSE_OUTPUT_INVALID' }, 'WORKER')); }
    });
  });
}
if (require.main === module) {
  (process.argv[2] === '--worker' ? apply() : runBounded()).then(value => {
    process.stdout.write(JSON.stringify(value) + '\n');
    if (!['PAUSE_VERIFIED', 'DISABLED'].includes(value.status)) process.exitCode = 1;
  }).catch(() => { process.stdout.write(JSON.stringify(blocked(null, 'WORKER')) + '\n'); process.exitCode = 1; });
}
module.exports = { FLAG, TARGET, PLAN_ID, assess, apply, runBounded };
