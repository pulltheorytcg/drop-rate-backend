'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const canary = require('../automation/n8n/ops/run-isolated-error-canary.cjs');

const SECRET = 'synthetic-hmac-material-' + 'a'.repeat(40);
const TOKEN = 'b'.repeat(64);
const privateValue = 'MUST_NEVER_INHERIT_OR_PRINT';
const failed = { id: '17', workflowId: canary.CANARY_ID, mode: 'webhook', status: 'error', stoppedAt: '2026-10-27' };
const handler = { id: '18', workflowId: canary.ERROR_ID, mode: 'error', status: 'success', stoppedAt: '2026-10-27' };

function actualReceipt() {
  const dr90 = canary.readSources()[0];
  const normalize = dr90.nodes.find(node => node.name === 'Normalize Failure').parameters.jsCode;
  const sign = dr90.nodes.find(node => node.name === 'Sign Control Receipt').parameters.jsCode;
  const input = { execution: { id: failed.id, error: { name: 'NodeOperationError', message: canary.ERROR_MESSAGE } },
    workflow: { id: canary.CANARY_ID, name: 'DR-90 Isolated Routing Canary' } };
  const receipt = new Function('$input', normalize)({ first: () => ({ json: input }) })[0].json;
  const signed = new Function('$json', '$env', 'require', sign)(receipt, {
    DROP_RATE_AUTOMATION_COMMAND_SECRET: SECRET, DROP_RATE_API_AUTOMATION_CONTROL_URL: 'http://127.0.0.1:1/fixture',
  }, require)[0].json;
  return { body: Buffer.from(signed.receipt_body), headers: {
    'x-drop-rate-timestamp': signed.receipt_timestamp,
    'x-drop-rate-signature': signed.receipt_signature,
  } };
}

function signedMutation(change) {
  const { body, headers } = actualReceipt();
  const data = JSON.parse(body); change(data);
  const changed = Buffer.from(JSON.stringify(data));
  headers['x-drop-rate-signature'] = 'sha256=' + crypto.createHmac('sha256', SECRET)
    .update(headers['x-drop-rate-timestamp'] + '.').update(changed).digest('hex');
  return { body: changed, headers };
}

function databaseFixture(published = false) {
  const database = new DatabaseSync(':memory:');
  database.exec(`CREATE TABLE workflow_entity(id TEXT,name TEXT,active INTEGER,activeVersionId TEXT,
    nodes TEXT,connections TEXT,settings TEXT,nodeGroups TEXT);
    CREATE TABLE workflow_history(workflowId TEXT,versionId TEXT,nodes TEXT,connections TEXT,nodeGroups TEXT);
    CREATE TABLE execution_entity(id INTEGER,workflowId TEXT,mode TEXT,status TEXT,stoppedAt TEXT);
    CREATE VIEW credentials_entity AS SELECT json_extract('NEVER_READ_CREDENTIALS','$.poison') AS data;
    CREATE VIEW execution_data AS SELECT json_extract('NEVER_READ_NODE_DATA','$.poison') AS data;`);
  for (const source of canary.readSources()) {
    database.prepare('INSERT INTO workflow_entity VALUES (?,?,?,?,?,?,?,?)').run(source.id, source.name,
      published ? 1 : 0, published ? 'version-' + source.id : null, JSON.stringify(source.nodes),
      JSON.stringify(source.connections), JSON.stringify(source.settings), '[]');
    database.prepare('INSERT INTO workflow_history VALUES (?,?,?,?,?)').run(source.id, 'version-' + source.id,
      JSON.stringify(source.nodes), JSON.stringify(source.connections), '[]');
  }
  return database;
}

test('the canary is strictly opt-in and never accepts loose truthy values', async () => {
  assert.equal(await canary.run({ DB_SQLITE_DATABASE: privateValue }), null);
  assert.equal(await canary.run({ [canary.FLAG]: 'false' }), null);
  const result = await canary.run({ [canary.FLAG]: '1', DROP_RATE_AUTOMATION_COMMAND_SECRET: privateValue });
  assert.equal(result.reason, 'INVALID_OPERATOR_FLAG');
  assert.equal(result.production_backend_verified, false);
  assert.ok(!JSON.stringify(result).includes(privateValue));
});

test('both committed workflow definitions are exact, inactive and nonrecursive', () => {
  const [dr90, fixture] = canary.readSources();
  assert.equal(dr90.active, false);
  assert.equal(fixture.active, false);
  assert.equal(fixture.settings.errorWorkflow, dr90.id);
  assert.equal(dr90.settings.errorWorkflow, undefined);
  assert.deepEqual(fixture.nodes.map(node => node.type), [
    'n8n-nodes-base.webhook', 'n8n-nodes-base.code', 'n8n-nodes-base.stopAndError',
  ]);
});

