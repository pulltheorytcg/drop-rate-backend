'use strict';

const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { DatabaseSync, constants } = require('node:sqlite');
const { test, after } = require('node:test');
const inspector = require('../automation/n8n/ops/inspect-stored-metadata.cjs');

const ROOT = path.resolve(__dirname, '..');
const HELPER = path.join(ROOT, 'automation/n8n/ops/inspect-stored-metadata.cjs');
const SOURCES = path.join(ROOT, 'automation/n8n/workflows');
const PRIVATE = 'PRIVATE_TEST_MATERIAL_MUST_NEVER_APPEAR';
const tempRoots = [];
after(() => { for (const root of tempRoots) fs.rmSync(root, { recursive: true, force: true }); });

function fixture(prefix = '') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drop-rate-n8n-metadata-'));
  tempRoots.push(root);
  fs.mkdirSync(path.join(root, '.n8n'));
  const filename = path.join(root, '.n8n/database.sqlite');
  const db = new DatabaseSync(filename);
  db.exec(`CREATE TABLE "${prefix}workflow_entity" (
    id TEXT PRIMARY KEY, name TEXT, active INTEGER, activeVersionId TEXT,
    nodes TEXT, connections TEXT, settings TEXT, nodeGroups TEXT,
    pinData TEXT, staticData TEXT);
    CREATE TABLE "${prefix}workflow_history" (
      workflowId TEXT, versionId TEXT, nodes TEXT, connections TEXT, nodeGroups TEXT,
      PRIMARY KEY (workflowId, versionId));
    CREATE TABLE "${prefix}credentials_entity" (
      id TEXT PRIMARY KEY, name TEXT, type TEXT, data TEXT);`);
  const definitions = inspector.WORKFLOWS.map(([id, file]) => {
    const value = JSON.parse(fs.readFileSync(path.join(SOURCES, file), 'utf8'));
    assert.equal(value.id, id);
    db.prepare(`INSERT INTO "${prefix}workflow_entity"
      (id, name, active, activeVersionId, nodes, connections, settings, nodeGroups, pinData, staticData)
      VALUES (?, ?, 0, NULL, ?, ?, ?, ?, ?, ?)`).run(
      id, value.name, JSON.stringify(value.nodes), JSON.stringify(value.connections),
      JSON.stringify(value.settings), JSON.stringify(value.nodeGroups || []), PRIVATE, PRIVATE,
    );
    return value;
  });
  db.prepare(`INSERT INTO "${prefix}credentials_entity" VALUES (?, ?, ?, ?)`).run(
    'drive-credential', 'Drop Rate Drive', 'googleDriveOAuth2Api', PRIVATE,
  );
  db.prepare(`INSERT INTO "${prefix}credentials_entity" VALUES (?, ?, ?, ?)`).run(
    'google-service-account', 'Google service account', 'googleApi', PRIVATE,
  );
  db.prepare(`INSERT INTO "${prefix}credentials_entity" VALUES (?, ?, ?, ?)`).run(
    'unrelated', PRIVATE, 'slackApi', PRIVATE,
  );
  return { root, filename, db, definitions };
}

function fileHash(filename) {
  return createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
}

test('normalization ignores generated state, preserves executable changes and key ordering', () => {
  const value = JSON.parse(fs.readFileSync(path.join(SOURCES, inspector.WORKFLOWS[0][1]), 'utf8'));
  const expected = inspector.definitionHash(value);
  const copy = { ...value, active: true, versionId: 'generated', pinData: { private: PRIVATE },
    staticData: { private: PRIVATE }, meta: { private: PRIVATE }, updatedAt: 'later' };
  copy.settings = Object.fromEntries(Object.entries(copy.settings).reverse());
  assert.equal(inspector.definitionHash(copy), expected);
  copy.settings = { ...copy.settings, errorWorkflow: 'another-workflow' };
  assert.notEqual(inspector.definitionHash(copy), expected);
  const codeChange = structuredClone(value);
  codeChange.nodes[1].parameters.jsCode += '\n// changed';
  assert.notEqual(inspector.definitionHash(codeChange), expected);
});

