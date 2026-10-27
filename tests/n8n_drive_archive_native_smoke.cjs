'use strict';

// Test-only: execute the pinned n8n engine against synthetic loopback transports.
// Never import this harness into the service image or bind a real credential.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const dns = require('node:dns').promises;
const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { definitionHash } = require('../automation/n8n/ops/inspect-stored-metadata.cjs');

const FLAG = 'DROP_RATE_DR95_NATIVE_SMOKE';
const DR95 = 'DR95R2DriveArchiveV1';
const DR91 = 'DR91SuccessReceiptV1';
const CREDENTIAL = 'DR95SyntheticOAuthOnly';
const DR95_HASH = '3b05c263d6348471922fea7367e1ac76bc3ab0232b9aedca04adb00c6ef4a093';
const DR91_HASH = '8f8b466d808171b2458fc0bcfc7a64a3ae8271221e084353d7eaf35198981296';
const ACCOUNT = 'dropratetcg@gmail.com';
const FOLDER = '1NhFIsWesgxlf059UMdx65ps9kFMqQeO9';
const PERMISSION = 'synthetic-owner-permission';
const BASE = '/api/v1/automation/commands/storage/drive-archive/';
const CONTROL = '/api/v1/automation/control/receipt';
const MAX_BYTES = 16000000;
const PREFIX = '/tmp/drop-rate-dr95-native-';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const clone = object => JSON.parse(JSON.stringify(object));
function requireTrue(condition, reason) { if (!condition) throw new Error(reason); }

// Test-local process lifecycle: do not depend on the unmerged DR90 canary.
function signalGroup(child, signal) {
  if (!Number.isInteger(child?.pid) || child.pid <= 1) return;
  try { process.kill(-child.pid, signal); } catch {}
}
function startChild(command, args, env, { timeout = 60000, capture = false } = {}) {
  const record = { child: null, finished: false, failure: null, output: '', closed: null };
  record.child = spawn(command, args, { env, cwd: env.N8N_USER_FOLDER,
    stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  let bytes = 0;
  const timer = setTimeout(() => {
    record.failure = 'CHILD_TIMEOUT'; signalGroup(record.child, 'SIGKILL');
  }, timeout);
  for (const stream of [record.child.stdout, record.child.stderr]) {
    stream.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 256 * 1024) {
        record.failure = 'CHILD_OUTPUT_LIMIT'; signalGroup(record.child, 'SIGKILL');
      } else if (capture && stream === record.child.stdout) record.output += chunk.toString('utf8');
    });
  }
  record.closed = new Promise(resolve => {
    record.child.once('error', () => { record.failure = 'CHILD_START_FAILED'; });
    record.child.once('close', code => {
      clearTimeout(timer);
      signalGroup(record.child, 'SIGKILL');
      record.finished = true;
      if (code !== 0 && !record.failure) record.failure = 'CHILD_EXIT_FAILED';
      resolve();
    });
  });
  return record;
}
async function stopChild(record) {
  if (!record || record.finished) return;
  signalGroup(record.child, 'SIGTERM');
  await Promise.race([record.closed, sleep(1000)]);
  if (record.finished) return;
  signalGroup(record.child, 'SIGKILL');
  await Promise.race([record.closed, sleep(1000)]);
  requireTrue(record.finished, 'CHILD_TERMINATION_FAILED');
}

function sources() {
  return [
    ['dr-95-r2-drive-archive.json', DR95_HASH],
    ['dr-91-success-receipt.json', DR91_HASH],
  ].map(([file, expected]) => {
    const filename = path.join(__dirname, '../automation/n8n/workflows', file);
    requireTrue(fs.lstatSync(filename).isFile() && fs.statSync(filename).size < 1024 * 1024,
      'SOURCE_INVALID');
    const workflow = JSON.parse(fs.readFileSync(filename, 'utf8'));
    requireTrue(workflow.active === false && definitionHash(workflow) === expected, 'SOURCE_CHANGED');
    return workflow;
  });
}

function runtimeFixture(reviewed, webhookPath) {
  requireTrue(/^[a-f0-9]{48}$/.test(webhookPath), 'WEBHOOK_FIXTURE_INVALID');
  const fixture = clone(reviewed);
  const triggers = fixture.nodes.filter(node =>
    ['n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.manualTrigger'].includes(node.type));
  requireTrue(triggers.length === 2, 'TRIGGER_FIXTURE_INVALID');
  fixture.nodes = fixture.nodes.filter(node => !triggers.includes(node));
  for (const trigger of triggers) delete fixture.connections[trigger.name];
  fixture.nodes.push({
    id: 'dr95-native-smoke-webhook', name: 'Private Runtime Smoke Trigger',
    type: 'n8n-nodes-base.webhook', typeVersion: 2.1, position: [-200, 0],
    webhookId: webhookPath,
    parameters: { httpMethod: 'POST', path: webhookPath, responseMode: 'onReceived',
      options: { responseCode: 202 } },
  });
  fixture.connections['Private Runtime Smoke Trigger'] = {
    main: [[{ node: 'Initialize Weekly Scan', type: 'main', index: 0 }]],
  };
  for (const node of fixture.nodes) {
    if (node.type === 'n8n-nodes-base.googleDrive'
      || node.parameters.nodeCredentialType === 'googleDriveOAuth2Api') {
      node.credentials = { googleDriveOAuth2Api: { id: CREDENTIAL, name: 'Synthetic loopback only' } };
    }
  }
  assertFixtureIsExact(reviewed, fixture);
  return fixture;
}

