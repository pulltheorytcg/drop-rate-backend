# Verified price-history archival to Google Drive

The founder approved the free recovery route and Google Drive storage on
14 October 2026. Preserve every archived field and original timestamp; only
`tcg.reference_market_history` is eligible for this procedure. Current quotes,
reference cards, physical inventory, owners, Store Prices and audit events are
outside its removal scope.

Required storage account: **dropratetcg@gmail.com** (Drop Rate).
Private archive folder: https://drive.google.com/drive/folders/1NhFIsWesgxlf059UMdx65ps9kFMqQeO9

Before every upload, verify the selected Drive connection's profile email and the
destination folder's owner/permissions. Use the Drop Rate account explicitly;
neither a default connection nor a folder named Drop Rate establishes ownership.
Keep the folder and files private. If the account differs, stop before uploading.

The 14 October archive was relocated to this account with a complete downloaded
SHA-256 and ZIP CRC check at **17:54:22 UTC**. The archive registry now points to
file `1tvMgxVs480slYLTyAagR1nZXFxAokV9g`; its original count, content digest and
restore verification remain unchanged. See the [incident record](DATABASE_READ_ONLY_INCIDENT_20261014.md).

## Archive before reclamation

1. Record a cutoff, exact row count, table schema, database/table sizes and the
   inventory owner/status/Store Price fingerprint. Inspect dependencies. Never
   infer write health from project ACTIVE_HEALTHY or a successful SELECT.
2. Export complete `row_to_json(history)` records as newline-delimited UTF-8 JSON,
   including IDs, quote JSON, quote digest and timestamps. Use bounded indexed
   pages, a fixed cutoff, and explicit ordering. No server-side file reads or OS
   commands are permitted. Keep original byte-level SHA-256 per chunk.
3. For connector transport, pgcrypto can compress the text with
   `pgp_sym_encrypt(data,'drop-rate-archive-transport-v1',
   'compress-algo=1,compress-level=6,cipher-algo=aes256')`. This public constant
   is **not a secret or security control**. `verify_reference_history_export.py`
   decrypts locally, verifies the database checksum/count/schema/IDs, and writes
   ordinary `.ndjson.gz` chunks and manifests. Do not store transport blobs in
   Git or mistake them for a completed backup.
4. Reject duplicate IDs across chunks and require the complete database count.
   Define the full content root as SHA-256 of the concatenated lowercase hex
   SHA-256 of each original JSON row **without its newline**, ordered by UUID.
   This hashes every field, not only the quote or identity.
5. Restore every chunk into disposable PostgreSQL with the same column types,
   primary key, unique key and CHECK constraints. Compare every restored row's
   canonical JSON digest with the original and verify every quote digest.
   `tools/history-archive-verify/restore.mjs` uses pinned local PGlite; production
   behavior and archive guards are separately tested in native PostgreSQL 17 CI.
   `--watch` can restore finished chunks while export continues; the final
   `export-complete.json` count must match before a receipt is issued.
6. Package only verified gzip chunks, their manifests, schema, restore tooling
   and instructions. Upload to the private Drive folder, read metadata, download
   the actual uploaded bytes, and compare the complete package SHA-256. Keep
   the manifest and restore receipt with the archive. Do not proceed if upload,
   download, quota, checksum or restoration fails. Never make the files public.

## Reclaim storage safely

The current price caches already retain the latest source quotes. The approved
free recovery archives all history through the verified cutoff and starts the
live history table afresh, leaving the largest capacity margin. Archived history
is retrievable from Drive; there is no automatic in-app reader for cold archives.

1. Ensure the FX-only trigger fix and archive-registry migration passed CI.
   The registry migration only creates admin-only metadata and a SECURITY INVOKER
   helper; applying it does not remove history.
2. During the quota incident, Supabase documents a **session/transaction-scoped**
   read-write override to reduce storage. Do not change a role or the global
   configuration to bypass the quota. Use `SET TRANSACTION READ WRITE` before
   queries in the maintenance transaction, and bounded lock/statement timeouts.
   For the full-table content hash, EXPLAIN the aggregate before execution. On
   PostgreSQL 17, `SET LOCAL enable_presorted_aggregate=off` avoids a slow random
   UUID index scan; `SET LOCAL work_mem='64MB'` was used for the verified recovery.
   These transaction-local planner settings preserve the exact ordered checksum.
   If the connector times out, verify that the transaction rolled back and no
   receipt exists before retrying. Never replace the content guard with a count.
3. Only after durable verification, call
   `tcg.archive_verified_reference_history` as the admin with the exact count,
   cutoff, content root, observed Drive file ID/URL, package SHA-256 and restore
   verification timestamp. The helper locks the history table, hashes every
   current field, and rejects any mismatch or unarchived new record. A stale
   backup leaves all rows untouched. It uses transactional TRUNCATE without
   CASCADE to reclaim the verified history's heap/index storage; original table
   schema, triggers, grants and RLS remain. It records the external archive in
   `tcg.reference_history_archives` in the same transaction.
4. Verify actual committed database size, the archive receipt, history state and
   unchanged current-cache/inventory fingerprints. Wait for a fresh connection
   to report normal write mode; a session override alone is not recovery.
5. Merge/deploy readiness only once the database is writable. Verify a fresh
   successful operations-monitor run and advancing maintenance receipts. Never
   send payouts or publish stock as a health test.

## Ongoing free-plan operation

The FX-fetch guard reduces redundant snapshots, but does not cap real changes.
Check size regularly and archive again before reaching the 500 MB allowance.
An archive task must verify its actual Drive upload and restoration on each run;
it must not remove records merely because they are old or a previous archive
exists. Concurrent new history causes the full-content guard to reject cleanup:
finish/export the new rows and reverify, or leave the database untouched.
Current-price tables and other database growth must also be monitored. This is
a free recovery route, not a promise that the database can grow indefinitely.

## Restore

Download and verify the package checksum, extract it, then use the included
restore tool against disposable PostgreSQL first. For native PostgreSQL, load
each JSON object with `json_populate_record(null::tcg.reference_market_history,
record::json)` using a **client** stream. Preserve IDs, quote JSON and timestamps;
reject a conflicting ID with different fields. Do not restore the whole archive
to the 500 MB production database: that recreates the capacity incident. Use a
separate local database for investigation or selectively restore required rows
after checking space. No additional paid service is required for local restore.
