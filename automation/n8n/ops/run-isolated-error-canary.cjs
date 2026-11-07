'use strict';

// This runs n8n itself, but exclusively in a new disposable SQLite directory.
// It never opens the installed instance's database or sends a real receipt.
// CI entry point (pinned image, --network none):
// DROP_RATE_N8N_ERROR_CANARY_ON_BOOT=true node /opt/drop-rate/ops/run-isolated-error-canary.cjs --smoke
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { definitionHash } = require('./inspect-stored-metadata.cjs');

const FLAG = 'DROP_RATE_N8N_ERROR_CANARY_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_ISOLATED_ERROR_CANARY';
const VERSION = '2.32.6';
const ERROR_ID = 'DR90GlobalErrorV1';
const CANARY_ID = 'DR90IsolatedRoutingCanaryV1';
const CANARY_KEY = 'dr-90-isolated-routing-canary';
const ERROR_MESSAGE = 'DROP_RATE_ISOLATED_ERROR_ROUTING_CANARY';
const DR90_SHA256 = '84d3d6db4fefe07890da33bbae543dc69369826e56fe64cca20d69c43060a011';
const CANARY_SHA256 = 'c8dfa99581634adbcd481d9e094d3dd05b30ba5abba0d2ce8ec6f2dc855b83fc';
const MAX_OUTPUT_BYTES = 256 * 1024;
const MAX_RECEIPT_BYTES = 4096;
const TOTAL_TIMEOUT_MS = 180000;
const TEMP_PREFIX = '/tmp/drop-rate-n8n-error-canary-';
const RECEIPT_PATH = '/isolated-control-receipt';
const WEBHOOK_PATH = '/webhook/drop-rate-isolated-error-canary';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const SAFE_FAILURES = new Set(['SOURCE_INVALID', 'PORT_INVALID', 'CHILD_TERMINATION_FAILED',
  'CHILD_TIMEOUT', 'CHILD_OUTPUT_LIMIT', 'CHILD_START_FAILED', 'CHILD_EXIT_FAILED',
  'TEMP_DATABASE_INVALID', 'TEMP_WORKFLOW_COUNT_INVALID', 'TEMP_WORKFLOW_MISSING',
  'TEMP_DEFINITION_CHANGED', 'TEMP_WORKFLOW_UNPUBLISHED', 'TEMP_PUBLISHED_DEFINITION_CHANGED',
  'TEMP_IMPORT_NOT_INACTIVE', 'RECEIPT_INVALID', 'LOCAL_RESPONSE_LIMIT', 'LOCAL_REQUEST_TIMEOUT',
  'CANARY_TIMEOUT', 'N8N_VERSION_MISMATCH', 'RUNTIME_UNAVAILABLE', 'RUNTIME_NOT_READY',
  'WEBHOOK_NOT_READY', 'WEBHOOK_NOT_ACCEPTED', 'AUTOMATIC_ROUTING_NOT_VERIFIED']);
const LOG_SIGNALS = [
  ['NETWORK_GUARD', /CANARY_NETWORK_BLOCKED/],
  ['SUBWORKFLOW_PERMISSION', /Error workflow execution blocked due to subworkflow settings/],
  ['ERROR_HANDLER_UNPUBLISHED', /not active and cannot be executed/],
  ['RUNNER_TIMEOUT', /Task request timed out|Task execution timed out|Task runner.*timed out/i],
  ['PORT_CONFLICT', /EADDRINUSE/],
];

function failure(reason, stage = 'PREFLIGHT') {
  return { event: EVENT, schema_version: 1, status: 'UNAVAILABLE', reason, stage,
    production_backend_verified: false };
}

