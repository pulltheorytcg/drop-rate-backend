# Buffer connection handoff — 4 October 2026

## Current founder target and end-to-end acceptance — 4 October 2026

This section supersedes the earlier five-platform target and static-only YouTube
direction below. The founder confirmed the immediate operating target as research
of content and creators, topic selection, original post creation, three posts per
day on each of the three connected platforms, then performance analysis to grow
traffic, conversions and followers. Interpret the cadence as three distinct daily
stories adapted to Instagram, TikTok and YouTube: nine platform posts per London
calendar day. Facebook/X are outside this first release.

The founder explicitly approved YouTube Shorts, initially silent and captioned,
then requested adding voiceovers. The desired YouTube output is now **narration
plus readable captions, with no background music**. Static-first/no-music remains
the direction for Instagram/TikTok where their verified automatic routes support
it. YouTube receives a rendered video, not a Community image post. This resolves
the format decision; it does not prove that a renderer or automatic delivery works.
A separate format decision is still needed if TikTok image/no-music automatic
publishing fails.

The narration stage should use an ordinary synthetic narrator with the approved
script; voice, pacing and pronunciation of card/anime names need a sample check.
Compose the voice track and synchronized captions into the final video before
Buffer receives it. Include speech availability, generation failures, timing,
pronunciation and audio-level checks in the creative pipeline. A changed script
or voice track changes the approved asset revision.

Plugin discovery found Higgsfield available but not installed; its declared
capabilities include narration and subtitles, matching the project's creative
provider direction. A connection suggestion was shown. No provider was connected,
credits purchased, voiceover generated or unattended speech API configured. A
ChatGPT plugin connection alone would not establish the background n8n renderer.

### Audited state

| Stage | Current evidence | Still needed |
| --- | --- | --- |
| Content/creator research | Editorial study in draft PR #512; not a continuous feed or representative performance dataset | Permitted source adapters, stored references/timestamps/rights and recurring collection |
| Topic selection and briefs | Tested stateless preparation in draft PR #512 | Durable daily selection, diversity, deduplication, freshness and stock/destination checks |
| Finished creative | Layout/brief direction exists; voiceover Shorts requested | Original/licensed images, narration, captions, Shorts rendering, stored assets and format validation |
| Durable approval and publication | Foundation schema/design in draft PR #216 | Reviewed schema, backend repositories, revision approvals, publication claims, audit and recovery |
| Connected channels | Live UI: Instagram, TikTok and YouTube connected; zero scheduled posts | A real automatically delivered pilot on each platform |
| Cadence and reconciliation | Read-only checks in draft PR #513 | Recurring preparation, capacity-aware scheduling, remote IDs/read-back, missed-slot alerts and ambiguous-write reconciliation |
| Performance and conversion learning | Measurement design only | Metric ingestion, follower snapshots where permitted, verified store attribution and evidence-based experiments |

Production n8n was checked again during this audit. Railway reports SUCCESS on
deployment `c45658f8-f684-4c49-958c-1bc80b918543`, running main commit
`21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1`, with the Buffer key name present and no
staged changes. This is service/configuration evidence, not inspection of the
private runtime's workflow database or proof of a marketing execution. PRs #216,
#512 and #513 remain unmerged drafts. The main workflow registry labels creative
generation, social publishing and analytics PLANNED.

**Conclusion: the research/create/publish/measure loop is not operational yet.**
Green tests for isolated components do not certify an end-to-end marketing system.

### Completion contract

1. Research creates an evidence-backed candidate set. Creator content informs
   hooks, formats and topics; it is not copied. Unknown creator reach, sales or
   missing metrics are not invented. Every factual claim and reusable asset keeps
   its source and rights/provenance record.
2. Three distinct stories are selected per London day. Each has a purpose,
   audience, verified facts, relevant store destination/CTA and three platform
   variants. Approval binds to the exact text and media revision. Changed assets
   invalidate approval. Freshness, unsupported claims and rights failures enter
   Action Required; a vetted evergreen reserve covers ordinary feed gaps.
3. One approved pilot per platform publishes automatically and yields its provider
   ID, platform URL and confirmed delivery state. A reminder, accepted API request
   or occupied queue slot is not delivery proof. Test timeout-after-write and
   duplicate-trigger recovery without blind retries or duplicate public posts.
4. Sustain three confirmed posts on each of the three channels per London day for
   seven consecutive days: 63 posts, zero duplicates, and an auditable record of
   scheduling/delivery times. Failed slots alert rather than publishing unchecked
   filler. Once this pilot passes, ongoing monitoring continues to detect drift.
5. Respect Buffer's current Free queue capacity of ten posts per channel. Target
   a rolling three-day horizon (nine per channel), subtract existing user/provider
   posts, and refill only after capacity is verified. A capacity limit is not a
   reason to buy a plan or overwrite existing content automatically.
6. Store metric snapshots with source, post, observation time, provider update time
   and coverage. Track supported views/reach, comments, saves/shares, engagement
   rates, watch/completion measures and followers/subscribers. Missing or delayed
   metrics remain unknown; unavailable follower attribution is not reported as zero.
7. Verify the real clickable path to the store on each platform. Use campaign/post
   identifiers and tracked destinations where supported; do not assume caption
   URLs are clickable. Connect observable sessions, product views, add-to-cart,
   checkout and orders/revenue to campaign evidence. Test the full attribution path
   with an isolated test event/order excluded from production growth reports.
   Report unattributed and channel-level traffic separately; do not invent exact
   per-post conversions for link-in-bio, cross-device or unobservable journeys.
8. Compare topics, formats, hooks, CTAs and posting windows using sufficiently
   mature observations. Prioritize attributable conversions/qualified traffic,
   then follower growth and meaningful engagement. Log bounded experiments and
   keep an exploration allocation; one viral post is not proof of a better policy.

The next implementation phase is durable content/evidence/revision/publication
state and its backend tests, integrating the existing draft foundations before
source collection and rendering. n8n remains orchestration; deterministic rules
remain in FastAPI, and PostgreSQL remains the source of truth. No new deployment,
production migration, automatic publisher or marketing schedule was enabled by
this audit. Business growth is an outcome to measure and improve, not guaranteed
by achieving the posting cadence.

Provider references checked for this audit:
- https://support.buffer.com/en-us/articles/using-youtube-shorts-with-buffer-Jl8iR6jIck
- https://support.buffer.com/en-us/articles/how-many-posts-can-i-schedule-in-advance-Kmy2IEecqm
- https://developers.buffer.com/examples/get-post-metrics.html
- https://support.buffer.com/en-us/articles/supported-channels-LM3P7Y4zsp

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
