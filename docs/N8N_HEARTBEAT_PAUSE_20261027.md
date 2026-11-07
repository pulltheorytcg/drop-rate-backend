# Guarded DR92-only pause — 27 October 2026

## Reason and observed definition

The automatic DR93 storage check returned HTTP 200 at `16:00:23 UTC`; the DR92
heartbeat then returned HTTP 500 and its DR90 error receipt HTTP 503 at
`16:00:34 UTC`. Database repairs are being prepared separately, while the
database connector is unavailable. Pausing the recurring heartbeat prevents
repeated failed technical requests during that repair. It does not claim the
backend defect is fixed.

Production deployment `61736e76-bbd2-4786-8a90-dbf49ea5b70b` reported exact
source/stored/published DR92 matching in the metadata receipt at
`2026-10-27T15:17:38.596902152Z`. Its normalized definition hash is:

`08c04d8a6b35e48ea7605f57a3db8910ebd7d0932f99d65c03ac239f773bb28e`

DR90 and DR93 were also published at their reviewed hashes; DR94 and DR91 were
inactive and unpublished. The helper rechecks actual state at operation time,
instead of trusting this earlier observation. It requires the four core
definitions and their current/published history to match the committed plan.
Only `DR92RuntimeHeartbeatV1` is selected for mutation.

## Disabled release, then explicit pause

Deploy the code with the new flag absent or false. After the pinned-runtime
unpublish smoke passes, the pause phase uses:

```text
DROP_RATE_N8N_HEARTBEAT_PAUSE_ON_BOOT=true
DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT=false
DROP_RATE_N8N_CONTROL_PLANE_PUBLISH_ON_BOOT=false
DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT=false
DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT=false
DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=false
DROP_RATE_N8N_METADATA_INSPECT_ON_BOOT=true
```

Keep the API and n8n Drive enable flags false. The operator refuses any
concurrent upgrade or publication phase. It verifies the local n8n socket is
offline, takes the shared exclusive lock, verifies n8n `2.32.6`, and creates a
private WAL-aware SQLite backup with integrity/hash/readback evidence. It then
rechecks source, stored/published state, current history and offline status.

The only mutation command is:

```text
n8n unpublish:workflow --id=DR92RuntimeHeartbeatV1
```

The [pinned command implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/cli/src/commands/unpublish/workflow.ts)
requires a restart for changes to affect a running server. This hook therefore
runs before `n8n start`, on the existing volume. It does not use broad
unpublication, edit executable workflow definitions, add a synthetic probe or
run a workflow. DR90, DR93, DR94 and DR91 retain their existing state.

## Required readback

Require a `DROP_RATE_N8N_HEARTBEAT_PAUSE` event with:

```json
{
  "plan_id": "pause-dr92-heartbeat-20261027-v1",
  "workflow_id": "DR92RuntimeHeartbeatV1",
  "status": "PAUSE_VERIFIED",
  "changed_count": 1
}
```

The full event must include a verified backup and source-matching DR92 with
`active:false`, `published:false`. The other three core workflows must have
their original publication states and exact reviewed hashes. The independent
five-workflow metadata event must confirm DR91 remains unchanged. A repeated
pause of the same already-unpublished definition returns `changed_count:0`
without another command, backup or history change.

Clear the pause flag after successful readback. Clearing it alone does not
resume a persisted unpublished schedule. Keep DR94 unpublished and DR91/Drive
activation off while their required backend acceptance remains unverified.

## Validation and later resumption

The native `--network none` smoke calls the actual n8n 2.32.6 unpublish command
for only DR92. It verifies the backup, inactive readback and no-op retry, and
compares every other workflow entity, every history row and all ownership rows
before/after. It also requires zero executions. Local SQLite tests cover source,
stored and history drift, backup failure/recheck, protected-state readback,
phase conflicts and the shared lock. The wrapper has a 60-second process-group
deadline and 64 KiB metadata cap, suppresses raw CLI output, and blocks startup
on a requested failure.

After the scoped heartbeat database repair and backend readiness are verified,
DR92 can be republished with the existing reviewed `health-schedules` phase;
an already-current published DR93 is a no-op in that phase. Keep the pause flag
false for resumption. Observe an actual successful automatic heartbeat and its
durable acceptance before claiming recovery. No manual probe or permission
bypass is part of this pause/recovery path.

## Production pause proof

PR [#761](https://github.com/pulltheorytcg/drop-rate-backend/pull/761) merged as
`47b56af19ac8bb11677063c30c41a602538febfd`. Its exact-head
[native job](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40544576561/job/122331604339)
proved the one-ID pause and preserved state at 16:50:54 UTC. The default-off
n8n release `cbc252e6-3504-44d0-be7c-cd16ae8d825c` succeeded at 16:53:51 UTC.

The subsequent production pause deployment
`f85935ed-6da5-46d7-8cdb-700ca0908e67` succeeded. Its receipt at
`2026-10-27T16:55:16.064077651Z` reported `PAUSE_VERIFIED`, `changed_count:1`,
and a verified 2,748,416-byte backup with SHA-256
`04dbe14417b3f4106c7f4d2486adc6017ea49870470a25315b8422c3355c0481`.

The operation and independent five-ID inspection at 16:55:16 UTC both showed
DR92 inactive and unpublished at its reviewed stored hash. DR90 and DR93
remained active/published, DR94 remained inactive/unpublished, and DR91 retained
its prior inactive/unpublished definition. No database repair is implied by
this pause. The pause flag was then cleared for the separate inactive DR91
source repair; clearing it does not republish DR92.
