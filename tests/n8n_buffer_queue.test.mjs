import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  BUFFER_ENDPOINT, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS,
} from '../automation/n8n/buffer-connection.mjs';
import {
  BUFFER_QUEUE_QUERY, BUFFER_QUEUE_PAGE_SIZE, BUFFER_QUEUE_MAX_PAGES,
  checkBufferQueue, summarizeQueueFirstPage,
} from '../automation/n8n/buffer-queue.mjs';

const apiKey = 'test-only-buffer-secret';
const fixture = (posts = [], hasNextPage = false, endCursor = null) => ({ data: {
  channels: BUFFER_CHANNELS.map(channel => ({
    ...channel, organizationId: BUFFER_ORGANIZATION_ID,
    isDisconnected: false, isLocked: false, isQueuePaused: false,
    timezone: 'Europe/London', allowedActions: ['scheduleUpdates'],
    metadata: { defaultToReminders: false },
  })),
  posts: { edges: posts.map(node => ({ node })), pageInfo: { hasNextPage, endCursor } },
} });
const post = (id, overrides = {}) => ({
  id, status: 'scheduled', dueAt: '2030-07-01T12:00:00+01:00', schedulingType: 'automatic',
  channel: { ...BUFFER_CHANNELS[0], organizationId: BUFFER_ORGANIZATION_ID }, ...overrides,
});
const audit = async (...bodies) => {
  let calls = 0;
  const result = await checkBufferQueue({ apiKey, fetchImpl: async () => {
    assert.ok(calls < bodies.length, 'no unexpected retry');
    return { ok: true, status: 200, json: async () => bodies[calls++] };
  } });
  return { result, calls };
};
const failed = (result, reason) => {
  assert.equal(result.ok, false);
  assert.equal(result.reason, reason);
  assert.equal(result.queue_complete, false);
  assert.equal(result.queue_empty, null);
  assert.equal(result.scheduled_posts, null);
  assert.equal(result.publishing_verified, false);
  assert.equal(result.posts, undefined);
};

test('verified empty queues have explicit zero counts on all three expected channels', async () => {
  const { result, calls } = await audit(fixture());
  assert.equal(calls, 1);
  assert.equal(result.ok, true);
  assert.equal(result.queue_complete, true);
  assert.equal(result.queue_empty, true);
  assert.equal(result.scheduled_posts, 0);
  assert.equal(result.channels.length, 3);
  assert.ok(result.channels.every(channel => channel.counts.scheduled === 0));
  assert.equal(result.snapshot_isolation, false);
  assert.equal(result.scheduling_authorized, false);
  assert.equal(result.publishing_verified, false);
  assert.equal(result.automatic_posting_active, false);
});

test('real posts, not configured posting slots, determine queue counts', async () => {
  const body = fixture([
    post('scheduled-1'), post('sending-1', { status: 'sending' }),
    post('error-1', { status: 'error', dueAt: null }),
    post('approval-1', { status: 'needs_approval', dueAt: null }),
    post('draft-1', { status: 'draft', dueAt: null, schedulingType: null }),
  ]);
  body.data.channels[0].postingSchedule = [{ time: '09:00' }];
  const { result } = await audit(body);
  assert.deepEqual(result.counts, { scheduled: 1, sending: 1, error: 1, needs_approval: 1, draft: 1 });
  assert.equal(result.queue_empty, false);
  assert.equal(result.posts[0].due_at, '2030-07-01T11:00:00.000Z');
  assert.equal(result.attention.failed_posts, 1);
});

test('drafts do not masquerade as scheduled posts, but remain visible', async () => {
  const { result } = await audit(fixture([post('draft-1', { status: 'draft', dueAt: null })]));
  assert.equal(result.queue_empty, true);
  assert.equal(result.counts.draft, 1);
  assert.equal(result.scheduled_posts, 0);
});

test('reminders, unknown delivery and overdue posts get separate attention counts', async () => {
  const { result } = await audit(fixture([
    post('reminder-1', { schedulingType: 'notification' }),
    post('unknown-1', { schedulingType: null }),
    post('past-1', { dueAt: '2020-01-01T00:00:00Z' }),
  ]));
  assert.deepEqual(result.attention, {
    overdue_scheduled: 1, reminder_scheduled: 1, unknown_delivery_scheduled: 1, failed_posts: 0,
  });
  assert.equal(result.publishing_verified, false);
});

