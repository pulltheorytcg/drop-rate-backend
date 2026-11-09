# Inventory shadow catch-up — 8 November 2026

Issue #1010. This extends the existing protected operational staging workflow and existing operational D1 database. Supabase remains authoritative. No new service, financial writer, authentication change or UI change.

## Source and replay contract

- One read-only PostgreSQL REPEATABLE READ snapshot captures the existing reviewed table scope and canonical product link fingerprints. The transaction timestamp and source transaction-snapshot marker are captured inside that same transaction.
- Compare every original inventory JSON/hash and exact field against the complete previous shadow. Classify each changed record once as pricing, legitimate condition/location/grading/language update, timestamp-only, version increment or serialization discrepancy. Unknown fields, invalid/corrupt payloads, version regressions, ownership/identity/Store Price/cost changes and non-inventory table drift block replay. No sensitive field values or item IDs in logs/artifacts.
- Append a deterministic content-addressed generation through the existing stage mapper. Existing generations are retained unchanged. Partial new generations are quarantined with the existing REJECTED state until complete typed-column/original-JSON/hash readback, owner/currency ledger comparison, replay journal and checkpoint verification succeed.
- The checkpoint high-water mark combines a consistent source snapshot, capture timestamp and the exact per-item version vector (hashed root; individual versions retained in private replay journal and generation). Timestamp windows are not used to omit records: every source record is compared on each capture.
- D1 transactions atomically advance the shadow replay head and verified visibility state. Compare-and-swap prevents a concurrent head replacement. Source capture predating the current high-water mark is rejected. Content-identical retries do not duplicate inventory or ledger records. A persistent reservation allows at most one new bounded snapshot per UTC day, with 2,500 logical rows including journal/receipt overhead. Retries use the reserved capture marker.
- An independent fresh source capture runs after replay. New production changes still fail the drift gate. An actual source-parity receipt is required; a deferred budget result is not parity.

## Limitations and next gates

This full-snapshot catch-up is NOT WAL CDC. Intermediate audit events, complete historical prices, pricing snapshots, all financial relations and Auth have not been migrated by this nine-table transfer. Their source records remain protected and unchanged. The source pricing-snapshot foreign-key value is preserved in original inventory JSON, but full pricing provenance and audit-history migration remain separate gates. A source version jump is recorded, not represented as a complete event history.

Real production rows read/written and API request time are aggregated from Cloudflare response metadata. These metrics are per run, not an account-wide daily quota measurement or a performance benchmark for application search.

## Tests and rollback

Disposable SQLite simulations exercise exact fields and hashes, source IDs/Store Prices, version and timestamp rejection, pricing classifications, idempotency, partial-transfer retry, daily budget, new updates in a subsequent window, financial drift, corrupted typed projections and quarantine visibility. Existing owner/refund/ledger-trigger and full-exit register suites remain required. CI uses Python 3.12. Simulation success is not live D1 parity.

Rollback: disable/stop the existing staging workflow; production continues using its existing Supabase path. Prior D1 generations and their replay journal/checkpoints remain available. No source deletions or destructive D1 rollback are part of this release. Never remove the 400 MB safeguard or copy source passwords/sessions as part of catch-up.

Cloudflare documents transactional batch rollback in https://developers.cloudflare.com/d1/worker-api/d1-database/ . No operational financial cutover is authorised by a successful shadow replay.


## 9 November — interrupted recovery across UTC midnight

Offline reproduction found that a failed stage reserved on day one could retry
with unchanged source rows on day two, mint a second reservation and report
verified replay with different generation/checkpoint capture timestamps.

Pending generations now locate their original reservation by immutable
`generation_id` before checking the current day's budget. Exactly one matching
reservation must exist. Preserve its original UTC day, row limit, parent,
capture timestamp and source-snapshot marker; do not modify the old receipt or
create another day's allowance for the same pending generation. Unrelated new
source generations still obey the existing one-per-day/2,500-logical-row cap.

Duplicate or inconsistent old reservations, stale retry capture and changed
parents fail closed without repair writes. An already-advanced head must also
have one consistent checkpoint/reservation/generation capture mark, exact
original row budget and full typed/original-JSON readback before reporting
idempotent verification. Existing corrupt metadata is not automatically
rewritten to make a check green. Independent review/recovery is required.

Tests cover failure before generation creation and before journal insertion,
next-day retry with the original receipt unchanged, invalid old reservations,
lost activation acknowledgement, already-verified metadata corruption and typed
projection tampering. These are offline SQLite tests, not real D1 atomicity or
production replay receipts. Idempotent readback adds nine fixed SELECTs; actual
provider read metrics and account capacity still require review for an approved
run. No account-wide cost or unlimited Paid allowance is claimed.

## Explicit approval for every write-capable operational stage

`stage-real-private-d1` now requires both maintainer-controlled repository
Actions variables, in addition to its existing main/event/production-environment
and offline-test guards:

- `DR_D1_OPERATIONAL_STAGE_APPROVED_SHA`: exact full commit SHA.
- `DR_D1_OPERATIONAL_STAGE_APPROVED_RUN_ID`: exact GitHub run ID.

Empty or mismatched approval skips the entire job before credentials, source
capture or D1 writes. Push, scheduling and workflow dispatch alone do not approve
an import. A new run/commit cannot inherit another release's approval; same-run
retries intentionally retain the matching run ID. Clear approval variables after
the authorised release. Read-only drift monitoring is a separate unchanged
workflow and remains scheduled.

Before setting these variables or rerunning a protected job, obtain separate
release authorisation, check current source/parity and measured Cloudflare
usage/headroom, and verify the actual job gate is reevaluated for the approved
run. Do not invoke `--apply` locally as a shortcut. No approval variable is set,
protected job rerun, remote parity check or import performed by this code change.
Rollback is a code revert with write approvals left empty; retain all original
generations, budgets, journals and checkpoints. Supabase remains authoritative.