test('reads only approved credential metadata, keeps database read-only, and reports four exact IDs', () => {
  // The API pre-deploy Node runtime supports SQLite but not setAuthorizer.
  // A poison projection proves data-read denial on both runtimes. Exercise
  // that path explicitly even when the local runtime supplies the authorizer.
  for (const hideAuthorizer of [true, false]) {
    const f = fixture();
    f.db.exec(`ALTER TABLE credentials_entity RENAME TO credential_rows;
      CREATE VIEW credentials_entity AS
        SELECT id, name, type, json_extract('credential data access forbidden', '$') AS data
        FROM credential_rows;`);
    f.db.close();
    const before = fileHash(f.filename);
    const db = inspector.openDatabase(f.filename);
    if (hideAuthorizer) Object.defineProperty(db, 'setAuthorizer', { value: undefined });
    const hasAuthorizer = typeof db.setAuthorizer === 'function';
    if (hideAuthorizer) assert.equal(hasAuthorizer, false);
    const credentialColumns = new Set();
    if (hasAuthorizer) {
      db.setAuthorizer((action, table, column) => {
        if (action === constants.SQLITE_READ && table === 'credentials_entity') {
          credentialColumns.add(column);
          if (column === 'data') return constants.SQLITE_DENY;
        }
        return constants.SQLITE_OK;
      });
    }
    const report = inspector.inspectDatabase(db, SOURCES);
    assert.equal(report.status, 'COMPLETE');
    assert.deepEqual(report.workflows.map(w => w.id), inspector.WORKFLOWS.map(([id]) => id));
    for (const workflow of report.workflows) {
      assert.match(workflow.source_sha256, /^[a-f0-9]{64}$/);
      assert.equal(workflow.source_matches_stored, true);
      assert.equal(workflow.active, false);
      assert.equal(workflow.published, false);
    }
    assert.deepEqual(report.drive_credentials.credentials, [
      { id: 'drive-credential', name: 'Drop Rate Drive', type: 'googleDriveOAuth2Api' },
      { id: 'google-service-account', name: 'Google service account', type: 'googleApi' },
    ]);
    if (hasAuthorizer) assert.deepEqual([...credentialColumns].sort(), ['id', 'name', 'type']);
    assert.ok(!JSON.stringify(report).includes(PRIVATE));
    assert.throws(() => db.prepare('SELECT data FROM credentials_entity').all(),
      /malformed JSON|prohibited|not authorized/i);
    assert.throws(() => db.prepare('SELECT * FROM credentials_entity').all(),
      /malformed JSON|prohibited|not authorized/i);
    assert.throws(() => db.exec("UPDATE workflow_entity SET active = 1"), /readonly/i);
    db.close();
    assert.equal(fileHash(f.filename), before);
  }
});

test('distinguishes stale stored settings and published history from the current draft', () => {
  const f = fixture();
  const heartbeat = f.definitions[1];
  f.db.prepare('UPDATE workflow_entity SET settings = ?, active = 1 WHERE id = ?').run(
    JSON.stringify({ executionOrder: 'v1' }), heartbeat.id,
  );
  const storage = f.definitions[2];
  const oldNodes = structuredClone(storage.nodes);
  oldNodes[0].parameters.rule.interval[0].hoursInterval = 2;
  f.db.prepare('INSERT INTO workflow_history VALUES (?, ?, ?, ?, ?)').run(
    storage.id, 'published-old-version', JSON.stringify(oldNodes),
    JSON.stringify(storage.connections), '[]',
  );
  f.db.prepare('UPDATE workflow_entity SET activeVersionId = ? WHERE id = ?').run(
    'published-old-version', storage.id,
  );
  const report = inspector.inspectDatabase(f.db, SOURCES);
  const h = report.workflows[1], s = report.workflows[2];
  assert.equal(h.active, true);
  assert.equal(h.published, false); // Never infer publication from the legacy flag.
  assert.equal(h.errorWorkflow, null);
  assert.equal(h.source_errorWorkflow, 'DR90GlobalErrorV1');
  assert.equal(h.source_matches_stored, false);
  assert.equal(s.active, false);
  assert.equal(s.published, true);
  assert.equal(s.source_matches_stored, true);
  assert.equal(s.source_matches_published, false);
  assert.match(s.published_sha256, /^[a-f0-9]{64}$/);
  f.db.close();
});

