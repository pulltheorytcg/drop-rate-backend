# Buffer connection handoff — 4 October 2026

## Follow-up: live browser queue check and prepared queue audit

On 4 October 2026, after the founder signed in during the continuation chat,
the authenticated Buffer UI was read without modifying account or content state:

| Surface | Observed result |
| --- | --- |
| Home, `https://publish.buffer.com/home` | 0 posts scheduled; no upcoming posts |
| Publish sidebar, `https://publish.buffer.com/schedule` | Instagram, TikTok and YouTube each showed 0 scheduled posts |
| Channels, `https://publish.buffer.com/settings/channels` | 3/3 connected on Free: Instagram Professional `dropratetcg`, TikTok `dropratetcg`, YouTube `Drop Rate` |
| Publish sidebar | Facebook and Twitter/X offered as unconnected channels |
| Publish queue | Empty suggested slots labelled Europe/London; no scheduled content |

This is fresh browser evidence. No live API post query was executed in this chat,
and no draft/failed/sent counts were inferred from the empty scheduled queue.
Buffer OAuth tools are still not exposed here. Browser sign-in is not an MCP
connection. Do not remove the existing Railway API key.

Prepared continuation component:

- `automation/n8n/buffer-queue.mjs`: fixed organization/channel scope; read-only
  channel and non-sent post query; bounded cursor pagination; exact identity and
  shape validation; sanitized errors; no captions or media retrieval; no retries.
- `DR32BufferQueueCheckV1`: separate inactive n8n export generated from the same
  validators. One page only; a continuation cursor yields an explicit incomplete
  result, never a false empty queue. The paginated CLI supports ten pages.
- Queue observations distinguish drafts, approvals, failures, sending and scheduled
  posts, plus overdue/notification/unknown delivery attention counts. Every failure
  returns null queue counts, and all paths leave publishing authority false.
- `Dockerfile.n8n` packages the CLI; the existing additive provisioner would import
  the new inactive workflow on a future deployment. Startup logic is unchanged.
- The existing connection parity test now normalizes CRLF/LF when comparing embedded
  JavaScript; this fixes Windows checkouts without changing runtime behavior.

Validation: 26 Node tests passed across connection and queue suites, including
the generated n8n Code node. Covers pagination, repeated cursor/post, page limit,
later-page failure, wrong identity, malformed dates/status, partial GraphQL errors,
401/403/429/503, transport/parse failure, secret-safe output and inactive workflow.
Fifteen targeted pytest tests passed across Buffer, provisioning, workflow registry
and orphan registry contracts. JavaScript syntax and `git diff --check` passed.
The new query/export has not been exercised against live Buffer or production n8n.

Next release gates, in sequence:

1. Run the read-only queue query using the existing service credential and compare
   the result with the browser. Do not redeploy merely to obtain a read-only result
   without a release decision. Keep raw keys and provider errors out of logs.
2. Import/execute the inactive n8n companion under the existing private setup and
   confirm incomplete/error routing. The generic workflow family remains DESIGNED.
3. Continue the durable backend publication ledger and approval flow before any
   Buffer write adapter. Queue reads have no atomic snapshot or deduplication lock.
4. Implement evidence storage and licensed static rendering from the editorial
   plan, then test approved per-channel drafts and delivery reconciliation.
5. Resolve Facebook/X capacity and YouTube static delivery explicitly; preserve
   static-first/no-music direction and do not substitute Shorts or buy upgrades.

## Verified live

The founder created a Buffer personal key, added it as `BUFFER_API_KEY` on
Railway `drop-rate-n8n-e840`, and deployed. Deployment
`00db0ac9-cfac-4270-99e4-22f19c29efb3` succeeded.

The Railway connector deliberately withholds environment-variable values. The
key was tested inside the existing Railway service using a bounded, read-only
pre-deploy request to `https://api.buffer.com`. The key was never printed or copied
into the repository. No authentication controls or public networking were changed.

Redeploy `e616be18-63d6-4791-8895-4f2505bce214` reused the earlier deployment and
did not execute the newly configured diagnostic. It is not API proof. A fresh
deployment of the same main commit, `21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1`,
did execute it: `c45658f8-f684-4c49-958c-1bc80b918543` logged
`DROP_RATE_BUFFER_CHECK` with `ok:true` and finished SUCCESS. Temporary pre-deploy
commands were then removed from service configuration.

