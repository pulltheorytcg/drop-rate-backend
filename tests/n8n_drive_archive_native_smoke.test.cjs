'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const { Readable } = require('node:stream');
const smoke = require('./n8n_drive_archive_native_smoke.cjs');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const keys = { encryption: 'e'.repeat(64), runner: 'r'.repeat(64),
  hmac: 'h'.repeat(64), oauth: 'synthetic-oauth-only' };

async function call(handler, method, url, body, headers = {}) {
  const request = Readable.from([body === undefined ? Buffer.alloc(0)
    : Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body))]);
  Object.assign(request, { method, url, headers });
  const response = { code: 0, headers: {}, value: null, headersSent: false,
    writeHead(code, outputHeaders) { this.code = code; this.headers = outputHeaders; this.headersSent = true; },
    end(value) { this.value = value; }, destroy() { this.destroyed = true; } };
  await handler(request, response);
  return response;
}

test('native smoke is opt-in, pins reviewed definitions, and mutates only fixture trigger/credential references', async () => {
  assert.equal(await smoke.run({}), null);
  const [reviewed] = smoke.sources();
  const fixture = smoke.runtimeFixture(reviewed, 'a'.repeat(48));
  smoke.assertFixtureIsExact(reviewed, fixture);
  assert.equal(fixture.nodes.filter(node => node.type === 'n8n-nodes-base.webhook').length, 1);
  assert.ok(!fixture.nodes.some(node => node.type.includes('scheduleTrigger')));
  const corrupted = structuredClone(fixture);
  corrupted.nodes.find(node => node.type === 'n8n-nodes-base.code').parameters.jsCode += '\nthrow new Error("changed")';
  assert.throws(() => smoke.assertFixtureIsExact(reviewed, corrupted));
  assert.throws(() => smoke.runtimeFixture(reviewed, 'public-webhook'));
});

test('native child environment isolates state/secrets and uses filesystem binaries with no execution data saving', () => {
  const env = smoke.childEnvironment('/tmp/drop-rate-dr95-native-ABC123',
    { main: 12500, broker: 12501, backend: 12502 }, keys);
  assert.equal(env.DB_TYPE, 'sqlite');
  assert.equal(env.N8N_DEFAULT_BINARY_DATA_MODE, 'filesystem');
  assert.equal(env.EXECUTIONS_DATA_SAVE_ON_SUCCESS, 'none');
  assert.equal(env.EXECUTIONS_DATA_SAVE_ON_ERROR, 'none');
  assert.equal(env.NODE_FUNCTION_ALLOW_BUILTIN, 'crypto');
  for (const forbidden of ['DATABASE_URL', 'HTTP_PROXY', 'HTTPS_PROXY', 'SUPABASE_URL',
    'TCG_DATABASE_URL', 'GOOGLE_APPLICATION_CREDENTIALS']) assert.equal(env[forbidden], undefined);
  assert.equal(env.DROP_RATE_AUTOMATION_COMMAND_SECRET, keys.hmac);
  assert.ok(!Object.values(env).includes(keys.oauth));
  assert.ok(smoke.networkGuard([12500, 12501, 12502]).includes('FIXTURE_NETWORK_BLOCKED'));
  assert.throws(() => smoke.networkGuard([0]));
});

test('temporary cleanup requires its inode and exact creation nonce', () => {
  const state = smoke.temporaryState();
  assert.equal(smoke.cleanup({ ...state, nonce: 'wrong' }), false);
  assert.ok(fs.existsSync(state.root));
  assert.equal(smoke.cleanup(state), true);
  assert.equal(fs.existsSync(state.root), false);
});

test('synthetic transports fail closed on unknown OAuth, arbitrary backend paths and any existing-file write', async () => {
  const dataset = smoke.fixtureDataset({ large: false });
  const transport = smoke.syntheticTransport(dataset, keys, '/tmp/nonexistent-dr95-binaries');
  let response = await call(transport.google, 'GET', '/drive/v3/about', undefined,
    { host: 'www.googleapis.com', authorization: 'Bearer wrong' });
  assert.equal(response.code, 400); assert.equal(transport.failure, 'SYNTHETIC_OAUTH_REQUIRED');
  const next = smoke.syntheticTransport(dataset, keys, '/tmp/nonexistent-dr95-binaries');
  response = await call(next.google, 'PATCH', '/upload/drive/v3/files/anything', Buffer.from('replacement'),
    { host: 'www.googleapis.com', authorization: 'Bearer ' + keys.oauth });
  assert.equal(response.code, 400); assert.equal(next.failure, 'EXISTING_FILE_WRITE_FORBIDDEN');
  const unsigned = smoke.syntheticTransport(dataset, keys, '/tmp/nonexistent-dr95-binaries');
  response = await call(unsigned.backend, 'POST', '/arbitrary', {});
  assert.equal(response.code, 400); assert.equal(unsigned.failure, 'SIGNATURE_TIME_INVALID');
});

test('mock creation enforces durable winning ID, exact byte digest and refuses a duplicate content write', async () => {
  const dataset = smoke.fixtureDataset({ large: false });
  const transport = smoke.syntheticTransport(dataset, keys, '/tmp/nonexistent-dr95-binaries');
  const a = dataset.archives[0], m = a.objects[0], body = dataset.blobs.get(m.sha256);
  const metadata = { id: 'WINNING_RESERVED_FILE_ID', name: m.file_name, mimeType: m.mime_type,
    parents: ['1NhFIsWesgxlf059UMdx65ps9kFMqQeO9'],
    appProperties: { drSchema: 'drive-copy-v1', drKind: a.kind,
      drManifest: a.manifest_sha256, drObject: m.sha256 } };
  transport.reservations.set(a.manifest_sha256 + ':' + m.sha256, {
    kind: a.kind, manifest_sha256: a.manifest_sha256, object_sha256: m.sha256, file_id: metadata.id });
  transport.events.push('source:' + m.sha256);
  const headers = { host: 'www.googleapis.com', authorization: 'Bearer ' + keys.oauth,
    'x-upload-content-type': m.mime_type, 'x-upload-content-length': String(m.size_bytes) };
  let response = await call(transport.google, 'POST', '/upload/drive/v3/files?uploadType=resumable', metadata, headers);
  assert.equal(response.code, 200);
  const location = new URL(response.headers.Location);
  const uploadHeaders = { host: 'www.googleapis.com', authorization: 'Bearer ' + keys.oauth,
    'content-range': 'bytes 0-' + (body.length - 1) + '/' + body.length,
    'content-length': String(body.length) };
  response = await call(transport.google, 'PUT', location.pathname + location.search, body, uploadHeaders);
  assert.equal(response.code, 201); assert.equal(sha(transport.files.get(metadata.id).bytes), m.sha256);
  response = await call(transport.google, 'POST', '/upload/drive/v3/files?uploadType=resumable', metadata, headers);
  assert.equal(response.code, 409); assert.equal(transport.counters.uploads, 1);
  response = await call(transport.google, 'PUT', location.pathname + location.search, body, uploadHeaders);
  assert.equal(response.code, 400); assert.equal(transport.failure, 'OVERWRITE_ATTEMPT');
});
