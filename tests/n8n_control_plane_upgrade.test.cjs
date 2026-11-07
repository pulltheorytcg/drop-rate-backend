'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { createHash } = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const { test, after } = require('node:test');
const inspector = require('../automation/n8n/ops/inspect-stored-metadata.cjs');
const upgrade = require('../automation/n8n/ops/guarded-control-plane-upgrade.cjs');
const ROOT = path.resolve(__dirname, '..');
const roots = [];
const PRIVATE = 'DISPOSABLE_PRIVATE_FIXTURE_DATA';
after(() => { for (const root of roots) fs.rmSync(root, { recursive: true, force: true }); });

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drop-rate-upgrade-test-'));
  roots.push(root);
  fs.mkdirSync(path.join(root, '.n8n'));
  const databasePath = path.join(root, '.n8n', 'database.sqlite');
  const sourceDirectory = path.join(root, 'workflows');
  fs.mkdirSync(sourceDirectory);
  const db = new DatabaseSync(databasePath);
  db.exec('PRAGMA journal_mode=WAL; CREATE TABLE workflow_entity (id TEXT PRIMARY KEY, name TEXT,'
    + ' active INTEGER, activeVersionId TEXT, versionId TEXT, nodes TEXT, connections TEXT, settings TEXT, nodeGroups TEXT);'
    + 'CREATE TABLE workflow_history (workflowId TEXT, versionId TEXT, nodes TEXT, connections TEXT, nodeGroups TEXT, PRIMARY KEY(workflowId,versionId));'
    + 'CREATE TABLE credentials_entity (id TEXT PRIMARY KEY,name TEXT,type TEXT,data TEXT);'
    + 'CREATE TABLE shared_workflow (workflowId TEXT, projectId TEXT, role TEXT);'
    + 'CREATE TABLE unrelated_state (value TEXT);');
  db.prepare('INSERT INTO unrelated_state VALUES (?)').run(PRIVATE);
  db.prepare('INSERT INTO credentials_entity VALUES (?,?,?,?)').run('fixture', 'Fixture', 'googleDriveOAuth2Api', PRIVATE);
  for (const [id, file] of inspector.WORKFLOWS) {
    const original = fs.readFileSync(path.join(ROOT, 'automation/n8n/workflows', file), 'utf8');
    fs.writeFileSync(path.join(sourceDirectory, file), original);
    const old = JSON.parse(original);
    if (upgrade.PLAN.targets.some(target => target.id === id)) delete old.settings.errorWorkflow;
    old.nodes.find(node => node.type === 'n8n-nodes-base.httpRequest')
      .parameters.options.response.response.responseFormat = 'json';
    const version = 'old-' + id;
    db.prepare('INSERT INTO workflow_entity VALUES (?,?,0,NULL,?,?,?,?,?)').run(
      id, old.name, version, JSON.stringify(old.nodes), JSON.stringify(old.connections), JSON.stringify(old.settings), '[]');
    db.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(
      id, version, JSON.stringify(old.nodes), JSON.stringify(old.connections), '[]');
    db.prepare('INSERT INTO shared_workflow VALUES (?,?,?)').run(id, 'original-project', 'workflow:owner');
  }
  const calls = [];
  const command = async args => {
    calls.push(args);
    if (args[0] === '--version') return { stdout: '2.32.6\n' };
    if (args[0] === 'import:workflow') {
      assert.equal(args[2], '--activeState=false');
      const values = JSON.parse(fs.readFileSync(args[1].slice('--input='.length), 'utf8'));
      assert.deepEqual(values.map(x => x.id), upgrade.PLAN.targets.map(x => x.id));
      db.exec('BEGIN');
      for (const value of values) {
        const version = 'new-' + value.id;
        db.prepare('UPDATE workflow_entity SET name=?,nodes=?,connections=?,settings=?,nodeGroups=?,versionId=? WHERE id=?').run(
          value.name, JSON.stringify(value.nodes), JSON.stringify(value.connections), JSON.stringify(value.settings), '[]', version, value.id);
        db.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(
          value.id, version, JSON.stringify(value.nodes), JSON.stringify(value.connections), '[]');
      }
      db.exec('COMMIT');
      return { stdout: PRIVATE, stderr: PRIVATE };
    }
    if (args[0] === 'publish:workflow') {
      const id = args[1].slice('--id='.length);
      db.prepare('UPDATE workflow_entity SET active=1,activeVersionId=versionId WHERE id=?').run(id);
      return { stdout: PRIVATE };
    }
    throw new Error(PRIVATE);
  };
  const env = { [upgrade.FLAG]: 'true', N8N_USER_FOLDER: root };
  const options = { env, sourceDirectory, command, offline: async () => {} };
  return { root, databasePath, sourceDirectory, db, calls, env, options };
}

