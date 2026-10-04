# Drop Rate n8n provisioning

This directory makes production n8n workflows version-controlled and reproducible without exposing the n8n editor publicly.

## Daily static editorial direction - 4 October 2026

Drop Rate covers cards, comics, manga, anime and screen releases across the
founder's requested franchises. See
[`docs/STATIC_SOCIAL_RESEARCH_AND_PLAYBOOK.md`](../../docs/STATIC_SOCIAL_RESEARCH_AND_PLAYBOOK.md)
for research, the varied carousel programme and measured traffic/sales experiments.
Artist stories are one recurring format, not the entire feed. Static-first, no music.
The goal is automated research, creation, channel management, multiple daily
posts and performance learning. Initial test target: three distinct daily stories;
confirmed across Instagram, Facebook, YouTube, TikTok and X (15 platform slots).
This end-to-end system is not yet implemented or active.

[`plans/daily-tcg-editorial.json`](plans/daily-tcg-editorial.json) remains a design
specification, not a runtime consumer or importable workflow. A separate real
inactive DR-31 preparation workflow now exists; no publisher is connected.
Instagram/Facebook/TikTok/X static routes need account/provider proof. YouTube
Community image posting has no documented public Data API creation route found;
do not silently substitute Shorts or daily manual posting.

## Rules

- Base image is pinned in `Dockerfile.n8n`.
- Workflow JSON contains no credentials or secrets.
- Startup provisioning is additive: it imports a workflow only when its stable workflow ID is absent.
- Startup must never delete/recreate the n8n SQLite database.
- Existing persistent workflows are not silently overwritten.
- Workflow publishing is a separate deliberate step after import/validation.
- Secrets remain Railway environment variables / n8n credentials, never Git.

## Why additive first

Blind re-imports can overwrite a workflow while an older execution is running or erase a manual emergency correction. V1 therefore bootstraps missing workflows only. A later deployment tool can perform explicit, version-aware updates with backup/rollback.

## Production migration gates

Before switching the existing n8n service from the stock image:

1. Build the derived image in CI.
2. Validate every workflow JSON.
3. Confirm n8n owner/project initialization supports CLI import.
4. Confirm the persistent volume is mounted at application start.
5. Take/verify a recoverable n8n database backup.
6. Deploy with the same encryption key and user-folder settings.
7. Verify health, workflow list and webhook registration.
8. Redeploy once more and prove the workflow/database persist.
9. Only then point the automation dispatcher at DR-00.

No public n8n domain is required for this provisioning model.

The startup provisioner deliberately refuses to start if the DR-00 runtime requirements above are missing. This is safer than starting an apparently healthy n8n service whose signed ingress can never authenticate events.


## DR-00 signed ingress

`DR00IngressV1` is the first version-controlled ingress workflow. It is intentionally imported **inactive**.

Runtime requirements before activation:

