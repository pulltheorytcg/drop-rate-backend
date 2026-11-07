# Guarded n8n control-plane update — 27 October 2026

## Scope and evidence

This operation repairs JSON response parsing in four observed, inactive
control-plane workflows and adds the three missing DR90 error-handler links.
It preserves the n8n SQLite volume, workflow IDs, signed request bytes and
ownership. Publication is a separate operator phase.

The metadata inspection on deployment
`166e3937-4c17-4f7d-9b36-be94d380ccfa` at
`2026-10-27T14:02:40.995663898Z` reported all four workflows inactive and
unpublished. DR90 matched the source at that observation. The subsequent native
canary exposed a real parser defect in that definition: the signed receipt was
accepted by the local receiver, but `Control Receipt Accepted?` failed because
the HTTP response body was still a stream object.
The bounded diagnostic from [CI run 40525381921](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40525381921)
at `2026-10-27T14:55:23Z` recorded one accepted receipt, zero rejected receipts,
and the final-node classification `RECEIPT_RESPONSE_NOT_ACCEPTED`. The success
gate remains a completed successful handler and exactly one accepted receipt.

Pinned `HttpRequestV3` sets `useStream: true` for raw request bodies. The explicit
JSON response branch only parses strings, while `autodetect` consumes the stream
and parses an `application/json` response. The backend-network adapter confirms
that `useStream` selects Axios `responseType: stream` and keeps its
`IncomingMessage` body. The reviewed fix changes only the response format to
`autodetect`; it retains raw request serialization, full status/body responses,
and strict status/boolean acceptance checks. The fixture receiver is unchanged.
Compatibility references are the pinned
[HTTP Request implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/HttpRequest/V3/HttpRequestV3.node.ts),
[Axios adapter](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/backend-network/src/http/axios/legacy.ts),
and [legacy response adapter](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/%40n8n/backend-network/src/http/legacy-request.ts).

Reversing that one response-format change in each target and removing the
DR92/DR93/DR94 `settings.errorWorkflow` links exactly reproduces every actually
observed stored hash.

| Workflow ID | Reviewed update | First rollout state |
| --- | --- | --- |
| `DR90GlobalErrorV1` | Parse streamed JSON response with `autodetect` | Inactive, unpublished |
| `DR92RuntimeHeartbeatV1` | Same response repair; set `settings.errorWorkflow` to DR90 | Inactive, unpublished |
| `DR93ObjectStorageHealthV1` | Same response repair; set `settings.errorWorkflow` to DR90 | Inactive, unpublished |
| `DR94R2ApprovedMediaMirrorV1` | Same response repair; set `settings.errorWorkflow` to DR90 | Inactive, unpublished |

The full observed and reviewed SHA-256 values are committed in
[`control-plane-upgrade-20261027.json`](../automation/n8n/ops/control-plane-upgrade-20261027.json).
Its plan ID is `control-plane-stream-response-and-error-links-20261027-v2`. The normalization is the
existing inspector's definition hash over ID, name, nodes, connections,
settings and node groups. Runtime-generated version IDs and execution state do
not affect that hash. No workflow code or credential values are logged.

The same inspection found no records of the supported Drive credential types
`googleDriveOAuth2Api` and `googleApi`. This is metadata evidence for those
types, not proof about other generic credentials or Drive authorization. This
release does not create or modify credentials.

DR91 has the same source-only response repair and is now included in the
read-only inspector. Its prior source hash is
`8f8b466d808171b2458fc0bcfc7a64a3ae8271221e084353d7eaf35198981296`;
its reviewed new source hash is
`1687b41a0f99a4ef27f1c1ad99c07bbbbe2aa0d68d959670dd6670ef40055568`.
At the initial release review, the prior hash was expected from the repository
and had not yet been observed in production. The fresh receipt at
`2026-10-27T15:07:24.645509857Z` subsequently confirmed that exact stored hash and
inactive/unpublished state. The separate
[DR91 repair plan](N8N_SUCCESS_RECEIPT_UPGRADE_20261027.md) uses that observation;
DR91 remains explicitly excluded from this four-ID import/publication plan.
DR95 cannot be activated on the basis of a corrected DR91 source file alone.
The parked DR01, DR01 V2 and DR02
raw JSON command nodes share this response-format issue and remain a separate
recorded repair task.

