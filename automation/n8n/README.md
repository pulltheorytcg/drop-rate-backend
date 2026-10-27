# Drop Rate n8n provisioning

This directory makes production n8n workflows version-controlled and reproducible without exposing the n8n editor publicly.

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

Activation still requires the DR90 error-routing and heartbeat gates. n8n's
Error Trigger handler itself does not need publication, and manually running a
workflow does not invoke its error workflow: prove routing with a controlled
automatic failure before enabling the reviewed recurring jobs.

Run the offline fixture tests with Node 24:

```sh
node --no-warnings --test tests/n8n_stored_metadata.test.cjs
```

The pytest wrapper includes these tests in the existing backend CI job. They use
disposable SQLite databases, deny credential-data reads with a SQLite authorizer,
verify that the database file is unchanged, compare stored/published versions,
exercise malformed and oversized data, and prove startup survives an inspector
failure. They make no network calls.

Primary compatibility references:

- [Pinned n8n image and Node version](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/docker/images/n8n/Dockerfile)
- [Pinned workflow entity and publication field](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/db/src/entities/workflow-entity.ts)
- [Pinned published workflow export behaviour](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/commands/export/workflow.ts)
- [Pinned n8n folder resolution](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/config/src/utils/utils.ts)
- [Node SQLite read-only connection](https://nodejs.org/docs/latest-v24.x/api/sqlite.html)
- [n8n Error Trigger testing and publication rules](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.errortrigger/)

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

