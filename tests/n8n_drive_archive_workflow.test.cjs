'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const workflow = JSON.parse(fs.readFileSync(path.join(__dirname,
  '../automation/n8n/workflows/dr-95-r2-drive-archive.json'), 'utf8'));
const nodes = Object.fromEntries(workflow.nodes.map(node => [node.name, node]));
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const ACCOUNT = 'dropratetcg@gmail.com';
const FOLDER = '1NhFIsWesgxlf059UMdx65ps9kFMqQeO9';
const SECRET = 'synthetic-archive-signature-not-production-' + 'a'.repeat(32);
const ENV = { DROP_RATE_DRIVE_ARCHIVE_ENABLED: 'true', DROP_RATE_AUTOMATION_COMMAND_SECRET: SECRET,
  DROP_RATE_API_AUTOMATION_CONTROL_URL: 'http://drop-rate-api-live.railway.internal:8000/api/v1/automation/control/receipt' };
const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
const response = body => ({ json: { statusCode: 200, body } });
const account = { user: { emailAddress: ACCOUNT, permissionId: 'synthetic-permission' } };
const folder = { id: FOLDER, name: 'Drop Rate - Pricing History Archives', mimeType: 'application/vnd.google-apps.folder',
  trashed: false, shared: false, owners: [{ emailAddress: ACCOUNT, permissionId: 'synthetic-permission' }],
  permissions: [{ role: 'owner', type: 'user', emailAddress: ACCOUNT }], capabilities: { canAddChildren: true } };
const dataBytes = Buffer.from('synthetic immutable archive bytes');
const manifestBytes = Buffer.from('{"synthetic_manifest":true}\n');
const blobs = new Map([[digest(dataBytes), dataBytes], [digest(manifestBytes), manifestBytes]]);
function archive(kind = 'REFERENCE_HISTORY') {
  const member = (bytes, suffix, mime_type, role) => ({ sha256: digest(bytes), size_bytes: bytes.length,
    file_name: 'drop-rate-' + kind.toLowerCase() + '-' + digest(bytes) + suffix, mime_type, role });
  return { kind, manifest_sha256: digest(manifestBytes), archive_id: 'synthetic-archive', copy_status: 'PENDING',
    last_recorded_verification_at: null,
    objects: [member(dataBytes, '.ndjson.gz', 'application/gzip', 'HISTORY'),
      member(manifestBytes, '.manifest.json', 'application/json', 'MANIFEST')] };
}
function binary(bytes, mimeType = 'application/gzip') {
  return { data: bytes.toString('base64'), mimeType, fileName: 'fixture.bin' };
}