test('the exact DR90 acceptance node still requires a successful parsed boolean receipt', () => {
  const dr90 = canary.readSources()[0];
  const code = dr90.nodes.find(node => node.name === 'Control Receipt Accepted?').parameters.jsCode;
  const invoke = json => new Function('$input', code)({ first: () => ({ json }) });
  const body = { accepted: true, workflow_key: 'fixture', execution_id: '17' };
  assert.deepEqual(invoke({ statusCode: 200, body }),
    [{ json: { recorded: true, workflow_key: 'fixture', execution_id: '17' } }]);
  for (const response of [{ statusCode: 500, body }, { statusCode: 200, body: {} },
    { statusCode: 200, body: JSON.stringify(body) },
    { statusCode: 200, body: { accepted: 'true' } },
    { statusCode: 200, body: { readable: true } }]) {
    assert.throws(() => invoke(response), /automation_control_receipt_/);
  }
});

test('the real fixture rejects missing, wrong, multibyte and malformed tokens before failing', () => {
  const code = canary.readSources()[1].nodes[1].parameters.jsCode;
  function invoke(token, body = { canary: 'DR90_AUTOMATIC_ROUTING' }, expected = TOKEN) {
    return new Function('$input', '$env', 'require', code)(
      { first: () => ({ json: { headers: { 'x-drop-rate-canary-token': token }, body } }) },
      { DROP_RATE_CANARY_TOKEN: expected }, require);
  }
  assert.deepEqual(invoke(TOKEN), [{ json: { authenticated: true } }]);
  for (const token of [undefined, '', 'a'.repeat(64), 'é'.repeat(64), TOKEN + '0']) {
    assert.deepEqual(invoke(token), []);
  }
  assert.deepEqual(invoke(TOKEN, { canary: 'DR90_AUTOMATIC_ROUTING', injected: true }), []);
  assert.deepEqual(invoke(TOKEN, null), []);
  assert.deepEqual(invoke(TOKEN, undefined, ''), []);
});

test('child configuration contains only temporary SQLite, generated keys and loopback destinations', () => {
  const root = '/tmp/drop-rate-n8n-error-canary-Abc123';
  const env = canary.childEnvironment(root, { main: 10001, broker: 10002, receipt: 10003 },
    { encryption: 'e'.repeat(64), token: TOKEN, runner: 'r'.repeat(64), hmac: SECRET }, root + '/guard.cjs');
  assert.equal(env.DB_TYPE, 'sqlite');
  assert.equal(env.DB_SQLITE_DATABASE, root + '/.n8n/database.sqlite');
  assert.equal(env.N8N_USER_FOLDER, root);
  assert.equal(env.N8N_LISTEN_ADDRESS, '127.0.0.1');
  assert.equal(env.N8N_RUNNERS_BROKER_LISTEN_ADDRESS, '127.0.0.1');
  assert.equal(env.DROP_RATE_API_AUTOMATION_CONTROL_URL, 'http://127.0.0.1:10003/isolated-control-receipt');
  for (const key of ['HOME', 'DATABASE_URL', 'DB_POSTGRESDB_HOST', 'HTTP_PROXY', 'HTTPS_PROXY',
    'RAILWAY_API_TOKEN', 'N8N_CONFIG_FILES', 'N8N_ENCRYPTION_KEY_FILE', 'NODE_PATH']) assert.equal(env[key], undefined);
  assert.equal(env.N8N_DIAGNOSTICS_ENABLED, 'false');
  assert.equal(env.N8N_SSRF_ALLOWED_IP_RANGES, '127.0.0.1/32');
});