function readSources() {
  const specs = [
    [path.join(__dirname, '..', 'workflows', 'dr-90-global-error.json'), ERROR_ID, DR90_SHA256],
    [path.join(__dirname, 'fixtures', 'error-routing-canary.json'), CANARY_ID, CANARY_SHA256],
  ];
  return specs.map(([filename, id, expected]) => {
    const info = fs.lstatSync(filename);
    if (!info.isFile() || info.size > 1024 * 1024) throw new Error('SOURCE_INVALID');
    const source = JSON.parse(fs.readFileSync(filename, 'utf8'));
    if (source.id !== id || source.active !== false || definitionHash(source) !== expected) {
      throw new Error('SOURCE_INVALID');
    }
    return source;
  });
}

function childEnvironment(root, ports, keys, guardFile) {
  // Deliberately do not spread process.env, inherit PATH, or read production
  // DB/URL/key settings. The only external input to run() is the exact opt-in.
  return {
    PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
    NODE_NO_WARNINGS: '1', NODE_OPTIONS: '--require=' + guardFile, TZ: 'UTC',
    DB_TYPE: 'sqlite', DB_SQLITE_DATABASE: path.join(root, '.n8n', 'database.sqlite'),
    N8N_USER_FOLDER: root, N8N_ENCRYPTION_KEY: keys.encryption,
    N8N_HOST: '127.0.0.1', N8N_LISTEN_ADDRESS: '127.0.0.1', N8N_PORT: String(ports.main),
    N8N_PROTOCOL: 'http', N8N_SECURE_COOKIE: 'false', N8N_EDITOR_BASE_URL: `http://127.0.0.1:${ports.main}`,
    WEBHOOK_URL: `http://127.0.0.1:${ports.main}/`, EXECUTIONS_MODE: 'regular',
    N8N_RUNNERS_MODE: 'internal', N8N_RUNNERS_BROKER_LISTEN_ADDRESS: '127.0.0.1',
    N8N_RUNNERS_BROKER_PORT: String(ports.broker), N8N_RUNNERS_AUTH_TOKEN: keys.runner,
    N8N_RUNNERS_MAX_CONCURRENCY: '1', N8N_RUNNERS_TASK_TIMEOUT: '15',
    N8N_RUNNERS_TASK_REQUEST_TIMEOUT: '20', N8N_RUNNERS_MAX_PAYLOAD: '1048576',
    N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false', NODE_FUNCTION_ALLOW_BUILTIN: 'crypto',
    N8N_DIAGNOSTICS_ENABLED: 'false', N8N_VERSION_NOTIFICATIONS_ENABLED: 'false',
    N8N_TEMPLATES_ENABLED: 'false', N8N_COMMUNITY_PACKAGES_ENABLED: 'false',
    N8N_LICENSE_AUTO_RENEW_ENABLED: 'false', N8N_SENTRY_DSN: '', N8N_FRONTEND_SENTRY_DSN: '',
    N8N_PERSONALIZATION_ENABLED: 'false', N8N_LOG_LEVEL: 'error', N8N_LOG_OUTPUT: 'console',
    N8N_GRACEFUL_SHUTDOWN_TIMEOUT: '3', EXECUTIONS_DATA_PRUNE: 'false',
    EXECUTIONS_DATA_SAVE_ON_SUCCESS: 'all', EXECUTIONS_DATA_SAVE_ON_ERROR: 'all',
    EXECUTIONS_DATA_SAVE_ON_PROGRESS: 'false', EXECUTIONS_TIMEOUT: '30',
    EXECUTIONS_TIMEOUT_MAX: '30',
    // Workflow HTTP traffic is separately restricted by n8n's SSRF filter.
    N8N_SSRF_PROTECTION_ENABLED: 'true', N8N_SSRF_BLOCKED_IP_RANGES: '0.0.0.0/0,::/0',
    N8N_SSRF_ALLOWED_IP_RANGES: '127.0.0.1/32',
    DROP_RATE_CANARY_TOKEN: keys.token,
    DROP_RATE_AUTOMATION_COMMAND_SECRET: keys.hmac,
    DROP_RATE_API_AUTOMATION_CONTROL_URL: `http://127.0.0.1:${ports.receipt}${RECEIPT_PATH}`,
  };
}