async function execute(name, input, { refs = {}, state = {}, env = ENV } = {}) {
  const source = nodes[name].parameters.jsCode;
  const fn = new AsyncFunction('$input', '$', '$env', '$execution', '$getWorkflowStaticData', 'require', 'URL', source);
  const output = await fn.call({ helpers: { getBinaryDataBuffer: async (index, field) => {
    assert.equal(index, 0); assert.ok(input.binary?.[field]);
    return Buffer.from(input.binary[field].data, 'base64');
  } } }, { first: () => input }, key => {
    assert.ok(Object.hasOwn(refs, key), 'missing paired reference ' + key);
    return { item: refs[key] };
  }, env, { id: 'synthetic-execution-17' }, scope => {
    assert.equal(scope, 'global'); return state;
  }, name => { assert.equal(name, 'crypto'); return crypto; }, undefined);
  assert.equal(output.length, 1, name + ' must remain serial');
  return output[0];
}
async function initialize(state = {}) {
  return await execute('Initialize Weekly Scan', { json: {} }, { state });
}
async function pending() {
  const item = await initialize();
  item.json.ctx.checkpoint.page = { kind: 'REFERENCE_HISTORY', archives: [archive()], archive_index: 0,
    object_index: 0, has_more: false, next_cursor: null };
  return item;
}
async function destination(item, about = account, target = folder) {
  return await execute('Verify Current Destination', response(target), { refs: {
    'Advance Serial Work': item, 'Google Account Identity': response(about),
  } });
}
async function ready(item, phase) {
  item = clone(item); item.json.ctx.phase = phase; item.json.ctx.authorized_phase = null;
  item = await execute('Advance Serial Work', item);
  assert.equal(item.json.ctx.phase, 'DESTINATION');
  item = await destination(item);
  return await execute('Advance Serial Work', item);
}
async function signed(item) {
  const result = await execute('Sign Bounded Backend Command', item);
  const j = result.json;
  assert.equal(j.command_signature, 'sha256=' + crypto.createHmac('sha256', SECRET)
    .update(j.command_timestamp + '.' + j.command_body).digest('hex'));
  assert.equal(Buffer.from(j.command_envelope, 'base64url').toString(), j.command_body);
  assert.ok(!j.command_body.includes(SECRET));
  assert.ok(!j.command_body.includes('object_key'));
  return result;
}
function plan(archives = [], has_more = false, next_cursor = null, blocked_archives = []) {
  return { accepted: true, execution_id: 'synthetic-execution-17', archives, has_more, next_cursor, blocked_archives,
    scan_scope: 'PAGE', drive_current_availability: 'NOT_ASSESSED', history_cleanup_authorised: false };
}
function properties(ctx) {
  const p = ctx.checkpoint.page, a = p.archives[p.archive_index], m = a.objects[p.object_index];
  return { drSchema: 'drive-copy-v1', drKind: a.kind, drManifest: a.manifest_sha256, drObject: m.sha256 };
}
function file(ctx, bytes = null) {
  const p = ctx.checkpoint.page, m = p.archives[p.archive_index].objects[p.object_index];
  return { id: ctx.reservation.file_id, name: m.file_name, mimeType: m.mime_type,
    size: String(bytes?.length || 0), ...(bytes?.length ? { sha256Checksum: digest(bytes) } : {}),
    parents: [FOLDER], owners: clone(folder.owners), permissions: clone(folder.permissions),
    shared: false, trashed: false, appProperties: clone(ctx.reservation.app_properties) };
}
async function reserved() {
  let item = await ready(await pending(), 'RESERVE');
  item.json.ctx.proposed_file_id = 'UNUSED_PROPOSED_DRIVE_ID';
  const request = await signed(item);
  const member = archive().objects[0];
  return await execute('Accept Backend Metadata', response({ accepted: true,
    execution_id: item.json.ctx.execution_id, file_id: 'DURABLE_CAS_WINNER_FILE_ID',
    file_name: member.file_name, app_properties: properties(item.json.ctx) }),
  { refs: { 'Sign Bounded Backend Command': request } });
}

test('workflow stays disabled, credential-unbound, serial and execution-data saving is off', () => {
  assert.equal(workflow.active, false);
  assert.equal(workflow.settings.errorWorkflow, 'DR90GlobalErrorV1');
  assert.equal(workflow.settings.saveDataErrorExecution, 'none');
  assert.equal(workflow.settings.saveDataSuccessExecution, 'none');
  assert.equal(workflow.settings.saveManualExecutions, false);
  assert.equal(workflow.settings.saveExecutionProgress, false);
  assert.equal(workflow.settings.executionTimeout, 900);
  for (const node of workflow.nodes) {
    assert.equal(node.credentials, undefined);
    if (node.type === 'n8n-nodes-base.code') new AsyncFunction(node.parameters.jsCode);
    if (node.type === 'n8n-nodes-base.googleDrive') {
      assert.equal(node.typeVersion, 3); assert.equal(node.parameters.authentication, 'oAuth2');
      assert.ok(['download'].includes(node.parameters.operation));
    }
    // Pinned HTTP4.2 forces a response stream for a raw request body. Explicit
    // JSON response mode does not consume that stream; autodetect does.
    if (node.type === 'n8n-nodes-base.httpRequest' && node.parameters.contentType === 'raw') {
      assert.ok(['autodetect', 'file'].includes(node.parameters.options.response.response.responseFormat));
      assert.equal(node.parameters.options.response.response.fullResponse, true);
    }
  }
  for (const paths of Object.values(workflow.connections)) {
    for (const output of paths.main) assert.equal(output.length, 1);
  }
});

test('missing opt-in fails before credentials or backend requests are touched', async () => {
  await assert.rejects(() => execute('Initialize Weekly Scan', { json: {} }, { env: {} }), /drive_archive_disabled/);
  await assert.rejects(() => execute('Initialize Weekly Scan', { json: {} }, { env: { DROP_RATE_DRIVE_ARCHIVE_ENABLED: '1' } }), /drive_archive_disabled/);
});