## Why the update runs before the server starts

The ordinary provisioner imports only absent stable IDs. That behavior cannot
repair an existing workflow, so this explicit, hash-pinned upgrade runs after
additive provisioning and before `n8n start`.

The helper requires SQLite, confirms the configured local n8n port refuses
connections, and uses an exclusive volume-local lock. Railway mounts the
volume at service startup and prevents two active deployments from mounting the
same volume concurrently. The deployment lifecycle provides the single-writer
boundary; the local port check alone is not a general distributed lock.
See Railway's [volume lifecycle](https://docs.railway.com/volumes) and
[volume restrictions](https://docs.railway.com/volumes/reference).

The database path follows n8n's actual `N8N_USER_FOLDER` and
`DB_SQLITE_DATABASE` rules. The older one-time pre-provision copy remains
unchanged; this operation creates and verifies its own backup at the resolved
database location.

## Phase 0: deploy inspection with mutations disabled

Deploy this release with `DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=false`,
`DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=false`,
`DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=false` and the existing metadata
inspection flag true. Review a fresh receipt for DR90 through DR94. The planned
four targets must still have their exact observed old hashes and remain inactive
and unpublished. Treat the DR91 record as newly collected evidence, not as
permission for this plan to write it.

## Phase 1: update the inactive definitions

After the exact release has passed the pinned-image CI checks, set only the
upgrade mutation flag on the existing n8n service:

```text
DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=true
DROP_RATE_N8N_METADATA_INSPECT_ON_BOOT=true
DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=false
DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=false
```

The metadata flag is read-only. Keep the existing one-shot bridge probe off;
this release does not invoke it. Do not enable the isolated canary flag on the
production service; that helper has no production startup hook.

On the next normal startup, the upgrade:

1. Verifies exact n8n version `2.32.6`, reviewed source hashes, observed stored
   hashes, and inactive/unpublished state for the fixed four IDs.
2. Makes a WAL-aware SQLite backup through `node:sqlite.backup()`. It checks
   database integrity, rereads the backed-up workflow metadata and computes a
   streamed SHA-256 receipt before proceeding.
3. Rechecks the source, offline state and stored metadata immediately before
   mutation. Unexpected changes stop the operation.
4. Runs one supported `n8n import:workflow --input=... --activeState=false`
   command containing only the pending reviewed DR90, DR92, DR93 and DR94 definitions.
5. Rereads each stored definition and its current draft history version. It
   requires exact reviewed hashes, DR90 error routing, and continued inactivity.

Expected event:

```json
{
  "event": "DROP_RATE_N8N_REVIEWED_UPGRADE",
  "plan_id": "control-plane-stream-response-and-error-links-20261027-v2",
  "status": "SOURCE_MATCH_VERIFIED",
  "changed_count": 4
}
```

The actual event additionally includes the private backup's ID, hash and byte
count plus the bounded workflow metadata. Require all four
`source_matches_stored` values to be true and all `active` and `published`
values to be false. The following `DROP_RATE_N8N_METADATA_INSPECTION` event
provides an independent fresh summary. Railway can store structured JSON fields
in log attributes while leaving the message empty; inspect the event attribute.

A retry against already-current inactive workflows returns the same verified
status with `changed_count: 0`, without another import or history version.
Disable the upgrade flag after collecting the successful readback. A future
definition revision requires a new reviewed plan; this operation cannot accept
arbitrary changed source or stored definitions.

## Phase 2: publish the exact error handler

The pinned n8n 2.32.6 implementation of `loadErrorWorkflowData()` requires a
published error handler and uses its published nodes and connections. An
unpublished DR90 cannot satisfy the automatic routing gate in this version.
This differs from generic Error Trigger documentation; the
[pinned implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/workflows/workflow-execution.service.ts)
is the compatibility reference.

After source-match evidence and the existing backend/secret readiness checks,
disable the upgrade flag and set:

```text
DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=false
DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=error-handler
```

This phase verifies all four stored and current draft-history definitions,
takes another verified backup, rechecks for drift, and calls
`n8n publish:workflow --id=DR90GlobalErrorV1` only. The receipt must report
`PUBLICATION_VERIFIED`, `publication_mode: error-handler`, and an exact matching
published DR90 hash. DR92, DR93 and DR94 remain unpublished. The server starts
after the CLI publication so it loads the new published state.

Disable the publication flag after the receipt. Publication is not evidence
that the production API accepted an error receipt. The isolated CI canary
proves the exact engine/handler contract, while live error fan-out and duplicate
receipt handling remain explicitly unverified until observed. This limitation
does not prevent diagnostic health scheduling. This release does not introduce
or run a production canary, manual wrapper or the older one-shot bridge probe.

## Phase 3: publish only the health schedules

Use `DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=health-schedules` only after the
source-match and DR90 publication receipts and pinned-image CI pass. This
selects DR92 and DR93 only. It requires the already-published exact DR90 version
and exact reviewed stored/history definitions, backs up and rechecks the
database, and verifies each published hash immediately after publication.
DR94 remains unpublished. Keep heartbeat alerts disabled during this diagnostic
activation.

Require `PUBLICATION_VERIFIED`, `publication_mode: health-schedules`,
`changed_count: 2` on first use, and only DR90/DR92/DR93 published at exact
reviewed hashes. Disable the flag after readback. Then observe actual automatic
execution:

- DR92 sends a signed request to `/api/v1/automation/control/heartbeat`. The
  endpoint returns success only after recording through
  `tcg.record_automation_heartbeat`. Read back the bounded `n8n-runtime` row and
  require a new execution ID, fresh timestamp and later progressing beat count.
  This proves live signing, API acceptance and durable heartbeat state.
- DR93 sends a signed request to
  `/api/v1/automation/commands/storage/health`. A successful response means
  `accepted: true` and `storage_status: REACHABLE` after a bucket-scoped
  `list_objects_v2` request with `MaxKeys=1`. It does not write an R2 object or a
  business record. This endpoint has no durable success-receipt table; use the
  actual API response/access status and available n8n execution metadata rather
  than inventing a database receipt.

The heartbeat updates only technical monitoring state. Neither workflow changes
inventory, ownership, prices, customers or settlements. Publication alone is
not execution proof; a new scheduled heartbeat cannot be required before its
schedule is published.

The pinned scheduler uses wall-clock cron boundaries, including a stable second
derived from the exact workflow/node ID. Hourly nodes receive the default
`triggerAtMinute: 0` when n8n materializes node parameters. There is no immediate
automatic execution on registration:

| Workflow | Effective cron in configured workflow/global timezone | First eligible execution after successful registration |
| --- | --- | --- |
| DR92 | `34 */5 * * * *` | Next five-minute boundary at second 34; under five minutes |
| DR93 | `23 0 */1 * * *` | Next hour boundary at second 23; under one hour |
| DR94 | `3 0 */1 * * *` | Next hour boundary at second 3; under one hour after its later publication |

Allow execution and network processing time after those boundaries. These are
schedule opportunities, not guarantees of successful delivery. The workflows
have no explicit timezone, so use the runtime's configured global timezone
rather than assuming UTC. The minute/second values are derived from the pinned
[cron generator](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/Schedule/GenericFunctions.ts),
[Schedule Trigger defaults](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/Schedule/ScheduleTrigger.node.ts)
and [workflow default materialization](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/workflow/src/workflow.ts).

The Railway OAuth connector currently returns variable names only. A filtered
read on 27 October confirmed API `TCG_AUTOMATION_COMMAND_SECRET` and n8n
`DROP_RATE_AUTOMATION_COMMAND_SECRET`/`DROP_RATE_API_AUTOMATION_CONTROL_URL` are
present but did not reveal values. Do not claim a direct equality/target-value
comparison. Normal startup validates the URL shape; an accepted automatic
signed heartbeat provides the live shared-secret/connectivity evidence.

The [pinned CLI](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/commands/execute.ts)'s
`execute --id` cannot start these schedule-only definitions;
its start selector requires a manual/chat or execute-workflow trigger. No manual
wrapper is needed for this staged activation.

## Phase 4: publish approved-media scheduling

After actual live heartbeat and storage-health evidence, use
`DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=media-schedule`. This selects only
DR94 and additionally requires exact published DR92 and DR93 versions. Require
`PUBLICATION_VERIFIED`, `publication_mode: media-schedule`, `changed_count: 1`
on first use, and all four published hashes matching. Disable the flag after
readback, then observe the actual hourly media execution.

DR94 submits a bounded batch with `limit: 3` to the existing approved-media
endpoint. The backend retains its rights, provider, content-hash and byte-readback
guards. An accepted response with `failed: 0` proves command completion; zero
pending candidates is a valid empty batch, not proof of a new object upload.
The helper cannot infer successful live health executions from publication
metadata. Setting this phase is the operator's decision after those observations.

The legacy `DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=true` path now also
requires fresh source/draft-history proof and exact published DR90, DR92 and
DR93 versions. Combining it with the new upgrade or publication flag is
rejected. The former combined `schedules` value is not accepted. No marketing,
customer, payment, Shopify, Drive or broad reference-image workflow is selected
by these phases.

## Backups and blocked operations

Backups are retained beside the resolved SQLite database under
`drop-rate-control-plane-backups/<plan-id>-<random>/`. Each directory is mode
`0700`; `database.sqlite`, the safe manifest and the reviewed import file are
mode `0600`. The database backup includes existing encrypted credential bytes
as part of the exact database. It is never exported to logs or uploaded by this
helper. Backup creation is bounded to databases of at most 512 MiB.

The helper's own database queries are read-only. Supported n8n CLI commands make
workflow changes and may initialize normal n8n services internally. CLI output
is captured and suppressed; diagnostics contain only fixed phase/reason codes
and reviewed metadata. The complete operation has a 60-second process-group
deadline and a 64 KiB output limit.

An explicitly requested mutation that cannot be verified emits `BLOCKED` and
stops startup. This differs from the optional read-only inspector, whose failure
remains nonfatal. Source drift, an active/unreviewed workflow, a missing backup,
an existing lock or unsupported runtime must be investigated before retrying.
Do not change expected hashes to bypass a mismatch.

The helper never deletes backups or automatically restores the database. An
interrupted process may leave `control-plane-upgrade.lock`; after proving that
no upgrade/server process is using the database, inspect the backup and live
metadata before an operator clears that lock. If restoration is required,
stop all writers, retain the current database and WAL state, and use the
verified backup under a separately reviewed recovery procedure. Do not copy a
backup over a running SQLite database.

## Verification and the isolated canary's limits

The backend CI test job pins Node `22.23.3`, the observed API runtime, so the
SQLite tests cannot silently depend on APIs available only in newer Node
versions. The exact n8n image supplies its own Node `24.18.0` for the native
runtime checks. The focused offline tests use actual temporary SQLite databases
to verify
WAL-aware backups, privacy, drift rejection, ownership preservation, no-op
retries, draft-history matching and phase isolation. The Python wrappers run
them in the normal backend test suite.

The existing `n8n-image` CI job builds the exact `2.32.6` image and then runs two
sequential checks with `--network none`:

1. Real n8n import/publication against a new disposable database: recreate the
   observed hashes, upgrade exactly four inactive definitions, preserve DR91, verify backup
   and ownership, retry without history growth, then exercise the separate
   error-handler, health-only and media-only publication commands, proving DR94
   remains unpublished after the health phase.
2. The isolated automatic canary: import and publish an exact DR90 copy and a
   token-checked local webhook fixture in another fresh database. Trigger one
   deliberate failure and require one failed `webhook` execution, one successful
   `error` execution and one HMAC-valid local receipt with matching identity.

The canary uses random temporary keys, a minimal environment, loopback-only
destinations, bounded child execution/output and guarded temporary cleanup. It
does not read production SQLite, credentials, runtime secrets or saved node
data. Its success event is `AUTOMATIC_ROUTING_VERIFIED` with
`production_backend_verified: false`. It proves the pinned engine's automatic
routing and the exact DR90 normalization/signing contract. It does not prove
the live API endpoint, shared production secret, receipt deduplication, founder
queue fan-out, scheduled heartbeat, storage probe or media delivery.

Native runtime checks must pass in CI before rollout; offline fixture tests are
not a substitute. Compatibility sources:

- [Pinned workflow importer](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/commands/import/workflow.ts)
- [Pinned import service and transactional history writes](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/services/import.service.ts)
- [Node SQLite backup API](https://nodejs.org/docs/latest-v24.x/api/sqlite.html#sqlitebackupsource-db-path-options)