test('exact observed differences are the raw response parser repair and three DR90 links', () => {
  const sources = upgrade.readSources(path.join(ROOT, 'automation/n8n/workflows'));
  assert.equal(sources.size, 4);
  assert.equal(upgrade.PLAN.error_workflow.sha256, '84d3d6db4fefe07890da33bbae543dc69369826e56fe64cca20d69c43060a011');
  assert.equal(upgrade.PLAN.targets[0].observed_stored_sha256,
    'c804be158c4447fcf9d10104fc5a93730d8475a0e513d8d8ee9a24cb65fb4ab8');
  assert.ok(!sources.has('DR91SuccessReceiptV1'));
});

test('offline guard denies a live local server and ignores unrelated platform PORT', async t => {
  const server = net.createServer(socket => socket.end());
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  try {
    await assert.rejects(upgrade.ensureOffline({ N8N_PORT: String(port), PORT: '1' }),
      error => error.safeCode === 'INSTANCE_RUNNING');
    const connect = net.createConnection.bind(net);
    t.mock.method(net, 'createConnection', options => {
      assert.equal(options.host, '127.0.0.1');
      assert.equal(options.port, 5678);
      // Route the standard n8n socket to this test's reserved ephemeral listener.
      return connect({ ...options, port });
    });
    await assert.rejects(upgrade.ensureOffline({ PORT: '1' }),
      error => error.safeCode === 'INSTANCE_RUNNING');
    t.mock.restoreAll();
  } finally {
    t.mock.restoreAll();
    await new Promise(resolve => server.close(resolve));
  }
  await upgrade.ensureOffline({ N8N_PORT: String(port) });
});

test('WAL-aware backup precedes one inactive import, preserves unrelated state, and retry is a no-op', async () => {
  const f = fixture();
  try {
    assert.ok(fs.existsSync(f.databasePath + '-wal'));
    const ownership = f.db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all();
    const report = await upgrade.applyUpgrade(f.options);
    assert.equal(report.status, 'SOURCE_MATCH_VERIFIED');
    assert.equal(report.changed_count, 4);
    assert.equal(report.backup.verified, true);
    assert.ok(!JSON.stringify(report).includes(PRIVATE));
    assert.equal(f.calls.filter(x => x[0] === 'import:workflow').length, 1);
    for (const row of report.workflows) {
      assert.equal(row.source_matches_stored, true);
      assert.equal(row.active, false);
      assert.equal(row.published, false);
    }
    const directory = path.join(path.dirname(f.databasePath), 'drop-rate-control-plane-backups', report.backup.id);
    const backupFile = path.join(directory, 'database.sqlite');
    assert.equal(fs.statSync(directory).mode & 0o777, 0o700);
    assert.equal(fs.statSync(backupFile).mode & 0o777, 0o600);
    assert.equal(createHash('sha256').update(fs.readFileSync(backupFile)).digest('hex'), report.backup.sha256);
    const copy = inspector.openDatabase(backupFile);
    assert.equal(copy.prepare('SELECT data FROM credentials_entity').get().data, PRIVATE);
    assert.equal(copy.prepare('SELECT value FROM unrelated_state').get().value, PRIVATE);
    const old = inspector.inspectDatabase(copy, f.sourceDirectory);
    for (const target of upgrade.PLAN.targets) {
      assert.equal(old.workflows.find(x => x.id === target.id).stored_sha256, target.observed_stored_sha256);
    }
    copy.close();
    assert.deepEqual(f.db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all(), ownership);
    assert.equal(f.db.prepare('SELECT value FROM unrelated_state').get().value, PRIVATE);
    const calls = f.calls.length;
    const again = await upgrade.applyUpgrade(f.options);
    assert.equal(again.status, 'SOURCE_MATCH_VERIFIED');
    assert.equal(again.changed_count, 0);
    assert.equal(f.calls.length, calls);
  } finally { f.db.close(); }
});