test('destination evidence comes from fresh real-response fields and rejects wrong account/shared folder', async () => {
  const item = await execute('Advance Serial Work', await initialize());
  const valid = await destination(item);
  assert.equal(valid.json.ctx.destination.account_permission_id, account.user.permissionId);
  assert.ok(Math.abs(Date.now() - Date.parse(valid.json.ctx.destination.checked_at)) < 1000);
  for (const changed of [{ ...folder, shared: true }, { ...folder, trashed: true },
    { ...folder, id: 'another-folder' }, { ...folder, capabilities: { canAddChildren: false } },
    { ...folder, permissions: [...folder.permissions, { role: 'reader', type: 'anyone' }] }]) {
    await assert.rejects(() => destination(item, account, changed), /drive_/);
  }
  await assert.rejects(() => destination(item, { user: { ...account.user, emailAddress: 'wrong@example.invalid' } }), /account_mismatch/);
});

test('every backend command reacquires account/folder evidence, including binary readback and completion', async () => {
  for (const phase of ['PLAN', 'RESERVE', 'OBJECT', 'VERIFY', 'COMPLETE']) {
    let item = await pending(); item.json.ctx.phase = phase;
    const next = await execute('Advance Serial Work', item);
    assert.equal(next.json.ctx.phase, 'DESTINATION');
    assert.equal(next.json.ctx.pending_phase, phase);
    const checked = await destination(next);
    assert.equal(checked.json.ctx.authorized_phase, phase);
    checked.json.ctx.destination.checked_at = new Date(Date.now() - 300001).toISOString();
    const refreshed = await execute('Advance Serial Work', checked);
    assert.equal(refreshed.json.ctx.phase, 'DESTINATION');
    await assert.rejects(() => signed(checked), /evidence_stale/);
  }
});

test('empty pages continue on opaque cursors and both source kinds finish before the sweep resets', async () => {
  let item = await ready(await initialize(), 'PLAN');
  const first = await signed(item);
  assert.equal(JSON.parse(first.json.command_body).cursor, null);
  item = await execute('Accept Backend Metadata', response(plan([], true, 'v1.0.eABjaG9pY2U')),
    { refs: { 'Sign Bounded Backend Command': first } });
  item = await execute('Advance Serial Work', item);
  assert.equal(item.json.ctx.phase, 'DESTINATION');
  assert.equal(item.json.ctx.checkpoint.kind_index, 0);
  item = await destination(item); item = await execute('Advance Serial Work', item);
  const second = await signed(item);
  assert.equal(JSON.parse(second.json.command_body).cursor, 'v1.0.eABjaG9pY2U');
  item = await execute('Accept Backend Metadata', response(plan()), { refs: { 'Sign Bounded Backend Command': second } });
  item = await execute('Advance Serial Work', item); item = await destination(item);
  item = await execute('Advance Serial Work', item);
  const third = await signed(item);
  assert.equal(JSON.parse(third.json.command_body).kind, 'OPENLIBRARY_REVIEWED');
  item = await execute('Accept Backend Metadata', response(plan()), { refs: { 'Sign Bounded Backend Command': third } });
  item = await execute('Advance Serial Work', item);
  const state = {};
  const finish = await execute('Save Bounded Resume Checkpoint', item, { state });
  assert.equal(finish.json.status, 'COMPLETE');
  assert.equal(finish.json.completed_sweep, true);
  assert.deepEqual(state.dr95_checkpoint.cursors, [null, null]);
  assert.equal(state.dr95_checkpoint.kind_index, 0);
});

test('blocked archives cannot become a complete/no-work claim and retain oversized evidence', async () => {
  let item = await ready(await initialize(), 'PLAN'); const request = await signed(item);
  item = await execute('Accept Backend Metadata', response(plan([], false, null,
    [{ manifest_sha256: 'e'.repeat(64), reason: 'ARCHIVE_OBJECT_EXCEEDS_TRANSFER_BOUND',
      declared_size_bytes: 17000000, maximum_object_bytes: 16000000 }])),
  { refs: { 'Sign Bounded Backend Command': request } });
  item.json.ctx.checkpoint.kind_index = 2; item.json.ctx.checkpoint.page = null; item.json.ctx.phase = 'ADVANCE';
  item = await execute('Advance Serial Work', item);
  const finish = await execute('Save Bounded Resume Checkpoint', item, { state: {} });
  assert.equal(finish.json.status, 'INCOMPLETE');
  assert.equal(finish.json.blocked_archives, 1);
  assert.equal(finish.json.blocked_sample[0].declared_size_bytes, 17000000);
  assert.equal(finish.json.history_cleanup_authorised, false);
});

