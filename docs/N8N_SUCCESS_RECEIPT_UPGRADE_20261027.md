# Separate DR91 response repair — 27 October 2026

**Operational hold:** live heartbeat/error receipts encountered backend failures
on 27 October. Keep both DR91 flags false while the scoped database repair and
its verification remain blocked. This package prepares the guarded operation;
it does not authorize publication against an unavailable receipt backend. The
separate [DR92 pause](N8N_HEARTBEAT_PAUSE_20261027.md) stops the failing schedule
without publishing DR91 or changing its stored definition.

## Observed state and exact scope

The production metadata inspector on n8n deployment
`4e16a798-7646-42ed-999e-4394bce145c3`, commit
`469efa9c0d01a653f9094c8b43c190b112f8265b`, returned `COMPLETE` at
`2026-10-27T15:07:24.645509857Z`. DR91 was inactive and unpublished, with no
error-workflow setting. Its stored hash was:

`8f8b466d808171b2458fc0bcfc7a64a3ae8271221e084353d7eaf35198981296`

The source hash was:

`1687b41a0f99a4ef27f1c1ad99c07bbbbe2aa0d68d959670dd6670ef40055568`

The first hash is now actual live evidence, rather than an inference from the
old repository source. Deployment `635a5db2-67a3-442f-9066-d84f8d9a7dd1`
subsequently upgraded exactly DR90/92/93/94. Its independent metadata receipt at
`2026-10-27T15:09:36.988108013Z` confirmed DR91 remained unchanged, inactive and
unpublished, while the four core stored hashes matched source. That deployment
reached `SUCCESS` at `15:09:50 UTC`. The Drive credential scan was complete and
empty in both inspections.

The separate plan is
[`success-receipt-upgrade-20261027.json`](../automation/n8n/ops/success-receipt-upgrade-20261027.json).
It allows only `DR91SuccessReceiptV1`. The reviewed difference is the HTTP
response-format value `json` → `autodetect`. Reversing that one value must
reproduce the exact observed old hash. Raw signed request bytes, receipt
validation, workflow IDs, settings and credentials are unchanged.

This addresses the pinned n8n stream behavior established by the successful
[DR90 native canary](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40527085392).
The corrected DR91 also executed successfully in the isolated
[DR95 native smoke](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40526508462),
including idempotent completion-receipt replay against the fixture backend.
Neither result is a production success-receipt observation.

## Repair phase

Release this helper with both new flags absent or `false`. Once its exact
pinned-runtime importer/publication CI passes, enable only:

```text
DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT=true
DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT=false
DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=false
DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=false
DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=false
DROP_RATE_N8N_METADATA_INSPECT_ON_BOOT=true
```

The helper requires all four core source/stored/draft-history definitions to be
current. They may already be published, but every published version must match
the reviewed source. DR91 must remain inactive and unpublished at its exact old
or already-repaired hash; its current history must match the stored definition.
The helper uses the existing offline check, shared exclusive lock, bounded CLI,
WAL-aware private SQLite backup and source/state recheck. The backup and
readback cover all five inspected workflows. Backup files remain under the
existing volume-local backup directory with private permissions.

One `import:workflow --activeState=false` call contains only DR91. Readback
requires the new stored and current history hashes, continued inactivity, and
the same reviewed core publication state. The event
`DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE` must report `SOURCE_MATCH_VERIFIED`,
`changed_count: 1`, and a verified backup. A repeated repair of the same
inactive source-matching version reports `changed_count: 0` without CLI writes
or another history version. Disable the repair flag after that receipt.

## Separate publication phase

After verifying the actual repair receipt, enable only:

```text
DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT=false
DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT=true
```

Keep the core and legacy media mutation flags false. This phase requires
source/current-history matching for all five workflows and an exact published
DR90 handler. It makes another verified backup, rechecks the state, and calls
`publish:workflow --id=DR91SuccessReceiptV1` only. Require `PUBLICATION_VERIFIED`,
`publication_mode: success-receipt`, `changed_count: 1`, and DR91's exact
published hash. A repeat produces `changed_count: 0`; disable the flag afterward.
The server starts after the CLI phase so it loads the new published state.

DR91 has only an Execute Sub-workflow trigger. Publishing it does not run it or
start a schedule/webhook. This phase does not publish DR95, authorize Google,
bind credentials, upload an archive, or prove production receipt replay.
The API and n8n Drive enable flags remain false. Actual Google authorization and
the reviewed private destination remain separate activation prerequisites.

## Validation and failure handling

The offline tests use real temporary SQLite files to verify the one-ID
boundary, five-workflow WAL backup, credential/ownership preservation, exact
hash/history refusal, source and stored drift, phase conflicts, shared lock,
publication prerequisite and both no-op retries. The existing n8n-image CI
smoke now repairs and publishes DR91 after all four core fixture workflows are
published. It compares their complete entity and history rows before/after, verifies exactly one
new DR91 history version and zero execution records, and retries both phases.
This is a disposable `--network none` runtime with no production database or
credentials. Its success is required before enabling either new flag.

Each requested operation has a 60-second process-group deadline and 64 KiB
metadata output cap. Raw n8n stdout/stderr and credential data are never logged.
A requested failure blocks startup with a fixed reason and retains the backup.
Do not restore a SQLite backup over a running writer; retain current database
and WAL state and review the specific failure before recovery.

## Production source repair proof

PR [#761](https://github.com/pulltheorytcg/drop-rate-backend/pull/761) merged as
`47b56af19ac8bb11677063c30c41a602538febfd`. Its exact-head pinned-runtime
[job](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40544576561/job/122331604339)
proved the DR91 repair, separate publication and no-op retries at 16:50:51 UTC.

Production deployment `5543dc3b-fcff-419c-b4cf-920d1049a278` succeeded. The
receipt at `2026-10-27T16:57:03.585791308Z` reported `SOURCE_MATCH_VERIFIED`,
`changed_count:1`, and a verified 2,748,416-byte backup with SHA-256
`215280dc84fb0982d76f270fb358db55090f2fd51d2528cc7e658cd290eee017`.
DR91's stored hash is now
`1687b41a0f99a4ef27f1c1ad99c07bbbbe2aa0d68d959670dd6670ef40055568`,
matching the reviewed source. It remains inactive and unpublished.

The independent five-ID inspection at 16:57:03 UTC confirmed every stored
definition matches source. DR90 and DR93 remain published; DR92 remains paused
and DR94 remains unpublished. No supported Google Drive credential was present.
All one-time mutation flags were then cleared for the next deployment. No
production DR91 execution or durable backend receipt has been claimed: the
database repair and successful signed acceptance remain prerequisites to
publication and Drive activation.