test('bounds results, supports reviewed table prefixes, and does not disguise malformed definitions', () => {
  const f = fixture('n8n_');
  const insert = f.db.prepare('INSERT INTO n8n_credentials_entity VALUES (?, ?, ?, ?)');
  for (let i = 0; i < 55; i++) insert.run(`extra-${String(i).padStart(2, '0')}`, 'Drive', 'googleDriveOAuth2Api', PRIVATE);
  f.db.prepare('UPDATE n8n_workflow_entity SET nodes = ? WHERE id = ?').run(
    `{not-json:${PRIVATE}`, inspector.WORKFLOWS[0][0],
  );
  f.db.prepare('UPDATE n8n_workflow_entity SET settings = ? WHERE id = ?').run(
    JSON.stringify({ oversize: 'x'.repeat(1024 * 1024) }), inspector.WORKFLOWS[1][0],
  );
  f.db.prepare('DELETE FROM n8n_workflow_entity WHERE id = ?').run(inspector.WORKFLOWS[3][0]);
  const report = inspector.inspectDatabase(f.db, SOURCES, 'n8n_');
  assert.equal(report.status, 'PARTIAL');
  assert.equal(report.workflows[0].stored_sha256, null);
  assert.equal(report.workflows[1].stored_sha256, null);
  assert.equal(report.workflows[3].status, 'MISSING');
  assert.equal(report.drive_credentials.truncated, true);
  assert.equal(report.drive_credentials.credentials.length, 50);
  assert.ok(!JSON.stringify(report).includes(PRIVATE));
  assert.ok(JSON.stringify(report).length < 65536);
  f.db.close();
});

test('resolves the upstream user-folder/database rules without printing configuration', () => {
  assert.equal(inspector.runtimeConfig({ N8N_USER_FOLDER: '/volume' }).databasePath,
    '/volume/.n8n/database.sqlite');
  assert.equal(inspector.runtimeConfig({ HOME: '/home/node', DB_SQLITE_DATABASE: '/volume/n8n.sqlite' }).databasePath,
    '/volume/n8n.sqlite');
  assert.equal(inspector.runtimeConfig({ DB_TYPE: 'postgresdb' }).reason, 'DATABASE_TYPE_UNSUPPORTED');
  assert.equal(inspector.runtimeConfig({ DB_TABLE_PREFIX: 'bad"' + PRIVATE }).reason, 'TABLE_PREFIX_UNSUPPORTED');
  assert.equal(inspector.runtimeConfig({ DB_SQLITE_DATABASE_FILE: PRIVATE }).reason,
    'DATABASE_CONFIGURATION_UNSUPPORTED');
});

test('CLI is gated, reports no secrets, and never creates a missing database', () => {
  const f = fixture();
  f.db.close();
  const before = fileHash(f.filename);
  const env = { ...process.env, N8N_USER_FOLDER: f.root, N8N_ENCRYPTION_KEY: PRIVATE };
  delete env[inspector.FLAG];
  let child = spawnSync(process.execPath, ['--no-warnings', HELPER], { env, encoding: 'utf8' });
  assert.equal(child.status, 0);
  assert.equal(child.stdout, '');
  env[inspector.FLAG] = 'true';
  child = spawnSync(process.execPath, ['--no-warnings', HELPER], { env, encoding: 'utf8' });
  assert.equal(child.status, 0);
  assert.equal(JSON.parse(child.stdout).status, 'COMPLETE');
  assert.ok(!child.stdout.includes(PRIVATE));
  assert.equal(child.stderr, '');
  assert.equal(fileHash(f.filename), before);
  env.DB_SQLITE_DATABASE = path.join(f.root, 'missing-' + PRIVATE + '.sqlite');
  child = spawnSync(process.execPath, ['--no-warnings', HELPER], { env, encoding: 'utf8' });
  assert.equal(child.status, 0);
  assert.equal(JSON.parse(child.stdout).reason, 'DATABASE_UNAVAILABLE');
  assert.ok(!child.stdout.includes(PRIVATE));
  assert.ok(!fs.existsSync(env.DB_SQLITE_DATABASE));
});