Buffer organisation: `6ac1a59ca59739d7c3e08601` (My organization).

| Channel | Buffer ID | Verified connection state |
| --- | --- | --- |
| Instagram @dropratetcg | `6ac1a5deea19ca0bde6c81b7` | Connected, unlocked, queue unpaused, scheduleUpdates allowed |
| TikTok @dropratetcg | `6ac1a66eea19ca0bde6c89ac` | Connected, unlocked, queue unpaused, scheduleUpdates allowed |
| YouTube Drop Rate | `6ac1a694ea19ca0bde6c8ba3` | Connected, unlocked, queue unpaused, scheduleUpdates allowed |

All three use `Europe/London`. TikTok and YouTube report
`defaultToReminders:false`. This is configuration evidence, not proof of a real
automatically delivered media post. Existing posting schedules were read, not
changed. The earlier UI check found empty queues; this probe did not query posts.

## Direct ChatGPT management

The founder supplied Buffer's official guide:
https://developers.buffer.com/guides/integrations/chatgpt.html

Buffer supports OAuth at `https://mcp.buffer.com/mcp`, without a personal API key
for the ChatGPT connection. Direct chat management and unattended n8n are separate
clients. Retain the Railway key for n8n.

Current OpenAI instructions place Developer mode in Settings → Security and login,
then the add button at https://chatgpt.com/plugins. Buffer's guide uses the older
Apps/Connectors → Advanced settings wording. Availability depends on account and
workspace policy. Set the connection name to Buffer, use the MCP URL above and
select OAuth, then complete Buffer's authorization screen. Install/select the
resulting personal plugin in the conversation. No Buffer tool is currently exposed
to this session; plugin search returned no catalogue result. OAuth connection is
not yet verified. Do not claim persistent direct management until tools are
available and a read-only channel/queue query succeeds.

OpenAI source: https://developers.openai.com/plugins/deploy/connect-chatgpt

## Repository component

- `automation/n8n/buffer-connection.mjs`: fixed-endpoint read-only check; strict
  organisation/channel identity, connection, lock, pause and permission checks;
  15-second timeout; no redirects, provider error echo or automatic retries.
- `automation/n8n/build-buffer-connection-workflow.mjs`: regenerates the n8n
  export from the same query and pure response validator.
- `automation/n8n/workflows/dr-32-buffer-connection-check.json`: inactive
  sub-workflow only. No scheduler, publishing mutation, public ingress or secret
  value. Saved execution data is disabled. HTTP transport errors can still fail
  an execution; callers must handle failure as unverified, not success.
- `Dockerfile.n8n` packages the diagnostic without changing startup behavior.
- Tests cover invalid credentials, provider/network failure, GraphQL partial
  errors, wrong/missing/duplicate identity, denied scheduling, paused/disconnected
  channels, secret-safe output and parity with the actual n8n Code node.

This component is prepared in a separate branch from editorial PR #512. Neither
its tests nor the earlier live probe prove that this exact n8n export has been
imported or executed in production. No workflow was activated.

## Remaining work toward the founder's goal

The goal remains three distinct stories daily, adapted across Instagram, Facebook,
YouTube, TikTok and X, with broad cards/comics/manga/anime/screen coverage and
website conversion measurement. Free Buffer currently holds IG/TikTok/YouTube.
Facebook/X are not connected there. No upgrade has been authorized.

PR #512 implements stateless editorial preparation only and remains unmerged.
Source fetching, evidence storage, rendering, durable publication idempotency,
Buffer draft/schedule adapters, delivery reconciliation, recurring scheduling and
performance learning are still required. A verified API key does not implement
these pieces. Direct ChatGPT OAuth also does not itself create a background n8n
research-and-publishing machine.

Static-first and no music remain the user's direction. Buffer's YouTube route
requires video; there is no verified Buffer route for YouTube Community images.
Do not silently substitute Shorts. TikTok's actual image/no-music delivery route
also needs a real test before claiming zero-touch publication.

Provider references:
- https://developers.buffer.com/guides/getting-started.html
- https://developers.buffer.com/reference.html
- https://developers.buffer.com/guides/integrations/mcp.html
- https://developers.buffer.com/guides/integrations/n8n.html