test('actual pinned DR90 normalization/signing passes only with the exact failed webhook identity', () => {
  const { body, headers } = actualReceipt();
  assert.equal(canary.validateReceipt(body, headers, SECRET, [failed, handler]), failed.id);
  assert.throws(() => canary.validateReceipt(body, headers, 'wrong-secret', [failed]), /RECEIPT_INVALID/);
  assert.throws(() => canary.validateReceipt(body, headers, SECRET, [{ ...failed, id: '19' }]), /RECEIPT_INVALID/);
  assert.throws(() => canary.validateReceipt(body, headers, SECRET, [{ ...failed, mode: 'manual' }]), /RECEIPT_INVALID/);
  assert.throws(() => canary.validateReceipt(body, headers, SECRET, [failed], Date.now() + 61000), /RECEIPT_INVALID/);
  assert.throws(() => canary.validateReceipt(Buffer.alloc(4097), headers, SECRET, [failed]), /RECEIPT_INVALID/);
  for (const change of [item => { item.status = 'SUCCESS'; }, item => { item.workflow_version = canary.ERROR_ID; },
    item => { item.owner_id = 'private-owner'; }, item => { item.error_message = 'another failure'; },
    item => { item.unexpected = true; }, item => { item.execution_id = '20'; }]) {
    const changed = signedMutation(change);
    assert.throws(() => canary.validateReceipt(changed.body, changed.headers, SECRET, [failed]), /RECEIPT_INVALID/);
  }
});

test('proof requires one failed webhook and one successful error-mode handler, with matching receipt', () => {
  assert.deepEqual(canary.executionEvidence([failed, handler], failed.id), {
    failed_execution_mode: 'webhook', handler_execution_mode: 'error',
    failed_execution_count: 1, handler_execution_count: 1,
  });
  for (const rows of [[failed], [failed, handler, { ...handler, id: '19' }],
    [failed, { ...handler, mode: 'manual' }], [{ ...failed, mode: 'cli' }, handler],
    [failed, { ...handler, status: 'error' }], [failed, { ...handler, stoppedAt: null }]]) {
    assert.equal(canary.executionEvidence(rows, failed.id), null);
  }
  assert.equal(canary.executionEvidence([failed, handler], 'wrong-id'), null);
});

test('real SQLite verifies both stored and published hashes without reading credentials or execution data', () => {
  const database = databaseFixture();
  try {
    assert.deepEqual(canary.inspectTemporaryState(database), []);
    assert.throws(() => canary.inspectTemporaryState(database, { published: true }), /UNPUBLISHED/);
    database.exec("UPDATE workflow_entity SET active=1,activeVersionId='version-'||id");
    assert.deepEqual(canary.inspectTemporaryState(database, { published: true }), []);
    assert.throws(() => canary.inspectTemporaryState(database), /NOT_INACTIVE/);
    database.prepare('UPDATE workflow_history SET nodes=? WHERE workflowId=?')
      .run('[]', canary.ERROR_ID);
    assert.throws(() => canary.inspectTemporaryState(database, { published: true }), /PUBLISHED_DEFINITION_CHANGED/);
  } finally { database.close(); }
});

test('a stored source edit or additional imported workflow invalidates the disposable proof', () => {
  const database = databaseFixture(true);
  try {
    database.prepare('UPDATE workflow_entity SET name=? WHERE id=?').run('Changed', canary.ERROR_ID);
    assert.throws(() => canary.inspectTemporaryState(database, { published: true }), /DEFINITION_CHANGED/);
    database.exec("INSERT INTO workflow_entity(id) VALUES ('unexpected')");
    assert.throws(() => canary.inspectTemporaryState(database, { published: true }), /COUNT_INVALID/);
  } finally { database.close(); }
});