test('budget exhaustion persists a partial member index and resumes without skipping the remaining member', async () => {
  const state = {}; let item = await pending();
  item.json.ctx.checkpoint.page.object_index = 1;
  item.json.ctx.counters.objects = 32;
  item.json.ctx.destination = { transient: SECRET };
  item = await execute('Advance Serial Work', item);
  assert.equal(item.json.ctx.phase, 'FINISH');
  const finish = await execute('Save Bounded Resume Checkpoint', item, { state });
  assert.equal(finish.json.status, 'INCOMPLETE'); assert.equal(finish.json.resumable, true);
  assert.equal(state.dr95_last_run.status, 'INCOMPLETE');
  assert.equal(state.dr95_checkpoint.page.object_index, 1);
  assert.ok(!JSON.stringify(state).includes(SECRET));
  assert.ok(!JSON.stringify(state).includes('destination'));
  item = await execute('Advance Serial Work', await initialize(state));
  assert.equal(item.json.ctx.phase, 'GENERATE_ID');
  assert.equal(item.json.ctx.checkpoint.page.object_index, 1);
  assert.equal(item.json.ctx.counters.objects, 0);
});

test('malformed static state and nonadvancing plan pages fail without creating a Drive file', async () => {
  const state = { dr95_checkpoint: { version: 1, private_bytes: SECRET } };
  await assert.rejects(() => initialize(state), /checkpoint_schema_invalid/);
  const item = await ready(await initialize(), 'PLAN'); const request = await signed(item);
  await assert.rejects(() => execute('Accept Backend Metadata', response(plan([], true, null)),
    { refs: { 'Sign Bounded Backend Command': request } }), /not_advancing/);
  const wrong = archive(); wrong.objects[0].size_bytes = 16000001;
  await assert.rejects(() => execute('Accept Backend Metadata', response(plan([wrong])),
    { refs: { 'Sign Bounded Backend Command': request } }), /member_invalid/);
});

test('the returned durable reservation wins over a newly generated candidate ID', async () => {
  const item = await reserved();
  assert.equal(item.json.ctx.reservation.file_id, 'DURABLE_CAS_WINNER_FILE_ID');
  assert.equal(item.json.ctx.proposed_file_id, undefined);
  assert.equal(item.json.ctx.phase, 'LOOKUP');
  for (const name of ['Native Download Exact Reserved File']) {
    assert.equal(nodes[name].parameters.fileId.value, '={{ $json.ctx.reservation.file_id }}');
  }
  assert.ok(nodes['Begin Reserved-ID Resumable Create'].parameters.body.includes('id:$json.ctx.reservation.file_id'));
});

test('existing nonempty files are never overwritten, and 409 creation must return through exact metadata checks', async () => {
  const item = await reserved(), ctx = item.json.ctx;
  let next = await execute('Verify Reserved File Metadata', response(file(ctx, dataBytes)),
    { refs: { 'Advance Serial Work': item } });
  assert.equal(next.json.ctx.phase, 'DOWNLOAD');
  item.json.ctx.source_ready = true; item.binary = { source: binary(dataBytes) };
  next = await execute('Verify Reserved File Metadata', response(file(ctx, dataBytes)),
    { refs: { 'Advance Serial Work': item } });
  assert.equal(next.json.ctx.phase, 'DOWNLOAD'); assert.equal(next.binary, undefined);
  for (const changed of [{ ...file(ctx, dataBytes), sha256Checksum: 'f'.repeat(64) },
    { ...file(ctx), parents: ['different-folder'] }, { ...file(ctx), shared: true },
    { ...file(ctx), appProperties: {} }]) {
    await assert.rejects(() => execute('Verify Reserved File Metadata', response(changed),
      { refs: { 'Advance Serial Work': item } }), /drive_/);
  }
  const retry = await execute('Accept Resumable Creation Session', { json: { statusCode: 409 } },
    { refs: { 'Advance Serial Work': item } });
  assert.equal(retry.json.ctx.phase, 'LOOKUP');
  await assert.rejects(() => execute('Verify Reserved File Metadata', { json: { statusCode: 404 } },
    { refs: { 'Advance Serial Work': retry } }), /missing_after_creation/);
});

