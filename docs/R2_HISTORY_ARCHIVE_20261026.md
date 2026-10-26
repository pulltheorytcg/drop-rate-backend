# Verified R2 history archival — 26 October 2026

## Problem and scope

The 26 October live audit found Supabase at 405,613,715 bytes, above the unchanged
400,000,000-byte bulk-refresh guard. There were 33,702 new history rows after the
49,290-row Drive archive completed at 17:28 UTC. Railway's API has no persistent
volume; n8n used roughly 0.102 GB of its 1 GB volume. The immediate bottleneck was
PostgreSQL price history, not Railway disk capacity.

The existing R2 exporter verifies a copy but cannot restore or reclaim database
storage. This release adds a bounded archive operation to the existing catalogue
worker, before its capacity guard. No new paid plan or Railway service is required.
Supabase remains authoritative for current prices, catalogue identity, owners,
inventory and settlements. Existing private Drive archives are retained.

## Safety and recovery contract

1. An existing platform administrator and the catalogue advisory lock are required.
2. Export a consistent, read-only snapshot of PostgreSQL canonical row JSON in UTC.
   Record exact count, ordered full-row hash root and compressed-byte SHA-256.
3. Upload the private content-addressed gzip. Download actual bytes and verify.
4. Parse and restore into a disposable typed PostgreSQL table in bounded batches.
   Validate every original field, quote payload, row identity and hash root.
5. Upload and verify a manifest with format, storage location and restore evidence.
6. Cleanup is a separately enabled operation. A private database function checks
   the platform-admin actor, validates the receipt, takes a short exclusive lock,
   and recomputes the full current-table count and root before truncation.
   Concurrent inserts or changed/missing rows cause refusal with no data removed.
7. Truncation and durable receipt insertion commit atomically. Retrying a committed
   receipt does not delete subsequent history. Archive objects are never deleted.

Only history with an exact, restorable external copy is reclaimed. A whole-table
verified truncation is used because DELETE alone does not reliably lower the
byte-based capacity measurement. Locks time out rather than holding checkout or
price updates indefinitely. The worker caps export rows/bytes and fails closed
when limits are exceeded. This is not a partitioning migration.

The private function encapsulates the minimum postgres-only cleanup privilege;
the API role receives no general DELETE or TRUNCATE permission. It is outside
the exposed API schema, authenticates the existing backend context and rechecks
platform-admin membership. Archive receipts have forced RLS and no public access.
No archive URL is signed for browser access.

## Rollout and rollback

Both flags default to false:

- TCG_HISTORY_R2_ARCHIVE_ENABLED: run a bounded attempt on worker startup and at
  most once per hour per process.
- TCG_HISTORY_R2_ARCHIVE_CLEANUP_ENABLED: permit the final verified reclaim step.

First deploy with only the first flag enabled. Observe successful byte and typed
restore verification and unchanged history count. Only then enable cleanup and
observe the committed receipt, actual bytes reclaimed, healthy API and subsequent
catalogue progress. Keep the database capacity threshold unchanged.

To pause, disable TCG_HISTORY_R2_ARCHIVE_ENABLED. Disabling cleanup alone retains
verified R2 copies without removing database rows. Prior Drive and R2 objects
remain durable. Each R2 receipt records exact object keys, endpoint, bucket,
digests, timestamps and actor. A restore must use those immutable objects and
verify original full-row hashes; never manufacture newer observation dates.

## Verification

The release includes unit failure tests and a disposable PostgreSQL 17 integration
job. Tests exercise corrupted/truncated data, bounds, interrupted upload, typed
restore, concurrent inserts, mismatched count/root, unauthorized callers, replay,
receipt conflict and unchanged current prices/inventory. Deployment and production
receipts must be recorded separately; passing CI alone is not live verification.

R2 browser CSP now recognizes either approved-media delivery or reference-cache
delivery. Independent delivery switches must not emit URLs that CSP blocks.

## Current limitations

R2 history archival is not live-price-cache delivery or a user-facing historical
chart API. Those remain separate unfinished work. Broad provider artwork caching
is still gated by source permission evidence. Missing source images cannot be
recovered simply by moving existing images to R2.

The 17:39 UTC coverage receipt recorded 42,482 priced physical references out of
67,065 (63.34%), including clearly labelled guides. All card references total
69,545, of which 2,480 are digital/non-resale records. The 90% user target and the
existing 95% software target are not met. Missing mappings, exact quotes and
permitted source access must be addressed without invented values.

A live one-image n8n signed-bridge test succeeded at 20:19 UTC and increased
verified approved-media mirrors from 2 to 3. The one-shot flag was reset. Recurring
DR94 activation remains off pending persistent-workflow review and DR90 failure
routing. This release does not claim a full artwork migration.