test('unobserved drift, active or published state, and source drift block before backup/import', async () => {
  for (const change of ['drift', 'active', 'published', 'source', 'handler']) {
    const f = fixture();
    try {
      const target = upgrade.PLAN.targets[0].id;
      if (change === 'drift') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{"executionOrder":"v0"}', target);
      if (change === 'active') f.db.prepare('UPDATE workflow_entity SET active=1 WHERE id=?').run(target);
      if (change === 'published') f.db.prepare('UPDATE workflow_entity SET activeVersionId=versionId WHERE id=?').run(target);
      if (change === 'handler') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{"executionOrder":"v0"}', upgrade.PLAN.error_workflow.id);
      if (change === 'source') {
        const file = path.join(f.sourceDirectory,
          inspector.WORKFLOWS.find(([id]) => id === 'DR92RuntimeHeartbeatV1')[1]);
        const value = JSON.parse(fs.readFileSync(file));
        value.nodes[1].parameters.jsCode += PRIVATE;
        fs.writeFileSync(file, JSON.stringify(value));
      }
      const report = await upgrade.applyUpgrade(f.options);
      assert.equal(report.status, 'BLOCKED', change);
      assert.equal(f.calls.length, 0);
      assert.ok(!fs.existsSync(path.join(path.dirname(f.databasePath), 'drop-rate-control-plane-backups')));
      assert.ok(!JSON.stringify(report).includes(PRIVATE));
    } finally { f.db.close(); }
  }
});

test('DR91 is inspected but never imported or published by the four-ID repair plan', async () => {
  const f = fixture();
  try {
    const prior = f.db.prepare('SELECT * FROM workflow_entity WHERE id=?').get('DR91SuccessReceiptV1');
    const before = inspector.inspectDatabase(f.db, f.sourceDirectory).workflows.find(x => x.id === prior.id);
    assert.equal(before.stored_sha256,
      '8f8b466d808171b2458fc0bcfc7a64a3ae8271221e084353d7eaf35198981296');
    assert.equal(before.source_matches_stored, false);
    assert.equal(before.active, false);
    assert.equal(before.published, false);
    const upgraded = await upgrade.applyUpgrade(f.options);
    assert.equal(upgraded.status, 'SOURCE_MATCH_VERIFIED');
    assert.ok(!upgraded.workflows.some(x => x.id === prior.id));
    const env = { ...f.env, [upgrade.FLAG]: 'false', [upgrade.PUBLISH_FLAG]: 'error-handler' };
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).status, 'PUBLICATION_VERIFIED');
    assert.deepEqual(f.db.prepare('SELECT * FROM workflow_entity WHERE id=?').get(prior.id), prior);
    assert.equal(f.db.prepare('SELECT count(*) AS count FROM workflow_history WHERE workflowId=?')
      .get(prior.id).count, 1);
  } finally { f.db.close(); }
});

test('backup failure and changes during backup cannot reach the importer', async () => {
  for (const drift of [false, true]) {
    const f = fixture();
    try {
      const makeBackup = async (...args) => {
        if (!drift) throw { safeCode: 'BACKUP_UNVERIFIED', message: PRIVATE };
        const saved = await upgrade.createBackup(...args);
        f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{"executionOrder":"v0"}', upgrade.PLAN.targets[0].id);
        return saved;
      };
      const report = await upgrade.applyUpgrade({ ...f.options, makeBackup });
      assert.equal(report.status, 'BLOCKED');
      assert.ok(['BACKUP_UNVERIFIED', 'STORED_DRIFT'].includes(report.reason));
      assert.equal(f.calls.filter(x => x[0] === 'import:workflow').length, 0);
      assert.ok(!JSON.stringify(report).includes(PRIVATE));
    } finally { f.db.close(); }
  }
});