function assertFixtureIsExact(reviewed, fixture) {
  assert.deepEqual(fixture.settings, reviewed.settings);
  assert.equal(fixture.active, false);
  const triggerTypes = ['n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.manualTrigger'];
  const unchanged = clone(fixture);
  unchanged.nodes = unchanged.nodes.filter(node => node.id !== 'dr95-native-smoke-webhook');
  for (const node of unchanged.nodes) delete node.credentials;
  unchanged.nodes = reviewed.nodes.map(node =>
    triggerTypes.includes(node.type) ? clone(node) : unchanged.nodes.find(item => item.id === node.id));
  delete unchanged.connections['Private Runtime Smoke Trigger'];
  for (const trigger of reviewed.nodes.filter(node => triggerTypes.includes(node.type))) {
    unchanged.connections[trigger.name] = clone(reviewed.connections[trigger.name]);
  }
  assert.deepEqual(unchanged, reviewed);
}

function temporaryState() {
  const root = fs.mkdtempSync(PREFIX);
  fs.chmodSync(root, 0o700);
  const nonce = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(path.join(root, 'owner'), nonce, { flag: 'wx', mode: 0o600 });
  const info = fs.lstatSync(root);
  return { root, nonce, dev: info.dev, ino: info.ino };
}

function cleanup(state) {
  if (!/^\/tmp\/drop-rate-dr95-native-[A-Za-z0-9]{6}$/.test(state.root)) return false;
  try {
    const info = fs.lstatSync(state.root);
    if (!info.isDirectory() || info.isSymbolicLink() || info.dev !== state.dev || info.ino !== state.ino
      || fs.realpathSync(state.root) !== state.root
      || fs.readFileSync(path.join(state.root, 'owner'), 'utf8') !== state.nonce) return false;
    fs.rmSync(state.root, { recursive: true });
    return true;
  } catch { return false; }
}

function networkGuard(ports) {
  requireTrue(ports.every(port => Number.isInteger(port) && port > 0 && port <= 65535), 'PORT_INVALID');
  return "'use strict';\n"
    + "const net=require('node:net'),dns=require('node:dns'),dgram=require('node:dgram');\n"
    + 'const ports=new Set(' + JSON.stringify([...ports, 443]) + ');\n'
    + "const original=net.Socket.prototype.connect;\n"
    + "net.Socket.prototype.connect=function(...args){const first=Array.isArray(args[0])?args[0][0]:args[0];"
    + "const opts=first&&typeof first==='object'?first:{port:first,host:args[1]};"
    + "const host=opts.host||'127.0.0.1';"
    + "if(!ports.has(Number(opts.port))||!(host==='127.0.0.1'||(host==='www.googleapis.com'&&Number(opts.port)===443)))"
    + "throw new Error('FIXTURE_NETWORK_BLOCKED');return original.apply(this,args);};\n"
    + "const lookup=dns.lookup;dns.lookup=function(host,...args){if(!['127.0.0.1','www.googleapis.com'].includes(host))"
    + "throw new Error('FIXTURE_NETWORK_BLOCKED');return lookup.call(this,host,...args);};\n"
    + "const promiseLookup=dns.promises.lookup;dns.promises.lookup=async function(host,...args){"
    + "if(!['127.0.0.1','www.googleapis.com'].includes(host))throw new Error('FIXTURE_NETWORK_BLOCKED');"
    + "return await promiseLookup.call(this,host,...args);};\n"
    + "dgram.createSocket=function(){throw new Error('FIXTURE_NETWORK_BLOCKED');};"
    + "require('node:module').syncBuiltinESMExports();\n";
}

function childEnvironment(root, ports, keys) {
  return {
    PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
    NODE_OPTIONS: '--require=' + path.join(root, 'network.cjs'), NODE_NO_WARNINGS: '1',
    NODE_EXTRA_CA_CERTS: path.join(root, 'mock-ca.crt'), TZ: 'UTC',
    DB_TYPE: 'sqlite', DB_SQLITE_DATABASE: path.join(root, '.n8n', 'database.sqlite'),
    N8N_USER_FOLDER: root, N8N_ENCRYPTION_KEY: keys.encryption,
    N8N_HOST: '127.0.0.1', N8N_LISTEN_ADDRESS: '127.0.0.1', N8N_PORT: String(ports.main),
    N8N_PROTOCOL: 'http', N8N_SECURE_COOKIE: 'false',
    N8N_EDITOR_BASE_URL: 'http://127.0.0.1:' + ports.main,
    WEBHOOK_URL: 'http://127.0.0.1:' + ports.main + '/',
    EXECUTIONS_MODE: 'regular', N8N_DEFAULT_BINARY_DATA_MODE: 'filesystem',
    N8N_BINARY_DATA_STORAGE_PATH: path.join(root, 'binary'),
    N8N_RUNNERS_MODE: 'internal', N8N_RUNNERS_BROKER_LISTEN_ADDRESS: '127.0.0.1',
    N8N_RUNNERS_BROKER_PORT: String(ports.broker), N8N_RUNNERS_AUTH_TOKEN: keys.runner,
    N8N_RUNNERS_MAX_CONCURRENCY: '1', N8N_RUNNERS_TASK_TIMEOUT: '60',
    N8N_RUNNERS_TASK_REQUEST_TIMEOUT: '60', N8N_RUNNERS_MAX_PAYLOAD: '67108864',
    N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false', NODE_FUNCTION_ALLOW_BUILTIN: 'crypto',
    N8N_DIAGNOSTICS_ENABLED: 'false', N8N_VERSION_NOTIFICATIONS_ENABLED: 'false',
    N8N_TEMPLATES_ENABLED: 'false', N8N_COMMUNITY_PACKAGES_ENABLED: 'false',
    N8N_LICENSE_AUTO_RENEW_ENABLED: 'false', N8N_SENTRY_DSN: '', N8N_FRONTEND_SENTRY_DSN: '',
    N8N_PERSONALIZATION_ENABLED: 'false', N8N_LOG_LEVEL: 'error', N8N_LOG_OUTPUT: 'console',
    N8N_GRACEFUL_SHUTDOWN_TIMEOUT: '3', EXECUTIONS_DATA_PRUNE: 'false',
    EXECUTIONS_DATA_SAVE_ON_SUCCESS: 'none', EXECUTIONS_DATA_SAVE_ON_ERROR: 'none',
    EXECUTIONS_DATA_SAVE_ON_PROGRESS: 'false', EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS: 'false',
    EXECUTIONS_TIMEOUT: '240', EXECUTIONS_TIMEOUT_MAX: '900',
    N8N_SSRF_PROTECTION_ENABLED: 'true', N8N_SSRF_BLOCKED_IP_RANGES: '0.0.0.0/0,::/0',
    N8N_SSRF_ALLOWED_IP_RANGES: '127.0.0.1/32',
    DROP_RATE_DRIVE_ARCHIVE_ENABLED: 'true',
    DROP_RATE_AUTOMATION_COMMAND_SECRET: keys.hmac,
    DROP_RATE_API_AUTOMATION_CONTROL_URL: 'http://127.0.0.1:' + ports.backend + CONTROL,
  };
}