function networkGuardSource(ports) {
  if (!ports.every(value => Number.isInteger(value) && value > 0 && value <= 65535)) {
    throw new Error('PORT_INVALID');
  }
  // This preload also blocks non-workflow Node TCP traffic. No inherited proxy
  // variables or external hostname can turn the temporary receipt into egress.
  return `'use strict';
const net = require('node:net');
const dns = require('node:dns');
const dgram = require('node:dgram');
const allowed = new Set(${JSON.stringify(ports)});
const original = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const options = first && typeof first === 'object' ? first : {port:first,host:args[1]};
  const host = options.host || '127.0.0.1';
  if (host !== '127.0.0.1' || !allowed.has(Number(options.port))) {
    throw new Error('CANARY_NETWORK_BLOCKED');
  }
  return original.apply(this,args);
};
const lookup = dns.lookup;
dns.lookup = function(host,...args) {
  if (host !== '127.0.0.1') throw new Error('CANARY_NETWORK_BLOCKED');
  return lookup.call(this,host,...args);
};
if (dns.promises) {
  const lookupPromise = dns.promises.lookup;
  dns.promises.lookup = async function(host,...args) {
    if (host !== '127.0.0.1') throw new Error('CANARY_NETWORK_BLOCKED');
    return await lookupPromise.call(this,host,...args);
  };
}
dgram.createSocket = function() { throw new Error('CANARY_NETWORK_BLOCKED'); };
require('node:module').syncBuiltinESMExports();
`;
}

function createTemporaryState() {
  const root = fs.mkdtempSync(TEMP_PREFIX);
  fs.chmodSync(root, 0o700);
  const nonce = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(path.join(root, 'canary-owner'), nonce, { mode: 0o600, flag: 'wx' });
  const info = fs.lstatSync(root);
  return { root, nonce, dev: info.dev, ino: info.ino };
}

function removeTemporaryState(state) {
  const { root, nonce, dev, ino } = state;
  if (!/^\/tmp\/drop-rate-n8n-error-canary-[A-Za-z0-9]{6}$/.test(root)) return false;
  try {
    const info = fs.lstatSync(root);
    if (!info.isDirectory() || info.isSymbolicLink() || info.dev !== dev || info.ino !== ino
      || fs.realpathSync(root) !== root
      || fs.readFileSync(path.join(root, 'canary-owner'), 'utf8') !== nonce) return false;
    fs.rmSync(root, { recursive: true, force: false });
    return true;
  } catch { return false; }
}

function signalGroup(child, signal) {
  if (!Number.isInteger(child?.pid) || child.pid <= 1) return;
  try { process.kill(-child.pid, signal); } catch { /* Only this new process group. */ }
}

async function stopChild(record) {
  if (!record || record.finished) return;
  signalGroup(record.child, 'SIGTERM');
  await Promise.race([record.closed, sleep(1000)]);
  if (record.finished) return;
  signalGroup(record.child, 'SIGKILL');
  await Promise.race([record.closed, sleep(1000)]);
  if (!record.finished) throw new Error('CHILD_TERMINATION_FAILED');
}

