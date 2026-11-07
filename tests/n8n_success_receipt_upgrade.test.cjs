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
const ROOT = path.resolve(__dirname, '..');
const PRIVATE = 'PRIVATE_SYNTHETIC_VALUE';
const roots = [];
after(() => { for (const root of roots) fs.rmSync(root, { recursive: true, force: true }); });

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drop-rate-dr91-upgrade-'));
  roots.push(root); fs.mkdirSync(path.join(root, '.n8n'));
  const sourceDirectory = path.join(root, 'workflows'); fs.mkdirSync(sourceDirectory);
  const databasePath = path.join(root, '.n8n/database.sqlite');
  const db = new DatabaseSync(databasePath);
  db.exec('PRAGMA journal_mode=WAL; CREATE TABLE workflow_entity(id TEXT PRIMARY KEY,name TEXT,'
    + 'nodes TEXT,connections TEXT,settings TEXT,nodeGroups TEXT,versionId TEXT,active INTEGER,activeVersionId TEXT);'
    + 'CREATE TABLE workflow_history(workflowId TEXT,versionId TEXT,nodes TEXT,connections TEXT,nodeGroups TEXT);'
    + 'CREATE TABLE credentials_entity(id TEXT,name TEXT,type TEXT,data TEXT);'
    + 'CREATE TABLE shared_workflow(workflowId TEXT,projectId TEXT,role TEXT);');
  db.prepare('INSERT INTO credentials_entity VALUES (?,?,?,?)').run('fixture', 'Drive', 'googleDriveOAuth2Api', PRIVATE);
  for (const [id, file] of inspector.WORKFLOWS) {
    const raw = fs.readFileSync(path.join(ROOT, 'automation/n8n/workflows', file), 'utf8');
    fs.writeFileSync(path.join(sourceDirectory, file), raw);
    const value = JSON.parse(raw), receipt = id === success.PLAN.id;
    if (receipt) value.nodes.find(x => x.type === 'n8n-nodes-base.httpRequest')
      .parameters.options.response.response.responseFormat = 'json';
    const version = 'original-' + id;
    db.prepare('INSERT INTO workflow_entity VALUES (?,?,?,?,?,?,?,?,?)').run(id, value.name,
      JSON.stringify(value.nodes), JSON.stringify(value.connections), JSON.stringify(value.settings), '[]',
      version, receipt ? 0 : 1, receipt ? null : version);
    db.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(id, version,
      JSON.stringify(value.nodes), JSON.stringify(value.connections), '[]');
    db.prepare('INSERT INTO shared_workflow VALUES (?,?,?)').run(id, 'original-project', 'workflow:owner');
  }
  const calls = [];
  const command = async args => {
    calls.push(args);
    if (args[0] === '--version') return { stdout: '2.32.6\n' };
    if (args[0] === 'import:workflow') {
      assert.equal(args[2], '--activeState=false');
      const values = JSON.parse(fs.readFileSync(args[1].slice('--input='.length)));
      assert.equal(values.length, 1); assert.equal(values[0].id, success.PLAN.id);
      const value = values[0], version = 'repaired-' + value.id;
      db.prepare('UPDATE workflow_entity SET nodes=?,connections=?,settings=?,versionId=? WHERE id=?').run(
        JSON.stringify(value.nodes), JSON.stringify(value.connections), JSON.stringify(value.settings), version, value.id);
      db.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(value.id, version,
        JSON.stringify(value.nodes), JSON.stringify(value.connections), '[]');
      return { stdout: PRIVATE, stderr: PRIVATE };
    }
    assert.deepEqual(args, ['publish:workflow', '--id=' + success.PLAN.id]);
    db.prepare('UPDATE workflow_entity SET active=1,activeVersionId=versionId WHERE id=?').run(success.PLAN.id);
    return { stdout: PRIVATE };
  };
  const env = { N8N_USER_FOLDER: root, [success.FLAG]: 'true' };
  return { root, db, databasePath, sourceDirectory, calls, env,
    options: { env, sourceDirectory, command, offline: async () => {} } };
}
const coreRows = db => db.prepare('SELECT * FROM workflow_entity WHERE id<>? ORDER BY id').all(success.PLAN.id);

test('only the actually observed response-format difference is allowed and the operator is default-off', async () => {
  assert.equal(success.readSource(path.join(ROOT, 'automation/n8n/workflows')).id, 'DR91SuccessReceiptV1');
  assert.equal(success.PLAN.observed_at, '2026-10-27T15:07:24.645509857Z');
  assert.equal((await success.runBounded('--apply', {})).status, 'DISABLED');
  assert.equal((await success.runBounded('--publish', {})).status, 'DISABLED');
  assert.equal((await success.runBounded('--apply', { [success.FLAG]: 'yes' })).reason, 'INVALID_OPERATOR_FLAG');
});