function fixtureDataset({ large = true } = {}) {
  // Synthetic transport fixtures, not a proof of real R2 archive eligibility.
  const blobs = new Map(), archives = [];
  const make = (kind, label, data) => {
    const manifest = Buffer.from(JSON.stringify({ fixture: label, members: data.map(sha) }) + '\n');
    const member = (bytes, index) => {
      blobs.set(sha(bytes), bytes);
      const isManifest = index === data.length;
      return { sha256: sha(bytes), size_bytes: bytes.length,
        file_name: 'drop-rate-' + kind.toLowerCase() + '-' + sha(bytes)
          + (isManifest ? '.manifest.json' : '.ndjson.gz'),
        mime_type: isManifest ? 'application/json' : 'application/gzip',
        role: isManifest ? 'MANIFEST' : kind === 'REFERENCE_HISTORY' ? 'HISTORY' : 'SOURCE' };
    };
    const archive = { kind, manifest_sha256: sha(manifest), archive_id: 'synthetic-' + label,
      copy_status: 'PENDING', last_recorded_verification_at: null,
      objects: [...data, manifest].map(member) };
    archives.push(archive);
    return archive;
  };
  make('REFERENCE_HISTORY', 'history-a', [Buffer.alloc(large ? MAX_BYTES : 32, 65)]);
  make('REFERENCE_HISTORY', 'history-b', [Buffer.alloc(large ? MAX_BYTES : 32, 66)]);
  make('OPENLIBRARY_REVIEWED', 'reviewed-source', [Buffer.from('synthetic held factual evidence\n'),
    Buffer.from('synthetic receipt metadata\n')]);
  return { blobs, archives };
}

function countFiles(root) {
  if (!fs.existsSync(root)) return 0;
  let count = 0;
  for (const item of fs.readdirSync(root, { withFileTypes: true })) {
    requireTrue(!item.isSymbolicLink(), 'BINARY_PATH_INVALID');
    count += item.isDirectory() ? countFiles(path.join(root, item.name)) : 1;
  }
  return count;
}

