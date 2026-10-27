# Drop Rate n8n provisioning

This directory makes production n8n workflows version-controlled and reproducible without exposing the n8n editor publicly.

## Rules

- Base image is pinned in `Dockerfile.n8n`.
- Workflow JSON contains no credentials or secrets.
- Default startup provisioning is additive: it imports a workflow only when its stable workflow ID is absent. The explicit guarded upgrade below handles the reviewed exception.
- Startup must never delete/recreate the n8n SQLite database.
- Existing persistent workflows are not silently overwritten.
- Workflow publishing is a separate deliberate step after import/validation.
- Secrets remain Railway environment variables / n8n credentials, never Git.

## Why additive first

Blind re-imports can overwrite a workflow while an older execution is running or erase a manual emergency correction. V1 therefore bootstraps missing workflows only. The guarded control-plane upgrade below adds an explicit version-aware update with a verified backup and separate recovery procedure.

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

It is imported **inactive**. Once the backend receipt endpoint and runtime configuration are deployed, verify the stored definition and publish DR90. n8n 2.32.6 loads only a published error handler. The staged health activation below proves live signed heartbeat/storage connectivity before approved-media scheduling. Live error-receipt fan-out and replay remain separate evidence gaps until observed; the isolated CI canary does not prove them.

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

Production readiness sequence:
1. deploy backend receipt endpoint;
2. configure matching command secret;
3. configure private/internal FastAPI control URL;
4. verify the exact inactive stored DR90 definition and its isolated automatic-routing CI proof;
5. publish DR90, then the diagnostic DR92/DR93 subset and observe actual signed health receipts;
6. keep production error fan-out and duplicate-receipt proof explicitly unverified until a real error or separately reviewed technical check establishes one automation_run and one deduped Action Required item per founder;
7. do not create a synthetic production failure merely to enable the diagnostic health schedules.


## Production source cutover safety

Production source cutover is complete on the existing `drop-rate-n8n-e840` service. Railway builds `Dockerfile.n8n` from the repo while keeping n8n pinned to `ghcr.io/n8n-io/n8n:2.32.6` and preserving the existing volume at `/home/node/.n8n`.

Startup validates control-plane runtime requirements, creates the one-time `database.sqlite.pre-drop-rate-provision-v1.bak` rollback copy when absent, refuses workflow JSON unless `active=false`, imports only missing stable IDs, and verifies every expected workflow ID exists after import.

The 30 September cutover proved persistent state was retained: DR-00 and DR-90 were detected as existing workflows, DR-91 was imported as a missing inactive workflow, and n8n started with zero published workflows.

The provisioner never wipes/recreates the persistent database and never imports credentials. The volume-local copy protects the source/provisioning rollback path; it does not replace normal platform-level backups.

## Read-only stored workflow and Drive credential inspection

`ops/inspect-stored-metadata.cjs` provides a bounded inspection on the next normal
startup when the operator explicitly sets
`DROP_RATE_N8N_METADATA_INSPECT_ON_BOOT=true`. It is disabled by default. The
startup hook runs after additive import verification and does not import,
overwrite, execute or publish a workflow. Remove or disable the flag after the
required evidence has been collected.

The helper uses Node's read-only SQLite connection directly. It does not start
the n8n CLI/ORM, run migrations, export credentials, read the credential `data`
column, or load the encryption key. The pinned n8n 2.32.6 image uses Node 24.18.0,
which supplies the required `node:sqlite` API. A separate child receives only the
database-location settings, has a 15-second hard deadline and a 64 KiB output
limit, and never receives application secrets or `NODE_OPTIONS`. Inspection
failure emits a fixed diagnostic and remains nonfatal to n8n startup.

One JSON log event, `DROP_RATE_N8N_METADATA_INSPECTION`, reports:

- Only `DR90GlobalErrorV1`, `DR92RuntimeHeartbeatV1`,
  `DR93ObjectStorageHealthV1`, and `DR94R2ApprovedMediaMirrorV1`.
- Normalized source, stored-draft and (when present) published-version SHA-256
  hashes, comparison results, source/stored `errorWorkflow`, and separate
  `active` and `published` states. In n8n 2.32.6, `activeVersionId` determines
  publication; the legacy `active` flag alone is not sufficient.
- At most 50 credential records containing **only** `id`, `name`, and `type`,
  restricted to `googleDriveOAuth2Api` and `googleApi`. The latter can be a Google
  service-account credential; its presence does not prove Drive access, usable
  scopes, or ownership of the intended account/folder. A truncation indicator
  prevents a partial result from being presented as a complete inventory.

Normalization `drop-rate-workflow-definition-v1` sorts object keys and hashes
`id`, `name`, `nodes`, `connections`, `settings`, and `nodeGroups` (empty by
default), preserving array order. It excludes generated timestamps/version IDs,
publication state, editor metadata, pinned data and static execution state. All
node parameters and credential references affect the hash, but their contents
are never logged. Published hashing follows n8n's export behaviour: nodes,
connections and node groups come from the referenced workflow-history version;
shared workflow settings come from the workflow entity. Each JSON column is
limited to 1 MiB. All reads share one read-only SQLite snapshot.