function startChild(command, args, env, { timeout = 60000, capture = false } = {}) {
  const record = { child: null, finished: false, failure: null, output: '', closed: null, signals: new Set() };
  record.child = spawn(command, args, {
    env, cwd: env.N8N_USER_FOLDER, stdio: ['ignore', 'pipe', 'pipe'], detached: true,
  });
  let bytes = 0, signalTail = '';
  const timer = setTimeout(() => {
    record.failure = 'CHILD_TIMEOUT';
    signalGroup(record.child, 'SIGKILL');
  }, timeout);
  for (const stream of [record.child.stdout, record.child.stderr]) {
    stream.on('data', chunk => {
      bytes += chunk.length;
      const diagnosticText = signalTail + chunk.toString('utf8');
      for (const [name, pattern] of LOG_SIGNALS) if (pattern.test(diagnosticText)) record.signals.add(name);
      signalTail = diagnosticText.slice(-160);
      if (bytes > MAX_OUTPUT_BYTES) {
        record.failure = 'CHILD_OUTPUT_LIMIT';
        signalGroup(record.child, 'SIGKILL');
      } else if (capture && stream === record.child.stdout) {
        record.output += chunk.toString('utf8');
      }
    });
  }
  record.closed = new Promise(resolve => {
    record.child.once('error', () => { record.failure = 'CHILD_START_FAILED'; });
    record.child.once('close', code => {
      clearTimeout(timer);
      // The child has just exited: stop its remaining descendants now. Never
      // signal an old PID after other commands have completed and it can recycle.
      signalGroup(record.child, 'SIGKILL');
      record.finished = true;
      if (code !== 0 && !record.failure) record.failure = 'CHILD_EXIT_FAILED';
      resolve();
    });
  });
  return record;
}

async function command(args, env, children, timeout, capture = false) {
  const record = startChild('n8n', args, env, { timeout, capture });
  children.push(record);
  await record.closed;
  if (record.failure) throw new Error(record.failure);
  return record.output;
}

function openTemporaryDatabase(root) {
  // No production path parameter exists; root is a fresh mkdtemp capability.
  if (!/^\/tmp\/drop-rate-n8n-error-canary-[A-Za-z0-9]{6}$/.test(root)) {
    throw new Error('TEMP_DATABASE_INVALID');
  }
  const { DatabaseSync } = require('node:sqlite');
  return new DatabaseSync(path.join(root, '.n8n', 'database.sqlite'),
    { readOnly: true, timeout: 250, allowExtension: false });
}

function inspectTemporaryState(database, { published = false } = {}) {
  const rows = database.prepare(`SELECT id,name,active,activeVersionId,nodes,connections,settings,nodeGroups
    FROM workflow_entity ORDER BY id LIMIT 3`).all();
  if (rows.length !== 2) throw new Error('TEMP_WORKFLOW_COUNT_INVALID');
  for (const [id, expected] of [[ERROR_ID, DR90_SHA256], [CANARY_ID, CANARY_SHA256]]) {
    const row = rows.find(item => item.id === id);
    if (!row) throw new Error('TEMP_WORKFLOW_MISSING');
    const parsed = item => ({ id: row.id, name: row.name,
      nodes: JSON.parse(item.nodes), connections: JSON.parse(item.connections),
      settings: JSON.parse(row.settings || '{}'), nodeGroups: JSON.parse(item.nodeGroups || '[]') });
    if (definitionHash(parsed(row)) !== expected) throw new Error('TEMP_DEFINITION_CHANGED');
    if (published) {
      if (!row.activeVersionId) throw new Error('TEMP_WORKFLOW_UNPUBLISHED');
      const version = database.prepare(`SELECT nodes,connections,nodeGroups FROM workflow_history
        WHERE workflowId=? AND versionId=? LIMIT 1`).get(id, row.activeVersionId);
      if (!version || definitionHash(parsed(version)) !== expected) {
        throw new Error('TEMP_PUBLISHED_DEFINITION_CHANGED');
      }
    } else if (row.activeVersionId != null || row.active !== 0) {
      throw new Error('TEMP_IMPORT_NOT_INACTIVE');
    }
  }
  // Read execution metadata only; never SELECT saved node data or credentials.
  const executions = database.prepare(`SELECT CAST(id AS TEXT) AS id,workflowId,mode,status,stoppedAt
    FROM execution_entity ORDER BY id LIMIT 4`).all();
  return executions;
}

function executionEvidence(rows, receiptExecutionId) {
  if (rows.length !== 2) return null;
  const failed = rows.find(item => item.workflowId === CANARY_ID);
  const handler = rows.find(item => item.workflowId === ERROR_ID);
  if (!failed || !handler || failed.mode !== 'webhook' || failed.status !== 'error'
    || !failed.stoppedAt || handler.mode !== 'error' || handler.status !== 'success'
    || !handler.stoppedAt || failed.id !== receiptExecutionId || failed.id === handler.id) return null;
  return { failed_execution_mode: 'webhook', handler_execution_mode: 'error',
    failed_execution_count: 1, handler_execution_count: 1 };
}