function syntheticTransport(dataset, keys, binaryRoot) {
  const files = new Map(), reservations = new Map(), sessions = new Map();
  const verified = new Set(), complete = new Set(), receipts = new Set();
  const events = [];
  const counters = { google_requests: 0, backend_requests: 0, creations: 0, uploads: 0,
    downloads: 0, source_reads: 0, readbacks: 0, completions: 0, success_receipts: 0,
    replayed_success_receipts: 0, conflicts: 0, generated_ids: 0, binary_observed: false };
  let failure = null, generated = 0;
  const owners = [{ emailAddress: ACCOUNT, permissionId: PERMISSION }];
  const permissions = [{ role: 'owner', type: 'user', emailAddress: ACCOUNT }];
  const folder = { id: FOLDER, name: 'Drop Rate - Pricing History Archives',
    mimeType: 'application/vnd.google-apps.folder', trashed: false, shared: false,
    owners, permissions, capabilities: { canAddChildren: true } };
  const properties = (a, m) => ({ drSchema: 'drive-copy-v1', drKind: a.kind,
    drManifest: a.manifest_sha256, drObject: m.sha256 });
  const metadata = record => ({ ...record.metadata, size: String(record.bytes.length),
    sha256Checksum: sha(record.bytes), owners, permissions, trashed: false, shared: false });
  const locate = command => {
    const a = dataset.archives.find(item =>
      item.kind === command.kind && item.manifest_sha256 === command.manifest_sha256);
    requireTrue(a, 'UNKNOWN_ARCHIVE');
    const m = a.objects.find(item => item.sha256 === command.object_sha256);
    return { a, m, key: a.manifest_sha256 + ':' + command.object_sha256 };
  };
  const json = (response, code, body, headers = {}) => {
    response.writeHead(code, { 'Content-Type': 'application/json', ...headers });
    response.end(JSON.stringify(body));
  };
  const readBody = async (request, maximum) => {
    const chunks = []; let size = 0;
    for await (const chunk of request) {
      size += chunk.length; requireTrue(size <= maximum, 'REQUEST_TOO_LARGE'); chunks.push(chunk);
    }
    return Buffer.concat(chunks);
  };
  const wrap = handler => async (request, response) => {
    try { await handler(request, response); }
    catch (error) {
      // Only fixed test assertions are classified. Never print a request or token.
      failure = /^[A-Z0-9_]{1,80}$/.test(error.message) ? error.message : 'MOCK_CONTRACT_FAILED';
      if (!response.headersSent) json(response, 400, { accepted: false });
      else response.destroy();
    }
  };
  const google = wrap(async (request, response) => {
    counters.google_requests += 1; requireTrue(counters.google_requests < 500, 'REQUEST_BUDGET');
    requireTrue(request.headers.host === 'www.googleapis.com', 'GOOGLE_HOST_INVALID');
    requireTrue(request.headers.authorization === 'Bearer ' + keys.oauth, 'SYNTHETIC_OAUTH_REQUIRED');
    const url = new URL(request.url, 'https://www.googleapis.com');
    requireTrue(!['PATCH', 'DELETE'].includes(request.method), 'EXISTING_FILE_WRITE_FORBIDDEN');
    if (request.method === 'GET' && url.pathname === '/drive/v3/about') {
      json(response, 200, { user: { emailAddress: ACCOUNT, permissionId: PERMISSION } }); return;
    }
    if (request.method === 'GET' && url.pathname === '/drive/v3/files/' + FOLDER) {
      json(response, 200, folder); return;
    }
    if (request.method === 'GET' && url.pathname === '/drive/v3/files/generateIds') {
      counters.generated_ids += 1;
      json(response, 200, { ids: ['SYNTHETIC_GENERATED_ID_' + (++generated)] }); return;
    }
    if (request.method === 'GET' && url.pathname.startsWith('/drive/v3/files/')) {
      const id = url.pathname.slice('/drive/v3/files/'.length);
      const record = files.get(id);
      if (!record) { json(response, 404, { error: { code: 404, message: 'Synthetic missing ID' } }); return; }
      if (url.searchParams.get('alt') === 'media') {
        counters.downloads += 1; events.push('download:' + id);
        response.writeHead(200, { 'Content-Type': record.metadata.mimeType,
          'Content-Length': record.bytes.length, 'Content-Disposition': 'attachment; filename="fixture.bin"' });
        response.end(record.bytes); return;
      }
      json(response, 200, metadata(record)); return;
    }
    if (request.method === 'POST' && url.pathname === '/upload/drive/v3/files'
      && url.searchParams.get('uploadType') === 'resumable') {
      const data = JSON.parse((await readBody(request, 8192)).toString());
      const reservation = [...reservations.values()].find(value => value.file_id === data.id);
      requireTrue(reservation, 'UNRESERVED_CREATE');
      const { a, m } = locate(reservation);
      assert.deepEqual(data, { id: reservation.file_id, name: m.file_name, mimeType: m.mime_type,
        parents: [FOLDER], appProperties: properties(a, m) });
      requireTrue(request.headers['x-upload-content-type'] === m.mime_type
        && request.headers['x-upload-content-length'] === String(m.size_bytes), 'UPLOAD_HEADERS_INVALID');
      requireTrue(events.includes('source:' + m.sha256), 'SOURCE_NOT_VERIFIED_FIRST');
      counters.binary_observed ||= countFiles(binaryRoot) > 0;
      if (files.has(data.id)) { counters.conflicts += 1; json(response, 409, { error: { code: 409 } }); return; }
      const session = 'synthetic_session_' + sessions.size;
      sessions.set(session, { metadata: data, member: m });
      counters.creations += 1; events.push('session:' + data.id);
      json(response, 200, {}, { Location: 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=' + session });
      return;
    }
    if (request.method === 'PUT' && url.pathname === '/upload/drive/v3/files') {
      const session = sessions.get(url.searchParams.get('upload_id'));
      requireTrue(session, 'UNKNOWN_UPLOAD_SESSION');
      const { metadata: data, member: m } = session;
      requireTrue(request.headers['content-range'] === 'bytes 0-' + (m.size_bytes - 1) + '/' + m.size_bytes,
        'UPLOAD_RANGE_INVALID');
      const bytes = await readBody(request, MAX_BYTES);
      requireTrue(bytes.length === m.size_bytes && sha(bytes) === m.sha256, 'UPLOAD_BYTES_CHANGED');
      requireTrue(request.headers['content-length'] === String(bytes.length), 'UPLOAD_LENGTH_INVALID');
      requireTrue(!files.has(data.id), 'OVERWRITE_ATTEMPT');
      files.set(data.id, { metadata: data, bytes });
      counters.uploads += 1; events.push('upload:' + data.id);
      json(response, 201, { id: data.id }); return;
    }
    throw new Error('GOOGLE_ROUTE_UNEXPECTED');
  });
  const backend = wrap(async (request, response) => {
    counters.backend_requests += 1; requireTrue(counters.backend_requests < 180, 'REQUEST_BUDGET');
    requireTrue(request.method === 'POST', 'BACKEND_METHOD_INVALID');
    const binary = request.url === BASE + 'verify-readback';
    const bytes = await readBody(request, binary ? MAX_BYTES : 8192);
    const envelope = binary
      ? Buffer.from(String(request.headers['x-drop-rate-command'] || ''), 'base64url') : bytes;
    requireTrue(envelope.length <= 8192, 'ENVELOPE_TOO_LARGE');
    const timestamp = request.headers['x-drop-rate-timestamp'];
    const signature = request.headers['x-drop-rate-signature'];
    requireTrue(/^\d{10}$/.test(timestamp) && Math.abs(Date.now() / 1000 - Number(timestamp)) < 300,
      'SIGNATURE_TIME_INVALID');
    const expected = 'sha256=' + crypto.createHmac('sha256', keys.hmac)
      .update(timestamp + '.').update(envelope).digest('hex');
    requireTrue(typeof signature === 'string' && signature.length === expected.length
      && crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected)), 'SIGNATURE_INVALID');
    const command = JSON.parse(envelope.toString());
    requireTrue(/^\d+$/.test(command.execution_id), 'EXECUTION_ID_INVALID');
    if (request.url === CONTROL) {
      requireTrue(command.workflow_key === 'dr-95-r2-drive-archive' && command.status === 'SUCCEEDED',
        'SUCCESS_RECEIPT_INVALID');
      const match = /^drive-archive:(reference_history|openlibrary_reviewed):([a-f0-9]{64})$/.exec(command.idempotency_key);
      requireTrue(match && complete.has(match[2]), 'SUCCESS_BEFORE_COMPLETION');
      if (receipts.has(command.idempotency_key)) counters.replayed_success_receipts += 1;
      else { receipts.add(command.idempotency_key); counters.success_receipts += 1; }
      events.push('DR91:' + match[2]);
      json(response, 200, { accepted: true, status: 'SUCCEEDED', workflow_key: command.workflow_key,
        execution_id: command.execution_id, duplicate_owner_receipts: 0 }); return;
    }
    requireTrue(command.schema_version === 1, 'COMMAND_VERSION_INVALID');
    const d = command.destination;
    assert.deepEqual(d, { account_email: ACCOUNT, account_permission_id: PERMISSION,
      folder_id: FOLDER, folder_name: folder.name, folder_mime_type: folder.mimeType,
      folder_trashed: false, folder_shared: false, folder_owner_email: ACCOUNT,
      folder_owner_permission_id: PERMISSION, permission_roles: ['owner'], checked_at: d?.checked_at });
    requireTrue(Number.isFinite(Date.parse(d.checked_at)) && Date.now() - Date.parse(d.checked_at) < 300000,
      'DESTINATION_STALE');
    const accepted = { accepted: true, execution_id: command.execution_id };
    if (request.url === BASE + 'plan') {
      requireTrue(command.action === 'PLAN_DRIVE_ARCHIVE_COPY' && command.limit === 2, 'PLAN_INVALID');
      requireTrue(['REFERENCE_HISTORY', 'OPENLIBRARY_REVIEWED'].includes(command.kind), 'PLAN_KIND_INVALID');
      const cursor = 'opaque.synthetic.' + command.kind;
      requireTrue(command.cursor === null || command.cursor === cursor, 'CURSOR_INVALID');
      const page = command.cursor === null ? [] : dataset.archives.filter(a => a.kind === command.kind)
        .map(a => ({ ...clone(a), copy_status: complete.has(a.manifest_sha256) ? 'RECORDED_BYTES_VERIFIED' : 'PENDING',
          last_recorded_verification_at: complete.has(a.manifest_sha256) ? new Date().toISOString() : null }));
      json(response, 200, { ...accepted, archives: page, blocked_archives: [],
        has_more: command.cursor === null, next_cursor: command.cursor === null ? cursor : null,
        scan_scope: 'PAGE', drive_current_availability: 'NOT_ASSESSED', history_cleanup_authorised: false }); return;
    }
    const { a, m, key } = locate(command);
    if (request.url === BASE + 'complete') {
      requireTrue(command.action === 'COMPLETE_DRIVE_ARCHIVE_COPY', 'COMPLETE_INVALID');
      requireTrue(a.objects.every(member => verified.has(a.manifest_sha256 + ':' + member.sha256)),
        'COMPLETION_BEFORE_READBACK');
      complete.add(a.manifest_sha256); counters.completions += 1; events.push('complete:' + a.manifest_sha256);
      json(response, 200, { ...accepted, status: 'ARCHIVE_COPY_RECORDED', archive_id: a.archive_id,
        manifest_sha256: a.manifest_sha256, objects_verified: a.objects.length,
        receipt_sha256: sha('complete:' + a.manifest_sha256), completed_at: new Date().toISOString(),
        history_cleanup_authorised: false }); return;
    }
    requireTrue(m, 'UNKNOWN_MEMBER');
    if (request.url === BASE + 'reserve') {
      requireTrue(command.action === 'RESERVE_DRIVE_ARCHIVE_FILE'
        && /^SYNTHETIC_GENERATED_ID_\d+$/.test(command.proposed_file_id), 'RESERVE_INVALID');
      if (!reservations.has(key)) reservations.set(key, { kind: a.kind, manifest_sha256: a.manifest_sha256,
        object_sha256: m.sha256, file_id: 'SYNTHETIC_CAS_WINNER_' + reservations.size,
        file_name: m.file_name, app_properties: properties(a, m) });
      const reserved = reservations.get(key); events.push('reserve:' + reserved.file_id);
      json(response, 200, { ...accepted, file_id: reserved.file_id, file_name: reserved.file_name,
        app_properties: reserved.app_properties }); return;
    }
    const reserved = reservations.get(key);
    requireTrue(reserved, 'MEMBER_NOT_RESERVED');
    if (request.url === BASE + 'object') {
      requireTrue(command.action === 'READ_DRIVE_ARCHIVE_OBJECT', 'OBJECT_INVALID');
      const body = dataset.blobs.get(m.sha256);
      counters.source_reads += 1; events.push('source:' + m.sha256);
      response.writeHead(200, { 'Content-Type': m.mime_type, 'Content-Length': body.length,
        'X-Drop-Rate-Content-SHA256': m.sha256, 'Cache-Control': 'no-store' }); response.end(body); return;
    }
    if (request.url === BASE + 'verify-readback') {
      requireTrue(command.action === 'VERIFY_DRIVE_ARCHIVE_READBACK', 'READBACK_INVALID');
      requireTrue(bytes.length === m.size_bytes && sha(bytes) === m.sha256, 'READBACK_BYTES_CHANGED');
      assert.deepEqual(command.drive_file, { id: reserved.file_id, name: m.file_name,
        parents: [FOLDER], owner_email: ACCOUNT, owner_permission_id: PERMISSION,
        shared: false, trashed: false, mime_type: m.mime_type, size_bytes: m.size_bytes,
        app_properties: reserved.app_properties });
      requireTrue(events.includes('download:' + reserved.file_id), 'READBACK_WITHOUT_NATIVE_DOWNLOAD');
      counters.binary_observed ||= countFiles(binaryRoot) > 0;
      verified.add(key); counters.readbacks += 1; events.push('verify:' + reserved.file_id);
      json(response, 200, { ...accepted, status: 'BYTES_VERIFIED', object_sha256: m.sha256,
        size_bytes: m.size_bytes, file_id: reserved.file_id, verified_at: new Date().toISOString(),
        receipt_sha256: sha('verified:' + key) }); return;
    }
    throw new Error('BACKEND_ROUTE_UNEXPECTED');
  });
  return { google, backend, counters, events, files, reservations, complete, receipts,
    get failure() { return failure; } };
}