test('failure diagnostics expose only bounded execution modes/statuses and fixed runtime signals', async () => {
  const database = databaseFixture(true);
  try {
    database.prepare('INSERT INTO execution_entity VALUES (?,?,?,?,?)').run(1, canary.CANARY_ID, 'webhook', 'error', '2026-10-27');
    database.prepare('INSERT INTO execution_entity VALUES (?,?,?,?,?)').run(2, canary.ERROR_ID, 'error', 'running', null);
    database.prepare('INSERT INTO execution_entity VALUES (?,?,?,?,?)').run(3, privateValue, privateValue, privateValue, null);
    const report = canary.diagnosticExecutionState(database);
    assert.deepEqual(report, [
      { workflow: 'CANARY', mode: 'webhook', status: 'error', stopped: true },
      { workflow: 'DR90', mode: 'error', status: 'running', stopped: false },
      { workflow: 'UNEXPECTED', mode: 'UNEXPECTED', status: 'UNEXPECTED', stopped: false },
    ]);
    assert.ok(!JSON.stringify(report).includes(privateValue));
    database.exec('DROP VIEW execution_data; CREATE TABLE execution_data(executionId INTEGER,data TEXT)');
    const flattened = [{ resultData: '1' }, { lastNodeExecuted: '2', error: '3', runData: '4' },
      'Control Receipt Accepted?', { name: '5', message: '6', description: '7', stack: '7' },
      { private_node_outputs: privateValue }, 'NodeOperationError',
      'automation_control_receipt_not_accepted', privateValue];
    database.prepare('INSERT INTO execution_data VALUES (?,?)').run(2, JSON.stringify(flattened));
    database.prepare('UPDATE execution_entity SET status=?,stoppedAt=? WHERE id=2').run('error', '2026-10-27');
    const diagnostic = canary.diagnosticExecutionState(database);
    assert.deepEqual(diagnostic[1].error_metadata, { last_node: 'Control Receipt Accepted?',
      name: 'NodeOperationError', signal: 'RECEIPT_RESPONSE_NOT_ACCEPTED' });
    assert.ok(!JSON.stringify(diagnostic).includes(privateValue));
    flattened[2] = privateValue; flattened[5] = privateValue; flattened[6] = privateValue;
    database.prepare('UPDATE execution_data SET data=? WHERE executionId=2').run(JSON.stringify(flattened));
    assert.deepEqual(canary.diagnosticExecutionState(database)[1].error_metadata,
      { last_node: 'UNEXPECTED', name: 'UNEXPECTED', signal: 'UNCLASSIFIED' });
  } finally { database.close(); }
  const state = canary.createTemporaryState();
  try {
    const child = canary.startChild(process.execPath,
      ['-e', 'process.stderr.write("CANARY_NETWORK_BLOCKED " + ' + JSON.stringify(privateValue) + ')'],
      { N8N_USER_FOLDER: state.root }, { timeout: 3000 });
    await child.closed;
    assert.equal(child.output, '');
    assert.deepEqual([...child.signals], ['NETWORK_GUARD']);
  } finally { assert.equal(canary.removeTemporaryState(state), true); }
});

test('cleanup requires the exact fresh directory inode and unmodified ownership marker', () => {
  const state = canary.createTemporaryState();
  try {
    assert.equal(canary.removeTemporaryState({ ...state, root: '/tmp' }), false);
    fs.writeFileSync(path.join(state.root, 'canary-owner'), 'different');
    assert.equal(canary.removeTemporaryState(state), false);
    assert.ok(fs.existsSync(state.root));
    fs.writeFileSync(path.join(state.root, 'canary-owner'), state.nonce);
    assert.equal(canary.removeTemporaryState(state), true);
    assert.equal(fs.existsSync(state.root), false);
  } finally { if (fs.existsSync(state.root)) fs.rmSync(state.root, { recursive: true }); }
});

test('child timeout/output bounds discard arbitrary output and terminate the new process group', async () => {
  const state = canary.createTemporaryState();
  try {
    const env = { N8N_USER_FOLDER: state.root };
    const flood = canary.startChild(process.execPath,
      ['-e', 'process.stdout.write(' + JSON.stringify(privateValue) + '.repeat(40000));setInterval(()=>{},1000)'],
      env, { timeout: 3000 });
    await flood.closed;
    assert.equal(flood.failure, 'CHILD_OUTPUT_LIMIT');
    assert.equal(flood.output, '');
    const timeout = canary.startChild(process.execPath, ['-e', 'setInterval(()=>{},1000)'], env, { timeout: 100 });
    await timeout.closed;
    assert.equal(timeout.failure, 'CHILD_TIMEOUT');
    await canary.stopChild(timeout);
  } finally { assert.equal(canary.removeTemporaryState(state), true); }
});

test('the child network preload rejects external hosts and unassigned loopback ports before connecting', async () => {
  const state = canary.createTemporaryState();
  try {
    const guard = path.join(state.root, 'guard.cjs');
    fs.writeFileSync(guard, canary.networkGuardSource([12345, 12346, 12347]));
    const code = `const assert=require('node:assert/strict'),net=require('node:net'),dns=require('node:dns');
      for(const options of [{host:'203.0.113.1',port:443},{host:'127.0.0.1',port:443},{path:'/tmp/unrelated.sock'}])
        assert.throws(()=>net.connect(options),/CANARY_NETWORK_BLOCKED/);
      assert.throws(()=>dns.lookup('example.invalid',()=>{}),/CANARY_NETWORK_BLOCKED/);
      process.stdout.write('network-blocked');`;
    const child = canary.startChild(process.execPath, ['-e', code],
      { N8N_USER_FOLDER: state.root, NODE_OPTIONS: '--require=' + guard }, { timeout: 3000, capture: true });
    await child.closed;
    assert.equal(child.failure, null);
    assert.equal(child.output, 'network-blocked');
  } finally { assert.equal(canary.removeTemporaryState(state), true); }
});