function diagnosticExecutionState(database) {
  if (!database) return [];
  try {
    const modes = new Set(['webhook', 'error', 'manual', 'cli', 'trigger', 'integrated']);
    const statuses = new Set(['new', 'running', 'success', 'error', 'canceled', 'crashed', 'waiting', 'unknown']);
    return database.prepare(`SELECT id,workflowId,mode,status,stoppedAt FROM execution_entity
      ORDER BY id LIMIT 5`).all().map(row => ({
      workflow: row.workflowId === CANARY_ID ? 'CANARY' : row.workflowId === ERROR_ID ? 'DR90' : 'UNEXPECTED',
      mode: modes.has(row.mode) ? row.mode : 'UNEXPECTED',
      status: statuses.has(row.status) ? row.status : 'UNEXPECTED',
      stopped: Boolean(row.stoppedAt),
      ...(row.status === 'error' ? diagnosticErrorMetadata(database, row.id) : {}),
    }));
  } catch { return []; }
}

function diagnosticErrorMetadata(database, executionId) {
  // n8n stores a flatted value table. Select only its fixed result/error metadata
  // paths, bounded to a small temporary record. Never select runData, node inputs,
  // node outputs, descriptions, stacks, request bodies or the complete data blob.
  try {
    const query = database.prepare(`SELECT json_extract(data, ?) AS value FROM execution_data
      WHERE executionId=? AND length(CAST(data AS BLOB))<=524288 AND json_valid(data) LIMIT 1`);
    const read = jsonPath => query.get(jsonPath, executionId)?.value;
    const reference = value => typeof value === 'string' && /^(0|[1-9][0-9]{0,5})$/.test(value)
      ? Number(value) : null;
    const valueAt = value => {
      const index = reference(value);
      return index === null ? null : read('$[' + index + ']');
    };
    const resultIndex = reference(read('$[0].resultData'));
    if (resultIndex === null) return {};
    const lastNode = valueAt(read('$[' + resultIndex + '].lastNodeExecuted'));
    const errorIndex = reference(read('$[' + resultIndex + '].error'));
    const errorName = errorIndex === null ? null : valueAt(read('$[' + errorIndex + '].name'));
    const errorMessage = errorIndex === null ? null : valueAt(read('$[' + errorIndex + '].message'));
    const nodes = new Set(['Local Canary Webhook', 'Authenticate Local Canary', 'Expected Isolated Failure',
      'Workflow Error', 'Normalize Failure', 'Sign Control Receipt', 'Record Failure in FastAPI', 'Control Receipt Accepted?']);
    const names = new Set(['Error', 'TypeError', 'NodeApiError', 'NodeOperationError', 'ExpressionError',
      'WorkflowOperationError', 'SubworkflowOperationError', 'TaskExecutionTimeoutError', 'TaskRequestTimeoutError']);
    let signal = 'UNCLASSIFIED';
    if (typeof errorMessage === 'string' && errorMessage.length <= 2048) {
      if (/automation_control_receipt_failed_http_/.test(errorMessage)) signal = 'RECEIPT_HTTP_STATUS';
      else if (/automation_control_receipt_not_accepted/.test(errorMessage)) signal = 'RECEIPT_RESPONSE_NOT_ACCEPTED';
      else if (/CANARY_NETWORK_BLOCKED/.test(errorMessage)) signal = 'NETWORK_GUARD';
      else if (/Task.*timed out/i.test(errorMessage)) signal = 'RUNNER_TIMEOUT';
      else if (/execution timed out|workflow timeout/i.test(errorMessage)) signal = 'WORKFLOW_TIMEOUT';
    }
    return { error_metadata: { last_node: nodes.has(lastNode) ? lastNode : 'UNEXPECTED',
      name: names.has(errorName) ? errorName : 'UNEXPECTED', signal } };
  } catch { return {}; }
}

