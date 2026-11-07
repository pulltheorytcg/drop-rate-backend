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
const success = require('/opt/drop-rate/ops/guarded-success-receipt-upgrade.cjs');
const pause = require('/opt/drop-rate/ops/guarded-heartbeat-pause.cjs');
const SCRIPT = '/opt/drop-rate/ops/guarded-control-plane-upgrade.cjs';
const SUCCESS_SCRIPT = '/opt/drop-rate/ops/guarded-success-receipt-upgrade.cjs';
const PAUSE_SCRIPT = '/opt/drop-rate/ops/guarded-heartbeat-pause.cjs';
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
  const operator = async (operation = '--apply', script = SCRIPT) => {
    try {
      const answer = await exec(process.execPath, ['--no-warnings', script, operation],
        { env, timeout: 70000, maxBuffer: 65536 });
      return JSON.parse(answer.stdout);
    } catch (error) {
      // Only fixed helper categories may escape; never print raw CLI output.
      try {
        const report = JSON.parse(error.stdout);
        if (['DROP_RATE_N8N_REVIEWED_UPGRADE', 'DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE',
          'DROP_RATE_N8N_HEARTBEAT_PAUSE'].includes(report.event)
          && report.status === 'BLOCKED'
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
      const target = upgrade.PLAN.targets.find(x => x.id === id);
      if (target) delete workflow.settings.errorWorkflow;
      workflow.nodes.find(node => node.type === 'n8n-nodes-base.httpRequest')
        .parameters.options.response.response.responseFormat = 'json';
      const expected = target ? target.observed_stored_sha256
        : '8f8b466d808171b2458fc0bcfc7a64a3ae8271221e084353d7eaf35198981296';
      assert.equal(inspector.definitionHash(workflow), expected);
      return workflow;
    });
    const seed = path.join(root, 'observed-workflows.json');
    fs.writeFileSync(seed, JSON.stringify(prior), { mode: 0o600 });
    await cli(['import:workflow', '--input=' + seed, '--activeState=false']);
    const beforeDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    const ownership = beforeDb.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all();
    const dr91Before = beforeDb.prepare('SELECT * FROM workflow_entity WHERE id=?').get('DR91SuccessReceiptV1');
    beforeDb.close();
    env[upgrade.FLAG] = 'true';
    stage = 'INACTIVE_UPGRADE';
    const changed = await operator();
    assert.equal(changed.status, 'SOURCE_MATCH_VERIFIED');
    assert.equal(changed.changed_count, 4);
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
    assert.deepEqual(afterDb.prepare('SELECT * FROM workflow_entity WHERE id=?').get('DR91SuccessReceiptV1'), dr91Before);
    const historyCount = afterDb.prepare('SELECT count(*) AS count FROM workflow_history').get().count;
    afterDb.close();
    stage = 'IDEMPOTENT_RETRY';
    const repeated = await operator();
    assert.equal(repeated.changed_count, 0);
    const repeatedDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.equal(repeatedDb.prepare('SELECT count(*) AS count FROM workflow_history').get().count, historyCount);
    repeatedDb.close();
    console.log('PASS: pinned n8n 2.32.6 real importer upgraded exactly four inactive definitions, preserved DR91 and ownership, verified SQLite backup and made retry a no-op');

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
    const finalDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.deepEqual(finalDb.prepare('SELECT * FROM workflow_entity WHERE id=?').get('DR91SuccessReceiptV1'), dr91Before);
    finalDb.close();
    console.log('PASS: separate pinned-version publication verified exact DR90, then health schedules, then approved media; no workflow executions or external requests');

    stage = 'DR91_PRESERVE_PUBLISHED_CORE';
    const readCore = db => db.prepare('SELECT * FROM workflow_entity WHERE id<>? ORDER BY id').all(success.PLAN.id);
    const readCoreHistory = db => db.prepare('SELECT * FROM workflow_history WHERE workflowId<>? ORDER BY workflowId,versionId')
      .all(success.PLAN.id);
    const coreDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    const publishedCore = readCore(coreDb);
    const publishedCoreHistory = readCoreHistory(coreDb);
    const priorCount = coreDb.prepare('SELECT count(*) AS count FROM workflow_history WHERE workflowId=?')
      .get(success.PLAN.id).count;
    coreDb.close();
    env[upgrade.PUBLISH_FLAG] = 'false';
    env[success.FLAG] = 'true';
    stage = 'DR91_ONE_ID_UPGRADE';
    const receiptUpgrade = await operator('--apply', SUCCESS_SCRIPT);
    assert.equal(receiptUpgrade.status, 'SOURCE_MATCH_VERIFIED');
    assert.equal(receiptUpgrade.changed_count, 1);
    assert.equal(receiptUpgrade.backup.verified, true);
    const dr91 = receiptUpgrade.workflows.find(x => x.id === success.PLAN.id);
    assert.equal(dr91.source_matches_stored, true);
    assert.equal(dr91.active, false); assert.equal(dr91.published, false);
    const dr91Db = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.deepEqual(readCore(dr91Db), publishedCore);
    assert.deepEqual(readCoreHistory(dr91Db), publishedCoreHistory);
    const repairedCount = dr91Db.prepare('SELECT count(*) AS count FROM workflow_history WHERE workflowId=?')
      .get(success.PLAN.id).count;
    assert.equal(repairedCount, priorCount + 1);
    dr91Db.close();
    stage = 'DR91_NO_OP_RETRY';
    assert.equal((await operator('--apply', SUCCESS_SCRIPT)).changed_count, 0);
    env[success.FLAG] = 'false';
    env[success.PUBLISH_FLAG] = 'true';
    stage = 'DR91_SEPARATE_PUBLICATION';
    const receiptPublication = await operator('--publish', SUCCESS_SCRIPT);
    assert.equal(receiptPublication.status, 'PUBLICATION_VERIFIED');
    assert.equal(receiptPublication.changed_count, 1);
    assert.equal(receiptPublication.workflows.find(x => x.id === success.PLAN.id).published_sha256,
      success.PLAN.source_sha256);
    assert.equal((await operator('--publish', SUCCESS_SCRIPT)).changed_count, 0);
    const verifiedDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.deepEqual(readCore(verifiedDb), publishedCore);
    assert.deepEqual(readCoreHistory(verifiedDb), publishedCoreHistory);
    assert.equal(verifiedDb.prepare('SELECT count(*) AS count FROM workflow_history WHERE workflowId=?')
      .get(success.PLAN.id).count, repairedCount);
    assert.equal(verifiedDb.prepare('SELECT count(*) AS count FROM execution_entity').get().count, 0);
    verifiedDb.close();
    console.log('PASS: pinned DR91 one-ID repair and separate publication preserved all published core rows, verified backup and made both retries no-ops; zero executions');

    stage = 'DR92_CAPTURE_PAUSE_BOUNDARY';
    const pauseDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    const otherEntities = db => db.prepare('SELECT * FROM workflow_entity WHERE id<>? ORDER BY id').all(pause.TARGET);
    const allHistory = db => db.prepare('SELECT * FROM workflow_history ORDER BY workflowId,versionId').all();
    const allOwnership = db => db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId,projectId').all();
    const preservedEntities = otherEntities(pauseDb);
    const preservedHistory = allHistory(pauseDb);
    const preservedOwnership = allOwnership(pauseDb);
    pauseDb.close();
    env[success.PUBLISH_FLAG] = 'false';
    env[pause.FLAG] = 'true';
    stage = 'DR92_EXACT_ONE_ID_PAUSE';
    const paused = await operator('--apply', PAUSE_SCRIPT);
    assert.equal(paused.status, 'PAUSE_VERIFIED'); assert.equal(paused.changed_count, 1);
    assert.equal(paused.backup.verified, true);
    const heartbeat = paused.workflows.find(x => x.id === pause.TARGET);
    assert.equal(heartbeat.active, false); assert.equal(heartbeat.published, false);
    assert.equal(heartbeat.source_matches_stored, true);
    assert.ok(paused.workflows.filter(x => x.id !== pause.TARGET).every(x => x.published && x.source_matches_published));
    stage = 'DR92_NO_OP_PAUSE_RETRY';
    assert.equal((await operator('--apply', PAUSE_SCRIPT)).changed_count, 0);
    const pausedDb = inspector.openDatabase(env.DB_SQLITE_DATABASE);
    assert.deepEqual(otherEntities(pausedDb), preservedEntities);
    assert.deepEqual(allHistory(pausedDb), preservedHistory);
    assert.deepEqual(allOwnership(pausedDb), preservedOwnership);
    assert.equal(pausedDb.prepare('SELECT count(*) AS count FROM execution_entity').get().count, 0);
    pausedDb.close();
    console.log('PASS: pinned DR92-only unpublish preserved all other entities, all history and ownership; verified backup, inactive readback and no-op retry; zero executions');
  } finally {
    // Only this newly created disposable CI directory is removed.
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch(() => {
  console.error(JSON.stringify({ status: 'FAILED', smoke: 'pinned-control-plane-upgrade', stage,
    ...(operatorFailure ? { operator_failure: operatorFailure } : {}) }));
  process.exitCode = 1;
});