test('pagination follows opaque cursors using variables at the fixed endpoint', async () => {
  let calls = 0;
  const cursor = 'opaque/cursor+with="quotes"';
  const bodies = [fixture([post('a')], true, cursor), fixture([post('b')])];
  const result = await checkBufferQueue({ apiKey, fetchImpl: async (url, request) => {
    assert.equal(url, BUFFER_ENDPOINT);
    assert.equal(request.redirect, 'error');
    assert.equal(request.headers.Authorization, `Bearer ${apiKey}`);
    const payload = JSON.parse(request.body);
    assert.equal(payload.query, BUFFER_QUEUE_QUERY);
    assert.deepEqual(payload.variables, { after: calls ? cursor : null });
    assert.ok(request.signal instanceof AbortSignal);
    assert.equal(/\bmutation\b/.test(payload.query), false);
    assert.equal(/\btext\b|\bauthor\b|\bassets\b/.test(payload.query), false);
    return { ok: true, status: 200, json: async () => bodies[calls++] };
  } });
  assert.equal(calls, 2);
  assert.equal(result.pages_read, 2);
  assert.equal(result.scheduled_posts, 2);
  assert.equal(JSON.stringify(result).includes(cursor), false);
});

test('missing credentials never contact Buffer', async () => {
  for (const key of ['', ' key', 'key\nvalue', null]) {
    failed(await checkBufferQueue({ apiKey: key, fetchImpl: () => assert.fail('unexpected request') }),
      'buffer_key_missing_or_invalid');
  }
});

test('HTTP failures never read provider bodies or retry', async () => {
  for (const [status, reason] of [[401, 'buffer_auth_rejected'], [403, 'buffer_auth_rejected'],
    [429, 'buffer_rate_limited'], [503, 'buffer_http_failed']]) {
    let calls = 0;
    const result = await checkBufferQueue({ apiKey, fetchImpl: async () => {
      calls++;
      return { ok: false, status, json: () => assert.fail('must not read error body') };
    } });
    failed(result, reason);
    assert.equal(calls, 1);
  }
});

test('transport, abort and JSON errors produce sanitized incomplete results', async () => {
  for (const fetchImpl of [
    async () => { throw new Error(apiKey); },
    async () => { throw new DOMException(apiKey, 'AbortError'); },
    async () => ({ ok: true, status: 200, json: async () => { throw new Error(apiKey); } }),
  ]) {
    const result = await checkBufferQueue({ apiKey, fetchImpl });
    failed(result, 'buffer_transport_or_parse_failed');
    assert.equal(JSON.stringify(result).includes(apiKey), false);
  }
});

test('GraphQL partial errors and missing pages never mean an empty queue', async () => {
  const partial = fixture(); partial.errors = [{ message: apiKey }];
  for (const body of [partial, null, {}, { data: { channels: [] } }]) {
    const { result } = await audit(body);
    assert.equal(result.ok, false);
    assert.equal(result.queue_empty, null);
    assert.equal(JSON.stringify(result).includes(apiKey), false);
  }
  const missing = fixture(); delete missing.data.posts;
  failed((await audit(missing)).result, 'buffer_queue_page_invalid');
});

test('malformed pagination, empty continuation pages and oversized pages fail closed', async () => {
  for (const info of [{}, { hasNextPage: 'false', endCursor: null },
    { hasNextPage: true, endCursor: null }, { hasNextPage: true, endCursor: '' },
    { hasNextPage: false, endCursor: 'x'.repeat(2049) }]) {
    const body = fixture(); body.data.posts.pageInfo = info;
    failed((await audit(body)).result, 'buffer_queue_page_invalid');
  }
  failed((await audit(fixture([], true, 'cursor'))).result, 'buffer_queue_page_invalid');
  failed((await audit(fixture(Array.from({ length: BUFFER_QUEUE_PAGE_SIZE + 1 }, (_, i) => post(`p${i}`))))).result,
    'buffer_queue_page_invalid');
});

test('wrong post organization, channel or network cannot leak into a report', async () => {
  for (const channel of [
    { ...BUFFER_CHANNELS[0], organizationId: 'wrong' },
    { ...BUFFER_CHANNELS[0], organizationId: BUFFER_ORGANIZATION_ID, service: 'facebook' },
    { id: 'other-channel', organizationId: BUFFER_ORGANIZATION_ID },
  ]) failed((await audit(fixture([post('a', { channel })]))).result, 'buffer_queue_channel_mismatch');
});

