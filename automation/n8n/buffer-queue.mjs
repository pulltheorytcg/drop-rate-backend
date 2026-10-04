// Read-only, advisory queue audit. Never use this as a publication lock.
import { pathToFileURL } from 'node:url';
import {
  BUFFER_ENDPOINT, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS,
  summarizeBufferConnection,
} from './buffer-connection.mjs';

export const BUFFER_QUEUE_PAGE_SIZE = 100;
export const BUFFER_QUEUE_MAX_PAGES = 10;
export const BUFFER_QUEUE_QUERY = `query DropRateBufferQueue($after: String) {
  channels(input: {organizationId: "${BUFFER_ORGANIZATION_ID}"}) {
    id service organizationId isDisconnected isLocked isQueuePaused timezone
    allowedActions
    metadata {
      ... on TiktokMetadata { defaultToReminders }
      ... on YoutubeMetadata { defaultToReminders }
    }
  }
  posts(first: ${BUFFER_QUEUE_PAGE_SIZE}, after: $after, input: {
    organizationId: "${BUFFER_ORGANIZATION_ID}"
    filter: {
      channelIds: ${JSON.stringify(BUFFER_CHANNELS.map(channel => channel.id))}
      status: [scheduled, sending, error, needs_approval, draft]
    }
    sort: [{field: dueAt, direction: asc}, {field: createdAt, direction: asc}]
  }) {
    edges { node {
      id status dueAt schedulingType
      channel { id service organizationId }
    } }
    pageInfo { hasNextPage endCursor }
  }
}`;

// These pure functions are embedded unchanged in the inactive n8n workflow.
// No captions, media URLs, provider error bodies, credentials or cursor output.
export function queueFailure(reason) {
  return {
    ok: false, reason, queue_complete: false, queue_empty: null,
    scheduled_posts: null, publishing_verified: false, automatic_posting_active: false,
  };
}