test('both fetched R2 bytes and fresh Drive bytes are hashed before their next side effect', async () => {
  let item = await ready(await reserved(), 'OBJECT'); const request = await signed(item);
  const m = archive().objects[0];
  const source = { json: { statusCode: 200, headers: { 'content-length': String(m.size_bytes),
    'x-drop-rate-content-sha256': m.sha256, 'cache-control': 'no-store' } }, binary: { source: binary(dataBytes) } };
  let next = await execute('Verify Source Bytes Before Creation', source,
    { refs: { 'Sign Bounded Backend Command': request } });
  assert.equal(next.json.ctx.phase, 'LOOKUP'); // Recheck absence after the source fetch.
  const changed = clone(source); changed.binary.source = binary(Buffer.from('corrupt'));
  await assert.rejects(() => execute('Verify Source Bytes Before Creation', changed,
    { refs: { 'Sign Bounded Backend Command': request } }), /source_bytes_invalid/);
  const downloaded = { json: {}, binary: { download: binary(dataBytes) } };
  next = await execute('Verify Fresh Drive Download', downloaded, { refs: { 'Advance Serial Work': item } });
  assert.equal(next.json.ctx.phase, 'LOOKUP'); assert.equal(next.json.ctx.have_download, true);
  downloaded.binary.download = binary(Buffer.from('changed download'));
  await assert.rejects(() => execute('Verify Fresh Drive Download', downloaded,
    { refs: { 'Advance Serial Work': item } }), /download_bytes_mismatch/);
});

test('create-only transport holds empty existing files and rejects unsafe resumable Locations before bytes leave', async () => {
  const item = await reserved();
  await assert.rejects(() => execute('Verify Reserved File Metadata', response(file(item.json.ctx)),
    { refs: { 'Advance Serial Work': item } }), /existing_empty_file_held/);
  let absent = await execute('Verify Reserved File Metadata', { json: { statusCode: 404 } },
    { refs: { 'Advance Serial Work': item } });
  assert.equal(absent.json.ctx.phase, 'OBJECT');
  item.json.ctx.source_ready = true; item.binary = { source: binary(dataBytes) };
  absent = await execute('Verify Reserved File Metadata', { json: { statusCode: 404 } },
    { refs: { 'Advance Serial Work': item } });
  assert.equal(absent.json.ctx.phase, 'CREATE');
  const valid = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=trusted_1';
  for (const location of [valid.replace('https:', 'http:'), valid.replace('www.googleapis.com', 'evil.invalid'),
    valid.replace('www.googleapis.com', 'www.googleapis.com@evil.invalid'), valid + '#fragment',
    valid + '&redirect=https://evil.invalid', valid.replace('/upload/', '/another/')]) {
    await assert.rejects(() => execute('Accept Resumable Creation Session',
      { json: { statusCode: 200, headers: { location } } }, { refs: { 'Advance Serial Work': absent } }),
    /session_location_invalid/);
  }
  const session = await execute('Accept Resumable Creation Session',
    { json: { statusCode: 200, headers: { location: valid } } }, { refs: { 'Advance Serial Work': absent } });
  assert.equal(session.json.ctx.phase, 'UPLOAD'); assert.ok(session.binary.source);
  for (const node of workflow.nodes) {
    assert.notEqual(node.parameters.operation, 'update');
    assert.notEqual(node.parameters.method, 'PATCH');
  }
  assert.equal(nodes['Begin Reserved-ID Resumable Create'].parameters.method, 'POST');
  assert.equal(nodes['Upload Reserved-ID Creation Bytes'].parameters.contentType, 'binaryData');
  for (const name of ['Begin Reserved-ID Resumable Create', 'Upload Reserved-ID Creation Bytes']) {
    assert.equal(nodes[name].parameters.options.redirect.redirect.followRedirects, false);
  }
});