test('invalid post status, IDs, dates and delivery modes cannot appear scheduled', async () => {
  for (const overrides of [{ id: '' }, { status: 'sent' }, { status: 'new-status' },
    { schedulingType: 'new-mode' }, { schedulingType: undefined }]) {
    failed((await audit(fixture([post('a', overrides)]))).result, 'buffer_queue_post_invalid');
  }
  for (const dueAt of ['tomorrow', '2030-01-01', undefined, '2030-13-01T00:00:00Z', '2030-02-30T00:00:00Z']) {
    failed((await audit(fixture([post('a', { dueAt })]))).result, 'buffer_queue_date_invalid');
  }
  failed((await audit(fixture([post('a', { dueAt: null })]))).result, 'buffer_queue_scheduled_date_missing');
});

test('duplicate posts and repeated cursors discard partial counts', async () => {
  failed((await audit(fixture([post('a'), post('a')]))).result, 'buffer_queue_duplicate_post');
  failed((await audit(fixture([post('a')], true, 'x'), fixture([post('a')]))).result, 'buffer_queue_duplicate_post');
  failed((await audit(fixture([post('a')], true, 'x'), fixture([post('b')], true, 'x'))).result,
    'buffer_queue_cursor_repeated');
});

test('page budget and a failing later page never report partial totals as complete', async () => {
  const pages = Array.from({ length: BUFFER_QUEUE_MAX_PAGES }, (_, i) => fixture([post(`p${i}`)], true, `c${i}`));
  const limited = await audit(...pages);
  failed(limited.result, 'buffer_queue_page_limit');
  assert.equal(limited.calls, BUFFER_QUEUE_MAX_PAGES);
  const bad = fixture(); bad.errors = [{ message: apiKey }];
  failed((await audit(fixture([post('a')], true, 'x'), bad)).result, 'buffer_graphql_failed');
});

test('disconnected and paused channels remain visible without claiming readiness', async () => {
  const body = fixture(); body.data.channels[0].isQueuePaused = true;
  const { result } = await audit(body);
  assert.equal(result.ok, true);
  assert.equal(result.queue_complete, true);
  assert.equal(result.all_connections_ready, false);
  assert.equal(result.channels[0].connection_ready, false);
  failed((await audit(fixture([post('a')], true, 'x'), body)).result, 'buffer_queue_connection_changed');
});

test('allowlisted report excludes provider prose, assets and secrets', async () => {
  const body = fixture([post('a', { text: apiKey, assets: [{ source: apiKey }], error: apiKey })]);
  body.extensions = { token: apiKey };
  const { result } = await audit(body);
  assert.equal(result.ok, true);
  assert.equal(JSON.stringify(result).includes(apiKey), false);
});

test('actual n8n validator matches the shared first-page function and rejects truncation', async () => {
  const workflow = JSON.parse(await readFile(new URL('../automation/n8n/workflows/dr-32-buffer-queue-check.json', import.meta.url)));
  assert.equal(workflow.active, false);
  assert.equal(workflow.nodes.some(node => /webhook|scheduleTrigger|executeCommand/.test(node.type)), false);
  assert.equal(workflow.settings.saveDataErrorExecution, 'none');
  assert.equal(workflow.settings.saveDataSuccessExecution, 'none');
  assert.equal(workflow.settings.saveManualExecutions, false);
  const request = workflow.nodes.find(node => node.type === 'n8n-nodes-base.httpRequest').parameters;
  assert.equal(request.url, BUFFER_ENDPOINT);
  assert.equal(request.options.redirect.redirect.followRedirects, false);
  assert.deepEqual(JSON.parse(request.body), { query: BUFFER_QUEUE_QUERY, variables: { after: null } });
  const execute = new Function('$input', 'Date', workflow.nodes.find(node => node.type === 'n8n-nodes-base.code').parameters.jsCode);
  const observedAt = '2026-10-04T08:00:00.000Z';
  class FixedDate extends Date { constructor(value = observedAt) { super(value); } }
  for (const [statusCode, body] of [[200, fixture()], [200, fixture([post('a')])],
    [200, fixture([post('a')], true, 'x')], [401, {}], [200, {}]]) {
    const result = execute({ first: () => ({ json: { statusCode, body } }) }, FixedDate);
    assert.deepEqual(result, [{ json: summarizeQueueFirstPage(statusCode, body,
      BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS, BUFFER_QUEUE_PAGE_SIZE, observedAt) }]);
  }
});