export function validateQueuePage(status, body, organizationId, expectedChannels, pageSize) {
  const connection = summarizeBufferConnection(status, body, organizationId, expectedChannels);
  if (!connection.ok) return queueFailure(connection.reason);
  const result = body.data.posts;
  const pageInfo = result?.pageInfo;
  if (!Array.isArray(result?.edges) || result.edges.length > pageSize
      || typeof pageInfo?.hasNextPage !== 'boolean'
      || !(pageInfo.endCursor === null || (typeof pageInfo.endCursor === 'string'
        && pageInfo.endCursor.length > 0 && pageInfo.endCursor.length <= 2048))
      || (pageInfo.hasNextPage && (!pageInfo.endCursor || !result.edges.length))) {
    return queueFailure('buffer_queue_page_invalid');
  }
  const ids = new Set();
  const posts = [];
  for (const edge of result.edges) {
    const post = edge?.node;
    const expected = expectedChannels.find(channel => channel.id === post?.channel?.id);
    if (!expected || post.channel.organizationId !== organizationId
        || post.channel.service !== expected.service) {
      return queueFailure('buffer_queue_channel_mismatch');
    }
    if (typeof post.id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(post.id)
        || !['scheduled', 'sending', 'error', 'needs_approval', 'draft'].includes(post.status)
        || ![null, 'automatic', 'notification'].includes(post.schedulingType)) {
      return queueFailure('buffer_queue_post_invalid');
    }
    if (ids.has(post.id)) return queueFailure('buffer_queue_duplicate_post');
    ids.add(post.id);
    const dueAt = post.dueAt;
    if (dueAt !== null && (typeof dueAt !== 'string'
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(dueAt)
        || !Number.isFinite(Date.parse(dueAt))
        || new Date(`${dueAt.slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10) !== dueAt.slice(0, 10))) {
      return queueFailure('buffer_queue_date_invalid');
    }
    if (post.status === 'scheduled' && dueAt === null) {
      return queueFailure('buffer_queue_scheduled_date_missing');
    }
    posts.push({
      id: post.id, channel_id: expected.id, status: post.status,
      due_at: dueAt === null ? null : new Date(dueAt).toISOString(),
      scheduling_type: post.schedulingType,
    });
  }
  return { ok: true, connection, posts, has_next_page: pageInfo.hasNextPage, cursor: pageInfo.endCursor };
}

export function summarizeQueue(connection, posts, pagesRead, startedAt, finishedAt) {
  const counts = rows => Object.fromEntries(
    ['scheduled', 'sending', 'error', 'needs_approval', 'draft']
      .map(status => [status, rows.filter(post => post.status === status).length]),
  );
  const totals = counts(posts);
  const scheduled = posts.filter(post => post.status === 'scheduled');
  return {
    ...connection,
    queue_complete: true,
    // Drafts/failed posts are reported separately from the publishing queue.
    queue_empty: totals.scheduled + totals.sending === 0,
    scheduled_posts: totals.scheduled,
    counts: totals,
    pages_read: pagesRead,
    observed_from: startedAt,
    observed_to: finishedAt,
    scope: 'expected_three_channels_non_sent_posts',
    snapshot_isolation: false,
    scheduling_authorized: false,
    attention: {
      overdue_scheduled: scheduled.filter(post => Date.parse(post.due_at) < Date.parse(finishedAt)).length,
      reminder_scheduled: scheduled.filter(post => post.scheduling_type === 'notification').length,
      unknown_delivery_scheduled: scheduled.filter(post => post.scheduling_type === null).length,
      failed_posts: totals.error,
    },
    channels: connection.channels.map(channel => ({
      ...channel, counts: counts(posts.filter(post => post.channel_id === channel.id)),
    })),
    posts: [...posts].sort((a, b) => (a.due_at ?? 'z').localeCompare(b.due_at ?? 'z') || a.id.localeCompare(b.id)),
  };
}

// n8n's bounded single-request check explicitly refuses a truncated queue.
// Use the CLI below for up to ten pages; neither route grants permission to post.
export function summarizeQueueFirstPage(status, body, organizationId, expectedChannels, pageSize, observedAt) {
  const page = validateQueuePage(status, body, organizationId, expectedChannels, pageSize);
  if (!page.ok) return page;
  if (page.has_next_page) return queueFailure('buffer_queue_pagination_required');
  return summarizeQueue(page.connection, page.posts, 1, observedAt, observedAt);
}

export async function checkBufferQueue({ apiKey = process.env.BUFFER_API_KEY, fetchImpl = globalThis.fetch } = {}) {
  if (typeof apiKey !== 'string' || !apiKey || /\s/.test(apiKey)) {
    return queueFailure('buffer_key_missing_or_invalid');
  }
  const startedAt = new Date().toISOString();
  const deadline = AbortSignal.timeout(45000);
  const cursors = new Set();
  const ids = new Set();
  const posts = [];
  let cursor = null;
  let initialConnection;
  try {
    for (let pageNumber = 1; pageNumber <= BUFFER_QUEUE_MAX_PAGES; pageNumber++) {
      deadline.throwIfAborted();
      const response = await fetchImpl(BUFFER_ENDPOINT, {
        method: 'POST', redirect: 'error',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ query: BUFFER_QUEUE_QUERY, variables: { after: cursor } }),
        signal: AbortSignal.any([deadline, AbortSignal.timeout(15000)]),
      });
      const body = response.ok ? await response.json() : null;
      const page = validateQueuePage(response.status, body, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS, BUFFER_QUEUE_PAGE_SIZE);
      if (!page.ok) return page;
      // Refuse counts if channel state changed during this multi-request observation.
      initialConnection ??= page.connection;
      if (JSON.stringify(initialConnection) !== JSON.stringify(page.connection)) {
        return queueFailure('buffer_queue_connection_changed');
      }
      for (const post of page.posts) {
        if (ids.has(post.id)) return queueFailure('buffer_queue_duplicate_post');
        ids.add(post.id);
        posts.push(post);
      }
      if (!page.has_next_page) {
        return summarizeQueue(page.connection, posts, pageNumber, startedAt, new Date().toISOString());
      }
      if (cursors.has(page.cursor)) return queueFailure('buffer_queue_cursor_repeated');
      cursors.add(page.cursor);
      cursor = page.cursor;
    }
    return queueFailure('buffer_queue_page_limit');
  } catch {
    return queueFailure('buffer_transport_or_parse_failed');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await checkBufferQueue();
  console.log(`DROP_RATE_BUFFER_QUEUE ${JSON.stringify(result)}`);
  process.exitCode = result.ok ? 0 : 1;
}