test('one-ID repair verifies a five-workflow WAL backup and preserves published core, ownership and credential data', async () => {
  const f = fixture();
  try {
    const originalCore = coreRows(f.db);
    const owners = f.db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all();
    const report = await success.apply(f.options);
    assert.equal(report.status, 'SOURCE_MATCH_VERIFIED'); assert.equal(report.changed_count, 1);
    assert.equal(report.backup.verified, true);
    assert.ok(!JSON.stringify(report).includes(PRIVATE));
    assert.deepEqual(coreRows(f.db), originalCore);
    assert.deepEqual(f.db.prepare('SELECT * FROM shared_workflow ORDER BY workflowId').all(), owners);
    const filename = path.join(path.dirname(f.databasePath), 'drop-rate-control-plane-backups', report.backup.id, 'database.sqlite');
    const db = inspector.openDatabase(filename);
    assert.deepEqual(coreRows(db), originalCore);
    const old = inspector.inspectDatabase(db, f.sourceDirectory).workflows.find(x => x.id === success.PLAN.id);
    assert.equal(old.stored_sha256, success.PLAN.observed_stored_sha256);
    assert.equal(db.prepare('SELECT data FROM credentials_entity').get().data, PRIVATE); db.close();
    const count = f.calls.length;
    assert.equal((await success.apply(f.options)).changed_count, 0);
    assert.equal(f.calls.length, count);
    assert.equal(f.db.prepare('SELECT count(*) AS n FROM workflow_history WHERE workflowId=?').get(success.PLAN.id).n, 2);
  } finally { f.db.close(); }
});

test('source drift, stored drift, active/published receipt and noncurrent core block before mutation', async () => {
  for (const change of ['source', 'stored', 'active', 'published', 'core']) {
    const f = fixture();
    try {
      if (change === 'source') {
        const file = path.join(f.sourceDirectory, 'dr-91-success-receipt.json');
        fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace('autodetect', 'json'));
      }
      if (change === 'stored') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{}', success.PLAN.id);
      if (change === 'active') f.db.prepare('UPDATE workflow_entity SET active=1 WHERE id=?').run(success.PLAN.id);
      if (change === 'published') f.db.prepare('UPDATE workflow_entity SET activeVersionId=versionId WHERE id=?').run(success.PLAN.id);
      if (change === 'core') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{}', core.PLAN.error_workflow.id);
      const result = await success.apply(f.options);
      assert.equal(result.status, 'BLOCKED', change); assert.equal(f.calls.length, 0);
    } finally { f.db.close(); }
  }
});

test('backup failure, drift during backup and missing imported history never report success', async () => {
  for (const failure of ['backup', 'drift', 'history']) {
    const f = fixture();
    try {
      const makeBackup = async (...args) => {
        if (failure === 'backup') throw { safeCode: 'BACKUP_UNVERIFIED', message: PRIVATE };
        const backup = await core.createBackup(...args);
        if (failure === 'drift') f.db.prepare('UPDATE workflow_entity SET settings=? WHERE id=?').run('{}', success.PLAN.id);
        return backup;
      };
      const command = async args => {
        const value = await f.options.command(args);
        if (failure === 'history' && args[0] === 'import:workflow') {
          f.db.prepare('DELETE FROM workflow_history WHERE workflowId=?').run(success.PLAN.id);
        }
        return value;
      };
      const result = await success.apply({ ...f.options, makeBackup, command });
      assert.equal(result.status, 'BLOCKED'); assert.ok(!JSON.stringify(result).includes(PRIVATE));
      if (failure !== 'history') assert.equal(f.calls.filter(x => x[0] === 'import:workflow').length, 0);
    } finally { f.db.close(); }
  }
});

test('publication is separate, requires exact published DR90, changes only DR91, and retry is a no-op', async () => {
  const f = fixture();
  try {
    const env = { ...f.env, [success.FLAG]: 'false', [success.PUBLISH_FLAG]: 'true' };
    assert.equal((await success.apply({ ...f.options, env, publication: true })).reason, 'SOURCE_NOT_VERIFIED');
    assert.equal((await success.apply(f.options)).status, 'SOURCE_MATCH_VERIFIED');
    const before = coreRows(f.db);
    f.db.prepare('UPDATE workflow_entity SET active=0,activeVersionId=NULL WHERE id=?').run(core.PLAN.error_workflow.id);
    assert.equal((await success.apply({ ...f.options, env, publication: true })).reason, 'ERROR_HANDLER_UNPUBLISHED');
    f.db.prepare('UPDATE workflow_entity SET active=1,activeVersionId=versionId WHERE id=?').run(core.PLAN.error_workflow.id);
    const result = await success.apply({ ...f.options, env, publication: true });
    assert.equal(result.status, 'PUBLICATION_VERIFIED'); assert.equal(result.changed_count, 1);
    assert.equal(result.workflows.find(x => x.id === success.PLAN.id).published_sha256, success.PLAN.source_sha256);
    assert.deepEqual(coreRows(f.db), before);
    assert.equal((await success.apply({ ...f.options, env, publication: true })).changed_count, 0);
    assert.deepEqual(f.calls.filter(x => x[0] === 'publish:workflow'), [['publish:workflow', '--id=' + success.PLAN.id]]);
  } finally { f.db.close(); }
});

test('mutually exclusive phases and the shared lock block before any CLI mutation', async () => {
  const f = fixture();
  try {
    for (const conflict of [success.PUBLISH_FLAG, core.FLAG, core.PUBLISH_FLAG,
      'DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT']) {
      assert.equal((await success.apply({ ...f.options, env: { ...f.env, [conflict]: 'true' } })).reason, 'PHASE_CONFLICT');
    }
    assert.equal((await core.applyUpgrade({ ...f.options, env: { ...f.env, [core.FLAG]: 'true' } })).reason, 'PHASE_CONFLICT');
    const lock = path.join(path.dirname(f.databasePath), 'control-plane-upgrade.lock');
    fs.writeFileSync(lock, PRIVATE, { mode: 0o600 });
    assert.equal((await success.apply(f.options)).reason, 'LOCK_UNAVAILABLE');
    assert.equal(fs.readFileSync(lock, 'utf8'), PRIVATE); assert.equal(f.calls.length, 0);
  } finally { f.db.close(); }
});
