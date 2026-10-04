# Buffer connection handoff — 4 October 2026

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