- `DROP_RATE_AUTOMATION_WEBHOOK_SECRET` must match the dispatcher secret and be at least 32 characters.
- Set `NODE_FUNCTION_ALLOW_BUILTIN=crypto` so the Code node can use Node's HMAC implementation.
- Set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` because n8n 2.x blocks `$env` access by default and DR-00 reads only `DROP_RATE_AUTOMATION_WEBHOOK_SECRET` from `$env`.
- Treat that env-access setting as a security boundary: only trusted, version-controlled Code workflows may run on this n8n instance, and the service environment should contain only secrets it genuinely requires.
- Requests older/newer than five minutes are rejected.
- The Webhook node preserves the raw request body; HMAC is verified over those exact bytes with a timing-safe comparison before the event can be acknowledged.
- Invalid signatures/envelopes receive HTTP 401; valid envelopes receive HTTP 202.

**Important:** do not activate DR-00 merely because it imports successfully. A 202 causes the dispatcher to ACK the outbox event. Activation therefore waits until the event router/handler is connected and an end-to-end test proves that accepted events are durably handled rather than swallowed.


## Launch operating system

The founder-approved pre-launch strategy is documented in:

- `docs/N8N_LAUNCH_OPERATING_SYSTEM.md`
- `automation/n8n/workflow-registry.json`

The strategy is **build broad / activate narrow**.

All 42 workflow families may be designed and implemented before launch, but a workflow may not become ACTIVE until its registry activation requirements are satisfied.

The control plane is the first implementation wave:
- global error workflow;
- Action Required bridge;
- execution receipts;
- dead-letter/replay visibility;
- backlog/heartbeat monitoring;
- workflow health.

The registry is source-controlled and tested. n8n UI state is never the authoritative workflow catalogue.

## DR-90 global error workflow

`DR90GlobalErrorV1` is the first control-plane workflow.

It is imported **inactive** until the backend receipt endpoint and matching runtime secrets are deployed and a synthetic failure is proven end-to-end.

Flow:

`n8n Error Trigger → normalize execution → HMAC-sign receipt → FastAPI /api/v1/automation/control/receipt → automation_runs + Action Required`

Rules:
- the workflow itself must not use itself as its own Error Workflow;
- failed execution IDs are idempotent;
- duplicate receipt delivery is a no-op;
- system-level failures fan out only to active founder Action Required queues;
- n8n cannot choose Action Required severity/category/code;
- no inventory/ownership/price/settlement mutation occurs;
- `DROP_RATE_AUTOMATION_COMMAND_SECRET` must match FastAPI `TCG_AUTOMATION_COMMAND_SECRET`;
- `DROP_RATE_API_AUTOMATION_CONTROL_URL` points to the governed FastAPI receipt endpoint.

Before activation:
1. deploy backend receipt endpoint;
2. configure matching command secret;
3. configure private/internal FastAPI control URL;
4. import DR-90;
5. trigger one synthetic failure;
6. prove exactly one automation_run per founder and one deduped Action Required per founder;
7. replay the same receipt and prove no duplicate state;
8. only then set DR-90 as the error workflow for other workflows.


## Production source cutover safety

Production source cutover is complete on the existing `drop-rate-n8n-e840` service. Railway builds `Dockerfile.n8n` from the repo while keeping n8n pinned to `ghcr.io/n8n-io/n8n:2.32.6` and preserving the existing volume at `/home/node/.n8n`.

Startup validates control-plane runtime requirements, creates the one-time `database.sqlite.pre-drop-rate-provision-v1.bak` rollback copy when absent, refuses workflow JSON unless `active=false`, imports only missing stable IDs, and verifies every expected workflow ID exists after import.

The 30 September cutover proved persistent state was retained: DR-00 and DR-90 were detected as existing workflows, DR-91 was imported as a missing inactive workflow, and n8n started with zero published workflows.

The provisioner never wipes/recreates the persistent database and never imports credentials. The volume-local copy protects the source/provisioning rollback path; it does not replace normal platform-level backups.

## DR-91 durable success receipt

`DR91SuccessReceiptV1` is a reusable inactive sub-workflow for parent workflows that have completed and verified their governed action.

Inputs:
- workflow key/version;
- n8n execution ID;
- Drop Rate idempotency key;
- completion timestamp;
- optional owner ID;
- optional automation event ID.

Flow:

`Execute Sub-workflow Trigger → validate/normalize → HMAC-sign SUCCEEDED receipt → FastAPI control receipt → verify durable acceptance`

Durable receipt idempotency uses the supplied `idempotency_key`, not merely the n8n execution ID. If n8n executes the same business event twice, the durable run receipt can therefore remain one logical result.

Parent workflows should call DR-91 only after their external/backend action has been read back or otherwise verified. Starting a workflow is not success.


## DR-92 n8n runtime heartbeat

`DR92RuntimeHeartbeatV1` is the inactive control-plane heartbeat. It exists to prove that scheduled n8n execution can still reach and durably update the governed backend; Railway container health alone is not sufficient evidence.

Flow:

`5-minute Schedule Trigger → build fixed heartbeat → HMAC-sign → FastAPI /api/v1/automation/control/heartbeat → private Postgres heartbeat state → 30-minute operations monitor`

Rules:
- the only accepted heartbeat key is `n8n-runtime`;
- heartbeats are signed with the existing automation command secret;
- duplicate or out-of-order executions cannot move the stored heartbeat backwards;
- the database stores the latest control-plane heartbeat, not business truth;
- monitoring is dormant by default via `TCG_N8N_HEARTBEAT_ALERTS_ENABLED=false`;
- when alerting is deliberately enabled, stale heartbeats create one deduped HIGH Action Required item per active founder and a healthy heartbeat resolves it;
- no inventory, ownership, pricing, settlement or customer state is mutated.

Activation gate:
1. deploy and apply the heartbeat database contract;
2. import DR-92 inactive;
3. manually execute it once and verify a durable heartbeat row;
4. replay the same execution and prove duplicate safety;
5. prove the stale/healthy Action Required lifecycle;
6. only then activate DR-92 and enable heartbeat alerts.

## DR-00 V2 + DR-01 Shopify publication

DR-00 V1 remains untouched because production n8n provisioning never overwrites an existing stable workflow ID.

The versioned path is:

`automation dispatcher → DR00IngressV2 → DR01InventoryApprovedShopifyV1 → signed FastAPI command → deterministic Shopify publication/read-back → DR91SuccessReceiptV1`

Failures inside DR-01 route to `DR90GlobalErrorV1`. DR-00 V2 returns HTTP 200 only after the child workflow completes successfully; a child failure therefore remains retryable to the dispatcher.

DR-01 owns no Shopify or database business rules. FastAPI validates the exact `inventory.approved` envelope and the database revalidates the matching DISPATCHING automation event before draft persistence/finalization.

Both workflows are imported inactive. Activation requires a controlled switch of the dispatcher webhook URL to `drop-rate/events-v2`; do not repoint the dispatcher until DR-90/91 are published/proven and a controlled DR-01 event has passed duplicate, retry and read-back tests.

## DR-01 V2 / DR-00 V3 command-router correction

The first inactive DR-01 build was imported before the signed Shopify command was split from the generic automation-control router. Its stored command URL therefore targets the retired control-path location.

Do not activate `DR01InventoryApprovedShopifyV1` or `DR00IngressV2`.

Use the versioned corrected path only:

`dispatcher → DR00IngressV3 (/drop-rate/events-v3) → DR01InventoryApprovedShopifyV2 → /api/v1/automation/commands/shopify/inventory-approved → DR91`

The old workflows remain inactive as audit history because the provisioner deliberately never overwrites a persistent workflow ID.

## DR-02 Shopify product updates v1

DR-02 v1 intentionally handles **Store Price projection drift only**.

Flow:

`15-minute schedule → signed FastAPI product-updates command → Postgres candidate snapshot → Shopify variant-price update/read-back → Postgres version revalidation/finalize → DR-91`

Scope is deliberately narrow:
- published single-item links only;
- production/non-test products only;
- pooled variants excluded;
- reserved lines excluded;
- inventory must remain APPROVED + FOR_SALE;
- canonical Store Price always comes from Postgres.

Title, description, SEO, media and arbitrary metafield rewrites are **not** included in DR-02 v1. They require their own deterministic readiness/update contracts rather than being bundled into a generic n8n mutation.

The workflow is imported inactive. Its migration must be applied through the normal manual production migration gate before any controlled activation test.

## DR-31 static editorial preparation v1

`DR31StaticEditorialPreparationV1` accepts a `brief_json` string, signs it with
the existing automation command secret and calls
`/api/v1/automation/commands/editorial/prepare`. The backend validates supplied
observations and returns a six-to-eight-slide brief and explicit blockers.
Every response has `publishable:false` and `stored:false`; no URL is fetched.

This workflow contains no scheduler, live source collection, rendering or
publisher. It must not call DR-91 because no durable action was completed.
It is imported inactive only after normal deployment; no live import is claimed.
The API must be deployed and DR-90 proven before a controlled execution.
`TCG_EDITORIAL_STOREFRONT_ORIGIN` is optional backend configuration; no configured
origin means no commerce link. Source text, dates and relevance still require
independent authoritative verification before any later publishing workflow.
