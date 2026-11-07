'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { test, after } = require('node:test');
const inspector = require('../automation/n8n/ops/inspect-stored-metadata.cjs');
const core = require('../automation/n8n/ops/guarded-control-plane-upgrade.cjs');
const success = require('../automation/n8n/ops/guarded-success-receipt-upgrade.cjs');
const pause = require('../automation/n8n/ops/guarded-heartbeat-pause.cjs');
const ROOT = path.resolve(__dirname, '..');
const PRIVATE = 'PRIVATE_PAUSE_FIXTURE_MATERIAL';
const roots = [];
after(() => { for (const root of roots) fs.rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drop-rate-dr92-pause-'));
  roots.push(root); fs.mkdirSync(path.join(root, '.n8n'));
  const sourceDirectory = path.join(root, 'workflows'); fs.mkdirSync(sourceDirectory);
  const databasePath = path.join(root, '.n8n/database.sqlite');
  const db = new DatabaseSync(databasePath);
  db.exec('PRAGMA journal_mode=WAL; CREATE TABLE workflow_entity(id TEXT PRIMARY KEY,name TEXT,'
    + 'nodes TEXT,connections TEXT,settings TEXT,nodeGroups TEXT,versionId TEXT,active INTEGER,activeVersionId TEXT);'
    + 'CREATE TABLE workflow_history(workflowId TEXT,versionId TEXT,nodes TEXT,connections TEXT,nodeGroups TEXT);'
    + 'CREATE TABLE credentials_entity(id TEXT,name TEXT,type TEXT,data TEXT);'
    + 'CREATE TABLE shared_workflow(workflowId TEXT,projectId TEXT,role TEXT);');
  db.prepare('INSERT INTO credentials_entity VALUES (?,?,?,?)').run('fixture', 'Fixture', 'googleDriveOAuth2Api', PRIVATE);
  for (const [id, file] of inspector.WORKFLOWS) {
    const raw = fs.readFileSync(path.join(ROOT, 'automation/n8n/workflows', file), 'utf8');
    fs.writeFileSync(path.join(sourceDirectory, file), raw);
    const value = JSON.parse(raw);
    if (id === success.PLAN.id) value.nodes.find(node => node.type === 'n8n-nodes-base.httpRequest')
      .parameters.options.response.response.responseFormat = 'json';
    const active = ['DR90GlobalErrorV1', pause.TARGET, 'DR93ObjectStorageHealthV1'].includes(id);
    const version = 'current-' + id;
    db.prepare('INSERT INTO workflow_entity VALUES (?,?,?,?,?,?,?,?,?)').run(id, value.name,
      JSON.stringify(value.nodes), JSON.stringify(value.connections), JSON.stringify(value.settings), '[]',
      version, active ? 1 : 0, active ? version : null);
    for (const history of ['historical-' + id, version]) {
      db.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(id, history,
        JSON.stringify(value.nodes), JSON.stringify(value.connections), '[]');
    }
    db.prepare('INSERT INTO shared_workflow VALUES (?,?,?)').run(id, 'original-project', 'workflow:owner');
  }
  const calls = [];
  const command = async args => {
    calls.push(args);
    if (args[0] === '--version') return { stdout: '2.32.6\n' };
    assert.deepEqual(args, ['unpublish:workflow', '--id=DR92RuntimeHeartbeatV1']);
    db.prepare('UPDATE workflow_entity SET active=0,activeVersionId=NULL WHERE id=?').run(pause.TARGET);
    return { stdout: PRIVATE, stderr: PRIVATE };
  };
  const env = { N8N_USER_FOLDER: root, [pause.FLAG]: 'true' };
  return { root, db, databasePath, sourceDirectory, env, calls,
    options: { env, sourceDirectory, command, offline: async () => {} } };
}
const others = db => db.prepare('SELECT * FROM workflow_entity WHERE id<>? ORDER BY id').all(pause.TARGET);
const history = db => db.prepare('SELECT * FROM workflow_history ORDER BY workflowId,versionId').all();
const owners = db => db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId,projectId').all();

test('pause is default-off and accepts only the exact explicit operator flag', async () => {
  assert.equal((await pause.runBounded({})).status, 'DISABLED');
  assert.equal((await pause.runBounded({ [pause.FLAG]: 'false' })).status, 'DISABLED');
  assert.equal((await pause.runBounded({ [pause.FLAG]: '1' })).reason, 'INVALID_OPERATOR_FLAG');
  assert.equal(pause.TARGET, 'DR92RuntimeHeartbeatV1');
});

test('exact one-ID pause verifies backup and preserves every other entity, ownership and history; retry is a no-op', async () => {
  const f = fixture();
  try {
    const before = { others: others(f.db), history: history(f.db), owners: owners(f.db) };
    const result = await pause.apply(f.options);
    assert.equal(result.status, 'PAUSE_VERIFIED'); assert.equal(result.changed_count, 1);
    assert.equal(result.backup.verified, true); assert.ok(!JSON.stringify(result).includes(PRIVATE));
    const target = result.workflows.find(x => x.id === pause.TARGET);
    assert.equal(target.active, false); assert.equal(target.published, false); assert.equal(target.source_matches_stored, true);
    assert.deepEqual(others(f.db), before.others); assert.deepEqual(history(f.db), before.history);
    assert.deepEqual(owners(f.db), before.owners);
    const filename = path.join(path.dirname(f.databasePath), 'drop-rate-control-plane-backups', result.backup.id, 'database.sqlite');
    const backup = inspector.openDatabase(filename);
    assert.equal(backup.prepare('SELECT active FROM workflow_entity WHERE id=?').get(pause.TARGET).active, 1);
    assert.deepEqual(others(backup), before.others); assert.deepEqual(history(backup), before.history);
    assert.deepEqual(owners(backup), before.owners);
    assert.equal(backup.prepare('SELECT data FROM credentials_entity').get().data, PRIVATE); backup.close();
    const count = f.calls.length;
    assert.equal((await pause.apply(f.options)).changed_count, 0); assert.equal(f.calls.length, count);
    assert.deepEqual(f.calls.filter(x => x[0] !== '--version'), [['unpublish:workflow', '--id=DR92RuntimeHeartbeatV1']]);
  } finally { f.db.close(); }
});

test('source, stored and published drift or missing history block before CLI writes', async () => {
  for (const change of ['source', 'stored', 'published', 'history']) {
    const f = fixture();
    try {
      if (change === 'source') {
        const file = path.join(f.sourceDirectory, 'dr-92-runtime-heartbeat.json');
        fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace('autodetect', 'json'));
      }
      if (change === 'stored') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{}', pause.TARGET);
      if (change === 'published') f.db.prepare('UPDATE workflow_entity SET activeVersionId=? WHERE id=?').run('missing', pause.TARGET);
      if (change === 'history') f.db.prepare('DELETE FROM workflow_history WHERE workflowId=?').run('DR94R2ApprovedMediaMirrorV1');
      const result = await pause.apply(f.options);
      assert.equal(result.status, 'BLOCKED', change); assert.equal(f.calls.length, 0);
    } finally { f.db.close(); }
  }
});