function validateReceipt(body, headers, secret, rows, now = Date.now()) {
  if (!Buffer.isBuffer(body) || body.length > MAX_RECEIPT_BYTES) throw new Error('RECEIPT_INVALID');
  const timestamp = headers['x-drop-rate-timestamp'];
  const signature = headers['x-drop-rate-signature'];
  if (typeof timestamp !== 'string' || !/^\d{10}$/.test(timestamp)
    || Math.abs(now / 1000 - Number(timestamp)) > 60
    || typeof signature !== 'string' || !/^sha256=[a-f0-9]{64}$/.test(signature)) {
    throw new Error('RECEIPT_INVALID');
  }
  const expected = 'sha256=' + crypto.createHmac('sha256', secret)
    .update(timestamp + '.').update(body).digest('hex');
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) throw new Error('RECEIPT_INVALID');
  const item = JSON.parse(body.toString('utf8'));
  const keys = ['workflow_key', 'workflow_version', 'execution_id', 'status', 'idempotency_key',
    'occurred_at', 'owner_id', 'event_id', 'error_code', 'error_message'];
  const failed = rows.filter(row => row.workflowId === CANARY_ID);
  if (!item || typeof item !== 'object' || Object.keys(item).length !== keys.length
    || keys.some(key => !Object.hasOwn(item, key)) || failed.length !== 1
    || failed[0].mode !== 'webhook' || failed[0].status !== 'error'
    || !failed[0].stoppedAt || item.execution_id !== failed[0].id
    || item.workflow_key !== CANARY_KEY || item.workflow_version !== CANARY_ID
    || item.status !== 'FAILED' || item.owner_id !== null || item.event_id !== null
    || item.idempotency_key !== `n8n-error:${CANARY_ID}:${item.execution_id}`
    || item.error_code !== 'NodeOperationError' || item.error_message !== ERROR_MESSAGE
    || !Number.isFinite(Date.parse(item.occurred_at))
    || Math.abs(now - Date.parse(item.occurred_at)) > 60000) throw new Error('RECEIPT_INVALID');
  return item.execution_id;
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return server.address().port;
}

async function closeServer(server) {
  if (!server) return;
  server.closeAllConnections?.();
  await new Promise(resolve => server.close(resolve));
}

async function requestLocal(port, requestPath, { body = null, headers = {} } = {}) {
  return await new Promise((resolve, reject) => {
    const request = http.request({ hostname: '127.0.0.1', port, path: requestPath,
      method: body === null ? 'GET' : 'POST', headers, timeout: 1500, agent: false }, response => {
      let bytes = 0;
      response.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > 8192) request.destroy(new Error('LOCAL_RESPONSE_LIMIT'));
      });
      response.once('end', () => resolve(response.statusCode));
      response.once('error', reject);
    });
    request.once('timeout', () => request.destroy(new Error('LOCAL_REQUEST_TIMEOUT')));
    request.once('error', reject);
    request.end(body);
  });
}