test('uses a hard deadline and minimal child environment; discards failed child output', () => {
  let called = false;
  assert.equal(inspector.run({}, () => { called = true; }), null);
  assert.equal(called, false);
  const result = inspector.run({ [inspector.FLAG]: 'true', HOME: '/home/node',
    N8N_ENCRYPTION_KEY: PRIVATE, DROP_RATE_AUTOMATION_COMMAND_SECRET: PRIVATE, NODE_OPTIONS: PRIVATE },
  (executable, args, options) => {
    assert.equal(options.timeout, 15000);
    assert.equal(options.maxBuffer, 65536);
    assert.equal(options.killSignal, 'SIGKILL');
    assert.deepEqual(Object.keys(options.env).sort(), [inspector.FLAG, 'HOME', 'NODE_NO_WARNINGS'].sort());
    return { status: null, error: { code: 'ETIMEDOUT', message: PRIVATE }, stdout: PRIVATE, stderr: PRIVATE };
  });
  assert.equal(result.reason, 'INSPECTION_TIMEOUT');
  assert.ok(!JSON.stringify(result).includes(PRIVATE));
  assert.equal(inspector.run({ [inspector.FLAG]: PRIVATE }).reason, 'INVALID_OPERATOR_FLAG');
});

test('startup still reaches n8n after an inspector executable failure and hides stderr', () => {
  const f = fixture();
  f.db.close();
  const bin = path.join(f.root, 'bin');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'node'), `#!/bin/sh\necho '${PRIVATE}' >&2\nexit 23\n`, { mode: 0o755 });
  fs.writeFileSync(path.join(bin, 'n8n'), '#!/bin/sh\nif [ "$1" = "start" ]; then echo N8N_START_REACHED; fi\n', { mode: 0o755 });
  const emptyWorkflows = path.join(f.root, 'empty-workflows');
  fs.mkdirSync(emptyWorkflows);
  const script = fs.readFileSync(path.join(ROOT, 'automation/n8n/start.sh'), 'utf8')
    .replace('WORKFLOW_DIR="/opt/drop-rate/workflows"', `WORKFLOW_DIR="${emptyWorkflows}"`);
  const filename = path.join(f.root, 'start.sh');
  fs.writeFileSync(filename, script);
  const child = spawnSync('/bin/sh', [filename], { encoding: 'utf8', timeout: 5000, env: {
    PATH: bin + ':' + process.env.PATH, HOME: f.root, N8N_USER_FOLDER: f.root,
    [inspector.FLAG]: 'true', N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false', NODE_FUNCTION_ALLOW_BUILTIN: 'crypto',
    DROP_RATE_AUTOMATION_WEBHOOK_SECRET: PRIVATE, DROP_RATE_AUTOMATION_COMMAND_SECRET: PRIVATE,
    DROP_RATE_API_AUTOMATION_CONTROL_URL: 'https://backend.invalid/api/v1/automation/control/receipt',
  } });
  assert.equal(child.status, 0);
  assert.ok(child.stdout.includes('INSPECTOR_PROCESS_FAILED'));
  assert.ok(child.stdout.includes('N8N_START_REACHED'));
  assert.ok(!child.stdout.includes(PRIVATE));
  assert.equal(child.stderr, '');
});

test('DR92, DR93 and DR94 remain inactive and link DR90 in reviewed source only', () => {
  for (const [, file] of inspector.WORKFLOWS.slice(1)) {
    const value = JSON.parse(fs.readFileSync(path.join(SOURCES, file), 'utf8'));
    assert.equal(value.active, false);
    assert.equal(value.settings.errorWorkflow, 'DR90GlobalErrorV1');
  }
  const error = JSON.parse(fs.readFileSync(path.join(SOURCES, inspector.WORKFLOWS[0][1]), 'utf8'));
  assert.notEqual(error.settings.errorWorkflow, error.id);
});
