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