async function run(env = process.env) {
  if (!env[FLAG] || env[FLAG] === 'false') return null;
  if (env[FLAG] !== 'true') return failure('INVALID_OPERATOR_FLAG');
  let state, receiptServer, mainReservation, brokerReservation, database, runtime;
  const children = [];
  let stage = 'PREFLIGHT', result, receiptCount = 0, rejectedReceipts = 0, receiptExecutionId = null;
  const deadline = Date.now() + TOTAL_TIMEOUT_MS;
  const remaining = maximum => {
    const value = Math.min(maximum, deadline - Date.now());
    if (value <= 0) throw new Error('CANARY_TIMEOUT');
    return value;
  };
  try {
    const sources = readSources();
    state = createTemporaryState();
    const keys = Object.fromEntries(['encryption', 'hmac', 'runner', 'token']
      .map(key => [key, crypto.randomBytes(32).toString('hex')]));
    receiptServer = http.createServer((request, response) => {
      let bytes = 0, chunks = [], ended = false;
      const reject = () => {
        if (ended) return;
        ended = true; rejectedReceipts += 1;
        response.writeHead(400, { 'Content-Type': 'application/json' });
        response.end('{"accepted":false}');
      };
      if (request.method !== 'POST' || request.url !== RECEIPT_PATH || receiptCount !== 0) {
        reject(); request.resume(); return;
      }
      request.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > MAX_RECEIPT_BYTES) { chunks = []; reject(); }
        else if (!ended) chunks.push(chunk);
      });
      request.once('error', reject);
      request.once('end', () => {
        if (ended) return;
        try {
          const rows = inspectTemporaryState(database, { published: true });
          receiptExecutionId = validateReceipt(Buffer.concat(chunks), request.headers, keys.hmac, rows);
          receiptCount += 1; ended = true;
          response.writeHead(200, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ accepted: true, workflow_key: CANARY_KEY,
            execution_id: receiptExecutionId }));
        } catch { reject(); }
      });
    });
    receiptServer.requestTimeout = 3000;
    receiptServer.headersTimeout = 3000;
    const ports = { receipt: await listen(receiptServer) };
    mainReservation = net.createServer(); brokerReservation = net.createServer();
    ports.main = await listen(mainReservation); ports.broker = await listen(brokerReservation);
    const guardFile = path.join(state.root, 'loopback-only.cjs');
    fs.writeFileSync(guardFile, networkGuardSource(Object.values(ports)), { mode: 0o600, flag: 'wx' });
    const childEnv = childEnvironment(state.root, ports, keys, guardFile);
    stage = 'VERSION';
    const version = await command(['--version'], childEnv, children, remaining(15000), true);
    if (version.trim() !== VERSION) throw new Error('N8N_VERSION_MISMATCH');
    const importFile = path.join(state.root, 'workflows.json');
    fs.writeFileSync(importFile, JSON.stringify(sources), { mode: 0o600, flag: 'wx' });
    stage = 'IMPORT';
    await command(['import:workflow', '--input=' + importFile, '--activeState=false'],
      childEnv, children, remaining(60000));
    database = openTemporaryDatabase(state.root);
    inspectTemporaryState(database);
    database.close(); database = null;
    stage = 'PUBLISH_TEMPORARY';
    // 2.32.6 loadErrorWorkflowData requires an activeVersion for DR90 as well.
    // Both publications occur only in the brand-new local database.
    for (const id of [ERROR_ID, CANARY_ID]) {
      await command(['publish:workflow', '--id=' + id], childEnv, children, remaining(30000));
    }
    database = openTemporaryDatabase(state.root);
    inspectTemporaryState(database, { published: true });
    await closeServer(mainReservation); mainReservation = null;
    await closeServer(brokerReservation); brokerReservation = null;
    stage = 'START';
    runtime = startChild('n8n', ['start'], childEnv, { timeout: remaining(75000) });
    children.push(runtime);
    const startupDeadline = Date.now() + remaining(45000);
    let ready = false;
    while (Date.now() < startupDeadline) {
      if (runtime.finished || runtime.failure) throw new Error('RUNTIME_UNAVAILABLE');
      try { ready = await requestLocal(ports.main, '/healthz/readiness') === 200; } catch { /* Still starting. */ }
      if (ready) break;
      await sleep(250);
    }
    if (!ready) throw new Error('RUNTIME_NOT_READY');
    // Readiness can precede trigger registration; poll only the disposable
    // webhook metadata. Never retry a triggering HTTP request.
    const webhookDeadline = Date.now() + remaining(15000);
    let registered = false;
    while (Date.now() < webhookDeadline) {
      registered = Boolean(database.prepare(`SELECT workflowId FROM webhook_entity
        WHERE workflowId=? AND method='POST' LIMIT 1`).get(CANARY_ID));
      if (registered) break;
      if (runtime.finished || runtime.failure) throw new Error('RUNTIME_UNAVAILABLE');
      await sleep(250);
    }
    if (!registered) throw new Error('WEBHOOK_NOT_READY');
    stage = 'TRIGGER';
    const status = await requestLocal(ports.main, WEBHOOK_PATH, {
      body: JSON.stringify({ canary: 'DR90_AUTOMATIC_ROUTING' }),
      headers: { 'Content-Type': 'application/json', 'X-Drop-Rate-Canary-Token': keys.token },
    });
    if (![200, 202].includes(status)) throw new Error('WEBHOOK_NOT_ACCEPTED');
    stage = 'VERIFY_AUTOMATIC_ROUTING';
    const executionDeadline = Date.now() + remaining(40000);
    let evidence;
    while (Date.now() < executionDeadline) {
      if (rejectedReceipts || receiptCount > 1) throw new Error('RECEIPT_INVALID');
      evidence = executionEvidence(inspectTemporaryState(database, { published: true }), receiptExecutionId);
      if (evidence && receiptCount === 1) break;
      if (runtime.finished || runtime.failure) throw new Error('RUNTIME_UNAVAILABLE');
      await sleep(250);
    }
    if (!evidence || receiptCount !== 1) throw new Error('AUTOMATIC_ROUTING_NOT_VERIFIED');
    await stopChild(runtime);
    // A late duplicate or extra execution invalidates the proof as well.
    evidence = executionEvidence(inspectTemporaryState(database, { published: true }), receiptExecutionId);
    if (!evidence || receiptCount !== 1 || rejectedReceipts) throw new Error('AUTOMATIC_ROUTING_NOT_VERIFIED');
    result = { event: EVENT, schema_version: 1, status: 'AUTOMATIC_ROUTING_VERIFIED',
      n8n_version: VERSION, source_sha256: DR90_SHA256, fixture_sha256: CANARY_SHA256,
      ...evidence, verified_receipt_count: 1, production_backend_verified: false };
  } catch (error) {
    // Never emit child output, exception messages, workflow code, signatures,
    // encryption material or production environment values.
    result = { ...failure('ISOLATED_CANARY_FAILED', stage),
      cause: SAFE_FAILURES.has(error?.message) ? error.message : 'UNCLASSIFIED',
      observations: { executions: diagnosticExecutionState(database),
        accepted_receipts: receiptCount, rejected_receipts: rejectedReceipts,
        runtime_signals: [...(runtime?.signals || [])].sort() } };
  } finally {
    let terminated = true;
    for (const child of children) {
      try { await stopChild(child); } catch { terminated = false; }
    }
    try { database?.close(); } catch { /* Read-only handle. */ }
    await closeServer(mainReservation); await closeServer(brokerReservation);
    await closeServer(receiptServer);
    if (state && (!terminated || !removeTemporaryState(state))) {
      result = failure('TEMPORARY_CLEANUP_FAILED', 'CLEANUP');
    } else if (result) result.cleanup_complete = true;
  }
  return result;
}

if (require.main === module) {
  run().then(result => {
    if (result) process.stdout.write(JSON.stringify(result) + '\n');
    if (process.argv.includes('--smoke') && result?.status !== 'AUTOMATIC_ROUTING_VERIFIED') process.exitCode = 1;
  }).catch(() => {
    process.stdout.write(JSON.stringify(failure('ISOLATED_CANARY_FAILED')) + '\n');
    if (process.argv.includes('--smoke')) process.exitCode = 1;
  });
}

module.exports = { FLAG, EVENT, VERSION, ERROR_ID, CANARY_ID, CANARY_KEY, ERROR_MESSAGE,
  DR90_SHA256, CANARY_SHA256, readSources, childEnvironment, networkGuardSource,
  createTemporaryState, removeTemporaryState, startChild, stopChild, inspectTemporaryState,
  executionEvidence, diagnosticExecutionState, validateReceipt, run };