test('failed backup or drift during backup cannot reach unpublish', async () => {
  for (const drift of [false, true]) {
    const f = fixture();
    try {
      const makeBackup = async (...args) => {
        if (!drift) throw { safeCode: 'BACKUP_UNVERIFIED', message: PRIVATE };
        const backup = await core.createBackup(...args);
        f.db.prepare('UPDATE workflow_entity SET active=0,activeVersionId=NULL WHERE id=?').run('DR93ObjectStorageHealthV1');
        return backup;
      };
      const result = await pause.apply({ ...f.options, makeBackup });
      assert.equal(result.status, 'BLOCKED'); assert.ok(!JSON.stringify(result).includes(PRIVATE));
      assert.equal(f.calls.filter(x => x[0] === 'unpublish:workflow').length, 0);
    } finally { f.db.close(); }
  }
});

test('readback rejects an unverified pause and any changed protected publication state', async () => {
  for (const failure of ['not-paused', 'other-workflow']) {
    const f = fixture();
    try {
      const command = async args => {
        if (args[0] === '--version') return f.options.command(args);
        if (failure === 'not-paused') return { stdout: PRIVATE };
        const value = await f.options.command(args);
        f.db.prepare('UPDATE workflow_entity SET active=0,activeVersionId=NULL WHERE id=?').run('DR93ObjectStorageHealthV1');
        return value;
      };
      const result = await pause.apply({ ...f.options, command });
      assert.equal(result.status, 'BLOCKED');
      assert.equal(result.reason, failure === 'not-paused' ? 'PAUSE_UNVERIFIED' : 'PROTECTED_STATE_CHANGED');
    } finally { f.db.close(); }
  }
});

test('pause conflicts with all publication/upgrade phases and respects their shared lock', async () => {
  const f = fixture();
  try {
    for (const flag of [core.FLAG, core.PUBLISH_FLAG, success.FLAG, success.PUBLISH_FLAG,
      'DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT']) {
      assert.equal((await pause.apply({ ...f.options, env: { ...f.env, [flag]: 'true' } })).reason, 'PHASE_CONFLICT');
    }
    assert.equal((await core.applyUpgrade({ ...f.options, env: { ...f.env, [core.FLAG]: 'true' } })).reason, 'PHASE_CONFLICT');
    assert.equal((await core.applyPublication({ ...f.options, env: { ...f.env, [core.PUBLISH_FLAG]: 'health-schedules' } })).reason, 'PHASE_CONFLICT');
    assert.equal((await success.apply({ ...f.options, env: { ...f.env, [success.FLAG]: 'true' } })).reason, 'PHASE_CONFLICT');
    const lock = path.join(path.dirname(f.databasePath), 'control-plane-upgrade.lock');
    fs.writeFileSync(lock, PRIVATE, { mode: 0o600 });
    assert.equal((await pause.apply(f.options)).reason, 'LOCK_UNAVAILABLE');
    assert.equal(fs.readFileSync(lock, 'utf8'), PRIVATE); assert.equal(f.calls.length, 0);
  } finally { f.db.close(); }
});
