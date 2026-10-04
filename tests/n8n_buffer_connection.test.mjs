import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  BUFFER_ENDPOINT, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS,
  BUFFER_CONNECTION_QUERY, checkBufferConnection, summarizeBufferConnection,
} from '../automation/n8n/buffer-connection.mjs';

const fixture = () => ({ data: { channels: BUFFER_CHANNELS.map(channel => ({
  ...channel, organizationId: BUFFER_ORGANIZATION_ID,
  isDisconnected: false, isLocked: false, isQueuePaused: false,
  timezone: 'Europe/London', allowedActions: ['scheduleUpdates'],
  metadata: { defaultToReminders: false },
})) } });
const summarize = (status, body) => summarizeBufferConnection(status, body, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS);

test('authenticated channels never imply verified publishing or an active machine', () => {
  const result = summarize(200, fixture());
  assert.equal(result.ok, true);
  assert.equal(result.all_connections_ready, true);
  assert.equal(result.publishing_verified, false);
  assert.equal(result.automatic_posting_active, false);
  assert.equal(result.channels[2].media_route, 'video_required_static_route_unavailable');
});

test('wrong organization, wrong network, duplicate and missing identities fail closed', () => {
  for (const change of [
    body => { body.data.channels[0].organizationId = 'another-org'; },
    body => { body.data.channels[0].service = 'facebook'; },
    body => { body.data.channels.push(body.data.channels[0]); },
    body => { body.data.channels.pop(); },
  ]) {
    const body = fixture(); change(body);
    assert.equal(summarize(200, body).ok, false);
  }
});

test('disconnected, locked, paused and permissionless channels cannot appear ready', () => {
  for (const change of [
    channel => { channel.isDisconnected = true; },
    channel => { channel.isLocked = true; },
    channel => { channel.isQueuePaused = true; },
    channel => { channel.allowedActions = []; },
  ]) {
    const body = fixture(); change(body.data.channels[0]);
    const result = summarize(200, body);
    assert.equal(result.ok, true);
    assert.equal(result.all_connections_ready, false);
    assert.equal(result.channels[0].connection_ready, false);
  }
});

test('unknown states, malformed responses and partial GraphQL errors never pass', () => {
  for (const body of [null, [], {}, { data: { channels: {} } },
    { ...fixture(), errors: [{ message: 'untrusted sensitive provider text' }] },
    { ...fixture(), errors: 'malformed' },
  ]) assert.equal(summarize(200, body).ok, false);
  const body = fixture(); delete body.data.channels[0].isLocked;
  assert.equal(summarize(200, body).ok, false);
});

test('HTTP failures are typed without echoing provider bodies', () => {
  for (const [status, reason] of [[401, 'buffer_auth_rejected'], [403, 'buffer_auth_rejected'],
    [429, 'buffer_rate_limited'], [503, 'buffer_http_failed']]) {
    assert.equal(summarize(status, { error: 'sensitive' }).reason, reason);
    assert.equal(JSON.stringify(summarize(status, { error: 'sensitive' })).includes('sensitive'), false);
  }
});

test('requests use only the fixed Buffer endpoint and query, without redirects or writes', async () => {
  const apiKey = 'test-only-buffer-value'; let calls = 0;
  const result = await checkBufferConnection({ apiKey, fetchImpl: async (url, request) => {
    calls++;
    assert.equal(url, BUFFER_ENDPOINT);
    assert.equal(request.redirect, 'error');
    assert.equal(request.headers.Authorization, `Bearer ${apiKey}`);
    assert.equal(JSON.parse(request.body).query, BUFFER_CONNECTION_QUERY);
    assert.ok(request.signal instanceof AbortSignal);
    assert.equal(/\bmutation\b/.test(request.body), false);
    return { ok: true, status: 200, json: async () => fixture() };
  } });
  assert.equal(calls, 1);
  assert.equal(result.ok, true);
  assert.equal(JSON.stringify(result).includes(apiKey), false);
});

test('missing/malformed keys cause no network call', async () => {
  for (const apiKey of ['', ' key', 'key ', 'key\nvalue', null]) {
    const result = await checkBufferConnection({ apiKey, fetchImpl: async () => assert.fail('unexpected request') });
    assert.equal(result.reason, 'buffer_key_missing_or_invalid');
  }
});

test('transport, rate limit and parse failures are sanitized and never blindly retried', async () => {
  for (const fetchImpl of [
    async () => { throw new Error('request contained test-only-buffer-value'); },
    async () => ({ ok: true, status: 200, json: async () => { throw new Error('sensitive body'); } }),
    async () => ({ ok: false, status: 429, json: async () => assert.fail('must not read error body') }),
  ]) {
    let calls = 0;
    const result = await checkBufferConnection({ apiKey: 'test-only-buffer-value', fetchImpl: (...args) => { calls++; return fetchImpl(...args); } });
    assert.equal(calls, 1);
    assert.equal(result.ok, false);
    assert.equal(/sensitive|test-only-buffer-value/.test(JSON.stringify(result)), false);
  }
});

test('n8n invokes the same validator, does not accept arbitrary requests, and stays inactive', async () => {
  const workflow = JSON.parse(await readFile(new URL('../automation/n8n/workflows/dr-32-buffer-connection-check.json', import.meta.url)));
  assert.equal(workflow.active, false);
  assert.equal(workflow.nodes.some(node => /webhook|scheduleTrigger/.test(node.type)), false);
  assert.equal(workflow.settings.saveDataErrorExecution, 'none');
  assert.equal(workflow.settings.saveDataSuccessExecution, 'none');
  const request = workflow.nodes.find(node => node.type === 'n8n-nodes-base.httpRequest').parameters;
  assert.equal(request.url, BUFFER_ENDPOINT);
  assert.equal(request.contentType, 'json', 'raw mode leaves the n8n 2.32.6 response body as a stream');
  assert.equal(request.specifyBody, 'json');
  assert.equal(request.body, undefined);
  assert.equal(request.rawContentType, undefined);
  assert.deepEqual(JSON.parse(request.jsonBody), { query: BUFFER_CONNECTION_QUERY });
  assert.equal(request.options.response.response.responseFormat, 'json');
  assert.equal(request.options.response.response.fullResponse, true);
  assert.equal(request.options.redirect.redirect.followRedirects, false);
  const code = workflow.nodes.find(node => node.type === 'n8n-nodes-base.code').parameters.jsCode;
  assert.ok(code.replace(/\r\n/g, '\n').startsWith(summarizeBufferConnection.toString().replace(/\r\n/g, '\n')));
  const execute = new Function('$input', code);
  for (const [statusCode, body] of [[200, fixture()], [401, {}], [200, {}]]) {
    assert.deepEqual(execute({ first: () => ({ json: { statusCode, body } }) }), [{ json: summarize(statusCode, body) }]);
  }
});