The helper follows the upstream database-path rule: append `.n8n` to
`N8N_USER_FOLDER` (or `HOME`, then the working directory), and resolve
`DB_SQLITE_DATABASE` relative to it. It supports a bounded alphanumeric/underscore
`DB_TABLE_PREFIX`. Unsupported database types, external config files, env-file
configuration, absent databases and schema mismatches produce fixed unavailable
or partial results; the helper never searches for another database or creates a
replacement file. It does not read or print configuration-file contents, paths,
environment values, raw errors, workflow code or credential data.

Source DR92 and DR93 now declare `DR90GlobalErrorV1` as their error workflow and
remain inactive. Existing stored copies are intentionally preserved, so a hash
mismatch is expected when their older stored definitions lack this setting.
Inspect and review that difference before choosing an explicit versioned update.
This inspection flag does not enable the existing DR94 publication switch.

The pinned n8n 2.32.6 implementation requires a published DR90 version: its
`loadErrorWorkflowData()` returns without running an unpublished handler.
This version-specific implementation takes precedence over the generic Error
Trigger documentation. A manual execution does not prove automatic error
routing. Publish the verified handler first, then enable only DR92/DR93 to
establish real automatic health receipts. A heartbeat cannot prove scheduling
before its schedule is published. The production error-receipt and fan-out
proof remains explicitly separate from this diagnostic activation.

Run the offline fixture tests with the API's Node 22.23.3 or the pinned n8n image's Node 24.18.0:

```sh
node --no-warnings --test tests/n8n_stored_metadata.test.cjs
```

The pytest wrapper includes these tests in the existing backend CI job. They use
disposable SQLite databases, deny credential-data reads with an erroring SQLite
view and an authorizer when the runtime provides one,
verify that the database file is unchanged, compare stored/published versions,
exercise malformed and oversized data, and prove startup survives an inspector
failure. They make no network calls.

Primary compatibility references:

- [Pinned n8n image and Node version](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/docker/images/n8n/Dockerfile)
- [Pinned workflow entity and publication field](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/db/src/entities/workflow-entity.ts)
- [Pinned published workflow export behaviour](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/commands/export/workflow.ts)
- [Pinned n8n folder resolution](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/config/src/utils/utils.ts)
- [Node SQLite read-only connection](https://nodejs.org/docs/latest-v24.x/api/sqlite.html)
- [Pinned error-handler publication requirement](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/workflows/workflow-execution.service.ts)
- [n8n Error Trigger automatic execution testing](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.errortrigger/)

## Guarded control-plane upgrade and publication

The observed 27 October stored copies of DR92, DR93 and DR94 are inactive and
unpublished. Each differs from the reviewed source only by the missing
`settings.errorWorkflow = DR90GlobalErrorV1`. The explicit plan in
`ops/control-plane-upgrade-20261027.json` pins both the observed and reviewed
hashes. DR90 is unchanged.

`DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=true` enables only this reviewed
inactive update. Before the server starts, the helper verifies the exact
runtime, source and stored hashes, confirms inactivity, takes a private,
WAL-aware SQLite backup, rechecks the state, and imports the three definitions
with `--activeState=false`. A retry with already-matching inactive definitions
does not import again. A failed requested upgrade stops startup with a bounded,
metadata-only diagnostic. The ordinary metadata inspector remains nonfatal.

Publication is a later, separate operation. Disable the upgrade flag, then use
`DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=error-handler` to publish only the
exact verified DR90. The `health-schedules` value publishes only DR92 and DR93
and requires DR90 already published at the exact reviewed hash. Observe an
actual durable heartbeat and successful signed read-only storage check before
using `media-schedule` for DR94. The media phase also requires both health
workflows already published at their exact reviewed hashes; the helper cannot
infer their successful live execution from publication alone. The legacy DR94
switch has the same publication prerequisites. Do not enable two mutation
phases in the same startup.

The pinned-image CI job exercises the real n8n importer and publication commands
against disposable SQLite state, then runs an isolated automatic error-routing
canary using the exact DR90 definition. The canary verifies one failed webhook
execution, one successful error-handler execution and one signed local receipt.
It does not use the production database, credentials or backend and explicitly
reports `production_backend_verified: false`. It has no automatic production
startup hook.

See [the guarded rollout and recovery procedure](../../docs/N8N_GUARDED_CONTROL_PLANE_UPGRADE_20261027.md)
for the phases, expected receipts, backup handling and remaining live gates.

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

Staged activation:
1. deploy and apply the heartbeat database contract;
2. verify the inactive source-matching DR92 definition and publish the exact DR90 handler;
3. publish DR92/DR93 through the guarded `health-schedules` phase while heartbeat alerts remain disabled;
4. verify the next automatic execution produces a fresh durable heartbeat row and the signed storage health request succeeds;
5. observe continued heartbeat progression before declaring recurring execution healthy;
6. test duplicate safety and the stale/healthy Action Required lifecycle before separately enabling heartbeat alerts. These alerting checks do not require holding the diagnostic heartbeat schedule unpublished.

The pinned `n8n execute --id` CLI cannot start these schedule-only definitions:
its start-node selector requires a manual/chat or execute-workflow trigger. Do
not claim a CLI run of a modified wrapper is an exact scheduled execution.

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

