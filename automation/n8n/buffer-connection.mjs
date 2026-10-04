// Read-only Buffer integration. Never accept a caller-supplied URL or query.
import { pathToFileURL } from 'node:url';

export const BUFFER_ENDPOINT = 'https://api.buffer.com';
export const BUFFER_ORGANIZATION_ID = '6ac1a59ca59739d7c3e08601';
export const BUFFER_CHANNELS = Object.freeze([
  Object.freeze({ id: '6ac1a5deea19ca0bde6c81b7', service: 'instagram', name: '@dropratetcg' }),
  Object.freeze({ id: '6ac1a66eea19ca0bde6c89ac', service: 'tiktok', name: '@dropratetcg' }),
  Object.freeze({ id: '6ac1a694ea19ca0bde6c8ba3', service: 'youtube', name: 'Drop Rate' }),
]);

export const BUFFER_CONNECTION_QUERY = `query DropRateBufferConnection {
  channels(input: {organizationId: "${BUFFER_ORGANIZATION_ID}"}) {
    id service organizationId isDisconnected isLocked isQueuePaused timezone
    allowedActions
    metadata {
      ... on TiktokMetadata { defaultToReminders }
      ... on YoutubeMetadata { defaultToReminders }
    }
  }
}`;

// This pure function is embedded unchanged in the n8n Code node by the builder.
// Never return provider errors, arbitrary response fields, request headers or keys.
export function summarizeBufferConnection(status, body, organizationId, expectedChannels) {
  const base = { publishing_verified: false, automatic_posting_active: false };
  const fail = reason => ({ ...base, ok: false, reason });
  if (!Number.isInteger(status) || status < 200 || status >= 300) {
    return fail(status === 401 || status === 403 ? 'buffer_auth_rejected'
      : status === 429 ? 'buffer_rate_limited' : 'buffer_http_failed');
  }
  if (!body || typeof body !== 'object' || Array.isArray(body)
      || (body.errors !== undefined && (!Array.isArray(body.errors) || body.errors.length))) {
    return fail('buffer_graphql_failed');
  }
  const channels = body.data?.channels;
  if (!Array.isArray(channels)) return fail('buffer_response_invalid');
  const summaries = [];
  for (const expected of expectedChannels) {
    const matches = channels.filter(channel => channel?.id === expected.id);
    if (matches.length !== 1) return fail('buffer_expected_channel_missing_or_duplicate');
    const channel = matches[0];
    if (channel.organizationId !== organizationId || channel.service !== expected.service) {
      return fail('buffer_channel_identity_mismatch');
    }
    if (['isDisconnected', 'isLocked', 'isQueuePaused'].some(field => typeof channel[field] !== 'boolean')
        || !Array.isArray(channel.allowedActions) || typeof channel.timezone !== 'string') {
      return fail('buffer_channel_state_invalid');
    }
    const schedulingAllowed = channel.allowedActions.includes('scheduleUpdates');
    const connected = !channel.isDisconnected && !channel.isLocked;
    const reminders = channel.metadata?.defaultToReminders;
    summaries.push({
      ...expected,
      connected,
      locked: channel.isLocked,
      queue_paused: channel.isQueuePaused,
      scheduling_allowed: schedulingAllowed,
      expected_timezone: channel.timezone === 'Europe/London',
      // Connection/permission is not proof of successful automatic media delivery.
      connection_ready: connected && !channel.isQueuePaused && schedulingAllowed,
      reminder_default: typeof reminders === 'boolean' ? reminders : null,
      media_route: expected.service === 'youtube' ? 'video_required_static_route_unavailable' : 'static_delivery_unverified',
    });
  }
  return {
    ...base,
    ok: true,
    api_access_verified: true,
    organization_id: organizationId,
    all_connections_ready: summaries.every(channel => channel.connection_ready),
    channels: summaries,
  };
}

export async function checkBufferConnection({ apiKey = process.env.BUFFER_API_KEY, fetchImpl = globalThis.fetch } = {}) {
  const failure = reason => ({ ok: false, reason, publishing_verified: false, automatic_posting_active: false });
  if (typeof apiKey !== 'string' || !apiKey || apiKey.trim() !== apiKey || /\s/.test(apiKey)) {
    return failure('buffer_key_missing_or_invalid');
  }
  try {
    const response = await fetchImpl(BUFFER_ENDPOINT, {
      method: 'POST',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ query: BUFFER_CONNECTION_QUERY }),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      return summarizeBufferConnection(response.status, null, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS);
    }
    return summarizeBufferConnection(response.status, await response.json(), BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS);
  } catch {
    return failure('buffer_transport_or_parse_failed');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await checkBufferConnection();
  console.log(`DROP_RATE_BUFFER_CONNECTION ${JSON.stringify(result)}`);
  process.exitCode = result.ok && result.all_connections_ready ? 0 : 1;
}