test('a prior complete with a missing DR91 receipt replays completion and the stable receipt key', async () => {
  let item = await pending();
  const a = item.json.ctx.checkpoint.page.archives[0];
  a.copy_status = 'RECORDED_BYTES_VERIFIED'; a.last_recorded_verification_at = new Date().toISOString();
  item = await execute('Advance Serial Work', item);
  assert.equal(item.json.ctx.pending_phase, 'COMPLETE');
  assert.equal(item.json.ctx.checkpoint.page.archive_index, 0);
  item = await destination(item); item = await execute('Advance Serial Work', item);
  const signedRequest = await signed(item);
  item = await execute('Accept Backend Metadata', response({ accepted: true,
    execution_id: item.json.ctx.execution_id, status: 'ARCHIVE_COPY_RECORDED',
    manifest_sha256: a.manifest_sha256, archive_id: a.archive_id, objects_verified: a.objects.length,
    receipt_sha256: 'd'.repeat(64), completed_at: new Date().toISOString(), history_cleanup_authorised: false }),
  { refs: { 'Sign Bounded Backend Command': signedRequest } });
  const prepared = await execute('Prepare Completed Archive Receipt', item);
  assert.equal(prepared.json.idempotency_key, 'drive-archive:reference_history:' + a.manifest_sha256);
  assert.equal(item.json.ctx.counters.objects, 0);
  const accepted = await execute('Accept DR91 Receipt', { json: { recorded: true,
    workflow_key: prepared.json.workflow_key, execution_id: prepared.json.execution_id } },
  { refs: { 'Prepare Completed Archive Receipt': prepared } });
  assert.equal(accepted.json.ctx.checkpoint.page.archive_index, 1);
});

test('a partial completion response cannot reach DR91 success', async () => {
  let item = await pending(); item.json.ctx.checkpoint.page.object_index = 2;
  item = await ready(item, 'COMPLETE'); const request = await signed(item);
  const result = { accepted: true, execution_id: item.json.ctx.execution_id, status: 'ARCHIVE_COPY_RECORDED',
    manifest_sha256: archive().manifest_sha256, archive_id: archive().archive_id, objects_verified: 1,
    receipt_sha256: 'd'.repeat(64), completed_at: new Date().toISOString(), history_cleanup_authorised: false };
  await assert.rejects(() => execute('Accept Backend Metadata', response(result),
    { refs: { 'Sign Bounded Backend Command': request } }), /completion_unverified/);
  item.json.ctx.phase = 'SUCCESS';
  await assert.rejects(() => execute('Prepare Completed Archive Receipt', item), /durable_archive_receipt_required/);
});