test('wrong runtime, import failure and incomplete history cannot produce source-match proof', async () => {
  for (const failure of ['runtime', 'import', 'history']) {
    const f = fixture();
    try {
      const command = async args => {
        if (failure === 'runtime') return { stdout: '0.0.0' };
        if (failure === 'import' && args[0] === 'import:workflow') throw new Error(PRIVATE);
        const value = await f.options.command(args);
        if (failure === 'history' && args[0] === 'import:workflow') {
          f.db.prepare('DELETE FROM workflow_history WHERE workflowId=?').run(upgrade.PLAN.targets[0].id);
        }
        return value;
      };
      const report = await upgrade.applyUpgrade({ ...f.options, command });
      assert.equal(report.status, 'BLOCKED');
      assert.ok(!JSON.stringify(report).includes(PRIVATE));
    } finally { f.db.close(); }
  }
});

test('publication is separate and requires exact handler, then health schedules, then media', async () => {
  const f = fixture();
  try {
    const env = { ...f.env, [upgrade.FLAG]: 'false', [upgrade.PUBLISH_FLAG]: 'error-handler' };
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).reason, 'SOURCE_NOT_VERIFIED');
    assert.equal((await upgrade.applyUpgrade(f.options)).status, 'SOURCE_MATCH_VERIFIED');
    env[upgrade.PUBLISH_FLAG] = 'health-schedules';
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).reason, 'ERROR_HANDLER_UNPUBLISHED');
    env[upgrade.PUBLISH_FLAG] = 'error-handler';
    const handler = await upgrade.applyPublication({ ...f.options, env });
    assert.equal(handler.status, 'PUBLICATION_VERIFIED');
    assert.equal(handler.changed_count, 1);
    assert.equal(handler.workflows.find(x => x.id === upgrade.PLAN.error_workflow.id).published, true);
    assert.equal(handler.workflows.filter(x => x.published).length, 1);
    assert.equal(upgrade.verifyBeforePublish(env, f.sourceDirectory).reason, 'HEALTH_SCHEDULES_UNPUBLISHED');
    env[upgrade.PUBLISH_FLAG] = 'media-schedule';
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).reason, 'HEALTH_SCHEDULES_UNPUBLISHED');
    env[upgrade.PUBLISH_FLAG] = 'health-schedules';
    const health = await upgrade.applyPublication({ ...f.options, env });
    assert.equal(health.status, 'PUBLICATION_VERIFIED');
    assert.equal(health.changed_count, 2);
    assert.deepEqual(health.workflows.filter(x => x.published).map(x => x.id), [
      'DR90GlobalErrorV1', 'DR92RuntimeHeartbeatV1', 'DR93ObjectStorageHealthV1']);
    assert.equal(health.workflows.find(x => x.id === 'DR94R2ApprovedMediaMirrorV1').published, false);
    assert.equal(upgrade.verifyBeforePublish(env, f.sourceDirectory).status, 'SOURCE_MATCH_VERIFIED');
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).changed_count, 0);
    env[upgrade.PUBLISH_FLAG] = 'media-schedule';
    const media = await upgrade.applyPublication({ ...f.options, env });
    assert.equal(media.status, 'PUBLICATION_VERIFIED');
    assert.equal(media.changed_count, 1);
    assert.ok(media.workflows.every(x => x.published && x.source_matches_published));
    env[upgrade.PUBLISH_FLAG] = 'schedules';
    assert.equal((await upgrade.applyPublication({ ...f.options, env })).reason, 'INVALID_OPERATOR_FLAG');
    assert.deepEqual(f.calls.filter(x => x[0] === 'publish:workflow').map(x => x[1]), [
      '--id=DR90GlobalErrorV1', '--id=DR92RuntimeHeartbeatV1',
      '--id=DR93ObjectStorageHealthV1', '--id=DR94R2ApprovedMediaMirrorV1']);
  } finally { f.db.close(); }
});

test('phase conflicts and a preexisting lock fail closed without stealing the lock', async () => {
  const f = fixture();
  try {
    const report = await upgrade.applyUpgrade({ ...f.options,
      env: { ...f.env, [upgrade.PUBLISH_FLAG]: 'error-handler' } });
    assert.equal(report.reason, 'PHASE_CONFLICT');
    const lock = path.join(path.dirname(f.databasePath), 'control-plane-upgrade.lock');
    fs.writeFileSync(lock, PRIVATE, { mode: 0o600 });
    assert.equal((await upgrade.applyUpgrade(f.options)).reason, 'LOCK_UNAVAILABLE');
    assert.equal(fs.readFileSync(lock, 'utf8'), PRIVATE);
    assert.equal(f.calls.length, 0);
  } finally { f.db.close(); }
});
