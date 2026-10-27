'use strict';
// Only the pinned, --network none CI container runs this real-import smoke.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { promisify } = require('node:util');
const exec = promisify(require('node:child_process').execFile);
const inspector = require('/opt/drop-rate/ops/inspect-stored-metadata.cjs');
const upgrade = require('/opt/drop-rate/ops/guarded-control-plane-upgrade.cjs');
const SCRIPT = '/opt/drop-rate/ops/guarded-control-plane-upgrade.cjs';
const SOURCES = '/opt/drop-rate/workflows';
let stage = 'PREFLIGHT';
let operatorFailure = null;

(async () => {
  assert.equal(process.env.DROP_RATE_UPGRADE_CI_ISOLATED, 'true');
  assert.equal(process.env.RAILWAY_PROJECT_ID, undefined);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drop-rate-upgrade-native-ci-'));
  fs.chmodSync(root, 0o700);
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (key.startsWith('DB_') || key.startsWith('DROP_RATE_')) delete env[key];
  Object.assign(env, { DB_TYPE: 'sqlite', DB_SQLITE_DATABASE: path.join(root, 'database.sqlite'),
    N8N_USER_FOLDER: root, N8N_ENCRYPTION_KEY: crypto.randomBytes(32).toString('hex'),
    N8N_DIAGNOSTICS_ENABLED: 'false', N8N_VERSION_NOTIFICATIONS_ENABLED: 'false',
    N8N_TEMPLATES_ENABLED: 'false', N8N_PORT: '5678' });
  const cli = args => exec('n8n', args, { env, timeout: 60000, maxBuffer: 1024 * 1024 });
  const operator = async (operation = '--apply') => {
    try {
      const answer = await exec(process.execPath, ['--no-warnings', SCRIPT, operation],
        { env, timeout: 70000, maxBuffer: 65536 });
      return JSON.parse(answer.stdout);
    } catch (error) {
      // Only fixed helper categories may escape; never print raw CLI output.
      try {
        const report = JSON.parse(error.stdout);
        if (report.event === 'DROP_RATE_N8N_REVIEWED_UPGRADE' && report.status === 'BLOCKED'
          && /^[A-Z_]{1,40}$/.test(report.reason) && /^[A-Z_]{1,40}$/.test(report.phase)) {
          operatorFailure = { phase: report.phase, reason: report.reason };
        }
      } catch { /* The fixed outer stage still identifies the failed check. */ }
      throw error;
    }
  };
  try {
    stage = 'VERSION';
    assert.equal((await cli(['--version'])).stdout.trim(), '2.32.6');
    stage = 'SEED_OBSERVED_DEFINITIONS';
    const prior = inspector.WORKFLOWS.map(([id, file]) => {
      const workflow = JSON.parse(fs.readFileSync(path.join(SOURCES, file), 'utf8'));
      delete workflow.settings.errorWorkflow;
      const expected = id === upgrade.PLAN.error_workflow.id ? upgrade.PLAN.error_workflow.sha256
        : upgrade.PLAN.targets.find(x => x.id === id).observed_stored_sha256;
      assert.equal(inspector.definitionHash(workflow), expected);
      return workflow;
    });
    const seed = path.join(root, 'observed-workflows.json');
    fs.writeFileSync(seed, JSON.stringify(prior), { mode: 0o600 });
    await cli(['import:workflow', '--input=' + seed, '--activeState=false']);
    const beforeDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    const ownership = beforeDb.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all();
    beforeDb.close();
    env[upgrade.FLAG] = 'true';
    stage = 'INACTIVE_UPGRADE';
    const changed = await operator();
    assert.equal(changed.status, 'SOURCE_MATCH_VERIFIED');
    assert.equal(changed.changed_count, 3);
    assert.ok(changed.workflows.every(x => x.source_matches_stored && !x.active && !x.published));
    stage = 'BACKUP_AND_OWNERSHIP_READBACK';
    const backupFile = path.join(root, 'drop-rate-control-plane-backups', changed.backup.id, 'database.sqlite');
    const copy = inspector.openDatabase(backupFile);
    const saved = inspector.inspectDatabase(copy, SOURCES);
    for (const target of upgrade.PLAN.targets) {
      assert.equal(saved.workflows.find(x => x.id === target.id).stored_sha256, target.observed_stored_sha256);
    }
    copy.close();
    const afterDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.deepEqual(afterDb.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all(), ownership);
    const historyCount = afterDb.prepare('SELECT count(*) AS count FROM workflow_history').get().count;
    afterDb.close();
    stage = 'IDEMPOTENT_RETRY';
    const repeated = await operator();
    assert.equal(repeated.changed_count, 0);
    const repeatedDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.equal(repeatedDb.prepare('SELECT count(*) AS count FROM workflow_history').get().count, historyCount);
    repeatedDb.close();
    console.log('PASS: pinned n8n 2.32.6 real importer upgraded exactly three inactive definitions, preserved ownership, verified SQLite backup and made retry a no-op');

    // Publication is exercised only in this disposable, network-isolated DB.
    env[upgrade.FLAG] = 'false';
    env[upgrade.PUBLISH_FLAG] = 'error-handler';
    stage = 'PUBLISH_ERROR_HANDLER';
    const handler = await operator('--publish');
    assert.equal(handler.status, 'PUBLICATION_VERIFIED');
    assert.equal(handler.workflows.filter(x => x.published).length, 1);
    assert.equal(handler.workflows.find(x => x.id === upgrade.PLAN.error_workflow.id).source_matches_published, true);
    env[upgrade.PUBLISH_FLAG] = 'health-schedules';
    stage = 'PUBLISH_HEALTH_SCHEDULES';
    const health = await operator('--publish');
    assert.equal(health.status, 'PUBLICATION_VERIFIED');
    assert.equal(health.changed_count, 2);
    assert.deepEqual(health.workflows.filter(x => x.published).map(x => x.id), [
      'DR90GlobalErrorV1', 'DR92RuntimeHeartbeatV1', 'DR93ObjectStorageHealthV1']);
    assert.equal(health.workflows.find(x => x.id === 'DR94R2ApprovedMediaMirrorV1').published, false);
    env[upgrade.PUBLISH_FLAG] = 'media-schedule';
    stage = 'PUBLISH_MEDIA_SCHEDULE';
    const media = await operator('--publish');
    assert.equal(media.status, 'PUBLICATION_VERIFIED');
    assert.equal(media.changed_count, 1);
    assert.ok(media.workflows.every(x => x.published && x.source_matches_published));
    console.log('PASS: separate pinned-version publication verified exact DR90, then health schedules, then approved media; no workflow executions or external requests');
  } finally {
    // Only this newly created disposable CI directory is removed.
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch(() => {
  console.error(JSON.stringify({ status: 'FAILED', smoke: 'pinned-control-plane-upgrade', stage,
    ...(operatorFailure ? { operator_failure: operatorFailure } : {}) }));
  process.exitCode = 1;
});