test('complete synthetic run orders reservation, create-only media, native download, durable object/manifest and DR91 receipts', async () => {
  const staticState = {}, files = new Map(), reservations = new Map(), verified = new Set(), events = [];
  let item = await initialize(staticState), final, generated = 0;
  for (let iterations = 0; iterations < 200; iterations++) {
    item = await execute('Advance Serial Work', item);
    const routed = item, ctx = item.json.ctx, phase = ctx.phase;
    const refs = { 'Advance Serial Work': routed };
    if (phase === 'DESTINATION') { item = await destination(item); events.push('fresh-destination'); continue; }
    if (['PLAN', 'RESERVE', 'OBJECT', 'VERIFY', 'COMPLETE'].includes(phase)) {
      const request = await signed(item); const command = JSON.parse(request.json.command_body);
      const commandRefs = { 'Sign Bounded Backend Command': request };
      if (phase === 'PLAN') {
        item = await execute('Accept Backend Metadata', response(plan(command.kind === 'REFERENCE_HISTORY' ? [archive()] : [])), { refs: commandRefs });
      } else if (phase === 'RESERVE') {
        const p = ctx.checkpoint.page, m = p.archives[p.archive_index].objects[p.object_index];
        const reservedId = 'CAS_RESERVED_FILE_' + reservations.size;
        reservations.set(m.sha256, reservedId); events.push('reserve:' + m.sha256);
        item = await execute('Accept Backend Metadata', response({ accepted: true, execution_id: ctx.execution_id,
          file_id: reservedId, file_name: m.file_name, app_properties: properties(ctx) }), { refs: commandRefs });
      } else if (phase === 'OBJECT') {
        const bytes = blobs.get(command.object_sha256), m = ctx.checkpoint.page.archives[0].objects[ctx.checkpoint.page.object_index];
        item = await execute('Verify Source Bytes Before Creation', { json: { statusCode: 200,
          headers: { 'content-length': String(bytes.length), 'x-drop-rate-content-sha256': m.sha256, 'cache-control': 'no-store' } },
        binary: { source: binary(bytes, m.mime_type) } }, { refs: commandRefs });
      } else if (phase === 'VERIFY') {
        const bytes = Buffer.from(request.binary.download.data, 'base64');
        assert.equal(digest(bytes), command.object_sha256);
        assert.equal(command.drive_file.id, reservations.get(command.object_sha256));
        verified.add(command.object_sha256); events.push('verify:' + command.object_sha256);
        item = await execute('Accept Durable Object Receipt', response({ accepted: true, execution_id: ctx.execution_id,
          status: 'BYTES_VERIFIED', object_sha256: command.object_sha256, size_bytes: bytes.length,
          file_id: command.drive_file.id, verified_at: new Date().toISOString(), receipt_sha256: 'c'.repeat(64) }), { refs: commandRefs });
      } else {
        assert.equal(verified.size, 2); events.push('complete');
        item = await execute('Accept Backend Metadata', response({ accepted: true, execution_id: ctx.execution_id,
          status: 'ARCHIVE_COPY_RECORDED', archive_id: archive().archive_id, manifest_sha256: archive().manifest_sha256,
          objects_verified: 2, completed_at: new Date().toISOString(), receipt_sha256: 'd'.repeat(64), history_cleanup_authorised: false }), { refs: commandRefs });
      }
    } else if (phase === 'GENERATE_ID') {
      item = await execute('Accept Generated Drive ID', response({ ids: ['GENERATED_UNUSED_ID_' + (++generated)] }), { refs });
    } else if (phase === 'LOOKUP') {
      const record = files.get(ctx.reservation.file_id);
      item = await execute('Verify Reserved File Metadata', record ? response(file(ctx, record.bytes)) : { json: { statusCode: 404 } }, { refs });
    } else if (phase === 'CREATE') {
      assert.ok([...reservations.values()].includes(ctx.reservation.file_id)); events.push('create:' + properties(ctx).drObject);
      assert.equal(files.has(ctx.reservation.file_id), false);
      item = await execute('Accept Resumable Creation Session', { json: { statusCode: 200, headers: { location: 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=syntheticSession' } } }, { refs });
    } else if (phase === 'UPLOAD') {
      const bytes = Buffer.from(item.binary.source.data, 'base64');
      assert.equal(files.has(ctx.reservation.file_id), false);
      files.set(ctx.reservation.file_id, { bytes }); events.push('upload:' + digest(bytes));
      item = await execute('Accept Reserved-ID Content Creation', { json: { statusCode: 201, body: { id: ctx.reservation.file_id } } }, { refs });
    } else if (phase === 'DOWNLOAD') {
      const bytes = files.get(ctx.reservation.file_id).bytes; events.push('download:' + digest(bytes));
      item = await execute('Verify Fresh Drive Download', { json: {}, binary: { download: binary(bytes) } }, { refs });
    } else if (phase === 'SUCCESS') {
      assert.equal(events.at(-1), 'complete');
      const prepared = await execute('Prepare Completed Archive Receipt', item);
      events.push('DR91');
      item = await execute('Accept DR91 Receipt', { json: { recorded: true,
        workflow_key: prepared.json.workflow_key, execution_id: ctx.execution_id } },
      { refs: { 'Prepare Completed Archive Receipt': prepared } });
    } else if (phase === 'FINISH') {
      final = await execute('Save Bounded Resume Checkpoint', item, { state: staticState }); break;
    } else assert.fail('unexpected phase ' + phase);
  }
  assert.equal(final?.json.status, 'COMPLETE');
  assert.equal(final.json.counters.objects, 2); assert.equal(final.json.counters.archives, 1);
  assert.equal(events.filter(event => event === 'DR91').length, 1);
  for (const m of archive().objects) {
    const steps = ['reserve:', 'create:', 'upload:', 'download:', 'verify:'].map(prefix => events.indexOf(prefix + m.sha256));
    assert.ok(steps.every(index => index >= 0)); assert.deepEqual(steps, [...steps].sort((a, b) => a - b));
  }
  assert.ok(!JSON.stringify(staticState).includes(SECRET));
  assert.ok(!JSON.stringify(staticState).includes(dataBytes.toString('base64')));
});