async function listen(server, port = 0) {
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  return server.address().port;
}
async function close(server) {
  if (!server) return;
  server.closeAllConnections?.(); await new Promise(resolve => server.close(resolve));
}
async function localRequest(port, requestPath, post = false) {
  return await new Promise((resolve, reject) => {
    const request = http.request({ hostname: '127.0.0.1', port, path: requestPath, agent: false,
      method: post ? 'POST' : 'GET', timeout: 3000, headers: { 'Content-Type': 'application/json' } }, response => {
      response.resume(); response.once('end', () => resolve(response.statusCode));
    });
    request.once('timeout', () => request.destroy(new Error('LOCAL_TIMEOUT')));
    request.once('error', reject); request.end(post ? '{}' : undefined);
  });
}
function openDatabase(state) {
  requireTrue(/^\/tmp\/drop-rate-dr95-native-[A-Za-z0-9]{6}$/.test(state.root), 'DATABASE_PATH_INVALID');
  const { DatabaseSync } = require('node:sqlite');
  return new DatabaseSync(path.join(state.root, '.n8n', 'database.sqlite'), { readOnly: true, timeout: 250 });
}
function inspectDefinitions(db, fixture, success, published) {
  const rows = db.prepare('SELECT id,nodes,connections,settings,active,activeVersionId FROM workflow_entity ORDER BY id').all();
  requireTrue(rows.length === 2, 'UNEXPECTED_WORKFLOW');
  for (const expected of [fixture, success]) {
    const row = rows.find(item => item.id === expected.id);
    requireTrue(row, 'WORKFLOW_MISSING');
    assert.deepEqual(JSON.parse(row.nodes), expected.nodes);
    assert.deepEqual(JSON.parse(row.connections), expected.connections);
    assert.deepEqual(JSON.parse(row.settings), expected.settings);
    if (published) {
      requireTrue(row.activeVersionId, 'WORKFLOW_UNPUBLISHED');
      const version = db.prepare('SELECT nodes,connections FROM workflow_history WHERE workflowId=? AND versionId=?')
        .get(row.id, row.activeVersionId);
      assert.deepEqual(JSON.parse(version.nodes), expected.nodes);
      assert.deepEqual(JSON.parse(version.connections), expected.connections);
    } else requireTrue(row.active === 0 && row.activeVersionId === null, 'IMPORT_ACTIVE');
  }
}
function staticData(db) {
  const row = db.prepare('SELECT staticData FROM workflow_entity WHERE id=?').get(DR95);
  const raw = JSON.parse(row.staticData || '{}');
  return raw.global || {};
}
function ensureNoSavedExecutionData(db, binaryRoot) {
  requireTrue(db.prepare('SELECT count(*) AS n FROM execution_entity').get().n === 0, 'EXECUTION_RETAINED');
  requireTrue(db.prepare('SELECT count(*) AS n FROM execution_data').get().n === 0, 'NODE_DATA_RETAINED');
  requireTrue(countFiles(binaryRoot) === 0, 'BINARY_DATA_RETAINED');
}

async function run(environment = process.env) {
  if (!environment[FLAG] || environment[FLAG] === 'false') return null;
  let stage = 'PREFLIGHT', state, db, runtime, googleServer, backendServer, mainReserve, brokerReserve, transport;
  const children = [];
  let result;
  const deadline = Date.now() + 480000;
  const remaining = max => {
    const duration = Math.min(max, deadline - Date.now());
    requireTrue(duration > 0, 'SMOKE_TIMEOUT'); return duration;
  };
  try {
    requireTrue(environment[FLAG] === 'true', 'FLAG_INVALID');
    requireTrue(fs.existsSync('/.dockerenv')
      && Object.values(os.networkInterfaces()).flat().every(item => item.internal), 'NETWORK_NONE_REQUIRED');
    const googleAddress = await dns.lookup('www.googleapis.com', { all: true });
    requireTrue(googleAddress.length > 0 && googleAddress.every(item => item.address === '127.0.0.1'),
      'GOOGLE_LOOPBACK_MAPPING_REQUIRED');
    for (const file of ['/fixture-tls/cert.pem', '/fixture-tls/key.pem']) {
      const info = fs.lstatSync(file);
      requireTrue(info.isFile() && !info.isSymbolicLink() && info.size < 16384, 'TLS_FIXTURE_INVALID');
    }
    const [reviewed, success] = sources();
    const webhookPath = crypto.randomBytes(24).toString('hex');
    const fixture = runtimeFixture(reviewed, webhookPath);
    state = temporaryState();
    const keys = Object.fromEntries(['encryption', 'runner', 'hmac', 'oauth']
      .map(key => [key, crypto.randomBytes(32).toString('hex')]));
    fs.copyFileSync('/fixture-tls/cert.pem', path.join(state.root, 'mock-ca.crt'));
    transport = syntheticTransport(fixtureDataset(), keys, path.join(state.root, 'binary'));
    googleServer = https.createServer({ key: fs.readFileSync('/fixture-tls/key.pem'),
      cert: fs.readFileSync('/fixture-tls/cert.pem') }, transport.google);
    backendServer = http.createServer(transport.backend);
    for (const server of [googleServer, backendServer]) { server.requestTimeout = 65000; server.headersTimeout = 5000; }
    await listen(googleServer, 443);
    const ports = { backend: await listen(backendServer) };
    mainReserve = net.createServer(); brokerReserve = net.createServer();
    ports.main = await listen(mainReserve); ports.broker = await listen(brokerReserve);
    fs.writeFileSync(path.join(state.root, 'network.cjs'), networkGuard(Object.values(ports)), { flag: 'wx', mode: 0o600 });
    const env = childEnvironment(state.root, ports, keys);
    const command = async (args, maximum = 60000, capture = false) => {
      const child = startChild('n8n', args, env, { timeout: remaining(maximum), capture });
      children.push(child); await child.closed; requireTrue(!child.failure, 'N8N_COMMAND_FAILED');
      return child.output;
    };
    stage = 'PINNED_VERSION';
    requireTrue((await command(['--version'], 15000, true)).trim() === '2.32.6', 'VERSION_MISMATCH');
    const input = path.join(state.root, 'workflows.json');
    fs.writeFileSync(input, JSON.stringify([fixture, success]), { flag: 'wx', mode: 0o600 });
    stage = 'IMPORT_REVIEWED_WORKFLOW';
    await command(['import:workflow', '--input=' + input, '--activeState=false']);
    db = openDatabase(state); inspectDefinitions(db, fixture, success, false); db.close(); db = null;
    const credentials = path.join(state.root, 'credentials.json');
    fs.writeFileSync(credentials, JSON.stringify([{ id: CREDENTIAL, name: 'Synthetic loopback only',
      type: 'googleDriveOAuth2Api', data: { grantType: 'authorizationCode', clientId: 'synthetic-client',
        clientSecret: 'synthetic-no-real-secret', scope: 'https://www.googleapis.com/auth/drive',
        oauthTokenData: { access_token: keys.oauth, token_type: 'Bearer', expires_in: 86400,
          expires: new Date(Date.now() + 86400000).toISOString() } } }]), { flag: 'wx', mode: 0o600 });
    stage = 'IMPORT_SYNTHETIC_CREDENTIAL';
    await command(['import:credentials', '--input=' + credentials]);
    fs.rmSync(credentials);
    stage = 'PUBLISH_TEMPORARY_FIXTURE';
    await command(['publish:workflow', '--id=' + DR91], 30000);
    await command(['publish:workflow', '--id=' + DR95], 30000);
    db = openDatabase(state); inspectDefinitions(db, fixture, success, true);
    await close(mainReserve); mainReserve = null; await close(brokerReserve); brokerReserve = null;
    const startRuntime = async () => {
      runtime = startChild('n8n', ['start'], env, { timeout: remaining(320000), capture: true });
      children.push(runtime);
      const startup = Date.now() + remaining(50000);
      while (Date.now() < startup) {
        requireTrue(!runtime.finished && !runtime.failure, 'RUNTIME_FAILED');
        let ready = false; try { ready = await localRequest(ports.main, '/healthz/readiness') === 200; } catch {}
        const trigger = db.prepare('SELECT workflowId FROM webhook_entity WHERE workflowId=? AND method=?').get(DR95, 'POST');
        if (ready && trigger) return;
        await sleep(250);
      }
      throw new Error('WEBHOOK_NOT_READY');
    };
    const executeRun = async (previousExecution, expectedStatus) => {
      const code = await localRequest(ports.main, '/webhook/' + webhookPath, true);
      requireTrue([200, 202].includes(code), 'TRIGGER_FAILED');
      const finish = Date.now() + remaining(170000);
      while (Date.now() < finish) {
        requireTrue(!transport.failure, transport.failure || 'MOCK_CONTRACT_FAILED');
        requireTrue(!runtime.finished && !runtime.failure, 'RUNTIME_FAILED');
        const saved = staticData(db);
        if (saved.dr95_last_run?.execution_id !== previousExecution
          && saved.dr95_last_run?.status === expectedStatus) {
          for (let attempt = 0; attempt < 20; attempt++) {
            try { ensureNoSavedExecutionData(db, path.join(state.root, 'binary')); return saved; }
            catch { await sleep(100); }
          }
          ensureNoSavedExecutionData(db, path.join(state.root, 'binary'));
        }
        await sleep(250);
      }
      throw new Error('WORKFLOW_DID_NOT_FINISH');
    };
    stage = 'FIRST_AUTOMATIC_RUN';
    await startRuntime();
    const first = await executeRun(null, 'INCOMPLETE');
    requireTrue(first.dr95_last_run.reason === 'OBJECT_BUDGET'
      && first.dr95_checkpoint.kind_index === 0 && first.dr95_checkpoint.page.archive_index === 1
      && first.dr95_checkpoint.page.object_index === 0, 'BUDGET_CHECKPOINT_INVALID');
    requireTrue(transport.complete.size === 1 && transport.receipts.size === 1, 'FIRST_RUN_ORDER_INVALID');
    stage = 'RESTART_AND_RESUME';
    await stopChild(runtime);
    const durable = staticData(db); assert.deepEqual(durable, first);
    await startRuntime();
    const second = await executeRun(first.dr95_last_run.execution_id, 'COMPLETE');
    requireTrue(second.dr95_checkpoint.kind_index === 0 && second.dr95_checkpoint.page === null
      && second.dr95_checkpoint.cursors.every(value => value === null), 'SWEEP_RESET_INVALID');
    requireTrue(transport.complete.size === 3 && transport.receipts.size === 3, 'BOTH_KINDS_NOT_COMPLETE');
    const transfers = { uploads: transport.counters.uploads, downloads: transport.counters.downloads,
      source_reads: transport.counters.source_reads, generated_ids: transport.counters.generated_ids };
    requireTrue(transfers.uploads === 7 && transfers.downloads === 7 && transport.counters.readbacks === 7,
      'BINARY_TRANSFER_COUNT_INVALID');
    stage = 'REPLAY_COMPLETION_RECEIPTS';
    await executeRun(second.dr95_last_run.execution_id, 'COMPLETE');
    for (const [key, value] of Object.entries(transfers)) requireTrue(transport.counters[key] === value,
      'COMPLETED_COPY_REUPLOADED');
    requireTrue(transport.counters.replayed_success_receipts === 3, 'DR91_REPLAY_MISSING');
    requireTrue(transport.counters.binary_observed, 'FILESYSTEM_BINARY_PATH_UNTESTED');
    await stopChild(runtime);
    inspectDefinitions(db, fixture, success, true);
    ensureNoSavedExecutionData(db, path.join(state.root, 'binary'));
    const saved = JSON.stringify(staticData(db));
    for (const value of Object.values(keys)) requireTrue(!saved.includes(value), 'SECRET_IN_STATIC_DATA');
    requireTrue(!/command_signature|command_body|upload_url|"binary"|"destination"/.test(saved),
      'TRANSIENT_STATE_RETAINED');
    result = { status: 'NATIVE_SYNTHETIC_DR95_VERIFIED', n8n_version: '2.32.6',
      source_definition_sha256: DR95_HASH, runtime_fixture_sha256: definitionHash(fixture),
      fixture_mutations: ['private webhook replaces schedule/manual triggers', 'synthetic OAuth credential binding'],
      automatic_runs: 3, runtime_restarts: 1, archives: 3, objects: 7,
      native_drive_download_verified: true, http_resumable_create_verified: true,
      binary_disposal_verified: true, durable_static_resume_verified: true,
      completion_receipt_replay_verified: true, production_backend_verified: false,
      real_google_api_verified: false, real_oauth_verified: false };
  } catch (error) {
    const safe = /^[A-Z0-9_]{1,80}$/.test(error.message) ? error.message : 'FIXTURE_ASSERTION_FAILED';
    result = { status: 'NATIVE_SYNTHETIC_DR95_FAILED', stage, reason: safe,
      production_backend_verified: false, real_google_api_verified: false, real_oauth_verified: false };
    if (transport) result.counters = { ...transport.counters };
    if (db) {
      try {
        result.execution_states = db.prepare('SELECT mode,status,count(*) AS count FROM execution_entity GROUP BY mode,status LIMIT 6').all();
      } catch {}
    }
  } finally {
    let terminated = true;
    for (const child of children) { try { await stopChild(child); } catch { terminated = false; } }
    try { db?.close(); } catch {}
    await close(mainReserve); await close(brokerReserve); await close(googleServer); await close(backendServer);
    if (state && (!terminated || !cleanup(state))) {
      result = { status: 'NATIVE_SYNTHETIC_DR95_FAILED', stage: 'CLEANUP', reason: 'CLEANUP_FAILED',
        production_backend_verified: false, real_google_api_verified: false };
    } else if (result) result.cleanup_complete = true;
  }
  return result;
}

if (require.main === module) {
  run().then(result => {
    if (result) process.stdout.write(JSON.stringify(result) + '\n');
    if (result?.status !== 'NATIVE_SYNTHETIC_DR95_VERIFIED') process.exitCode = 1;
  }).catch(() => {
    process.stdout.write('{"status":"NATIVE_SYNTHETIC_DR95_FAILED","reason":"HARNESS_FAILED"}\n');
    process.exitCode = 1;
  });
}
module.exports = { FLAG, DR95, DR91, DR95_HASH, sources, runtimeFixture, assertFixtureIsExact,
  temporaryState, cleanup, networkGuard, childEnvironment, fixtureDataset, syntheticTransport,
  startChild, stopChild, run };
