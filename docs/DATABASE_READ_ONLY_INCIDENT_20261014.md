# Database capacity incident — 14 October 2026

## Verified incident

Read-only checks at 12:21–12:25 UTC / 13:21–13:25 London found:

- Railway `drop-rate-api` is the existing **operations monitor**, running `run_operations_monitor.py` on a 30-minute cron. Deployment `77bf7e3b-527c-4a3e-9be7-cb7f17354f28` is CRASHED. Its payout-heartbeat, Shopify reconciliation and outbox checks fail with `ReadOnlySQLTransactionError`.
- `drop-rate-api-live` remains running on successful deployment `55b50ac6-129b-4eb7-b8af-aed5e64e2910`, pricing revision 22. Its Shopify maintenance and eBay refresh also report the same database write error. Reads succeeding does not make seller writes or background jobs healthy.
- Supabase organization `nqfcumedzjhmnjinmyit` is on the **free** plan. Project `ozrxenrdladkooixutmm` reports ACTIVE_HEALTHY, but PostgreSQL has `default_transaction_read_only=on`, source `configuration file`, and is not a recovery replica.
- Database size: **1,510,870,163 bytes**. Free database allowance: **500 MB**. This is a storage-capacity incident, not a Flipzi integration failure.
- `tcg.reference_market_history`: **1,189,642,240 bytes**, 724,207 estimated live rows and four dead rows. Heap 977,068,032 bytes; indexes 212,271,104 bytes. A routine vacuum will not reclaim the roughly 1 GB required to fit the free allowance.
- The old `/health/ready` returned HTTP 200 with `database=connected` because it only ran `SELECT 1`. `/api/v1/public-config` also returned 200. Neither proved writes were available.

No production data was removed, no database setting was overridden, and no capacity upgrade or new subscription was activated during this investigation.

## Prepared fixes

1. **Write-aware readiness.** `/health/ready` checks recovery state, the current transaction mode and the session default mode. A readable but read-only database returns HTTP 503 with `database=read_only`. Connection errors remain sanitised. `/health/live` remains independent of the database. This checks configuration, not every table privilege or every possible future write failure.
2. **Stop FX-fetch-only history growth.** The existing history trigger currently hashes the entire quote, including `fx_retrieved_at`. Fetching an unchanged FX publication can therefore duplicate the same price evidence. In a deterministic 12-reference diagnostic sample, each identity had 32 history rows but only 9–10 distinct quote payloads after removing that one field. This sample is not an estimate of recoverable bytes across the whole database.
3. Migration `20261014122734_reference_history_fx_refresh_guard.sql` skips a new history insert only for an UPDATE with the same reference identity, GBP range and pricing date, when quote arrays differ solely in top-level `fx_retrieved_at`. The current cache still receives the newest retrieval time. Source observation dates, FX publication dates/rates, prices, identity, finish and eligibility changes continue to be evidence changes. Existing history rows and privileges are preserved; no historical cleanup/backfill or index rewrite is included.

These fixes are prepared for review, **not deployed/applied during read-only mode**. Merging a write-aware health check before database recovery would cause Railway's readiness gate to reject the deployment. Preventing future duplicates does not shrink existing history or remove the current capacity block.

## Recovery decision and order

On 14 October 2026 the founder approved the **free archive route using Google Drive**. No paid upgrade is authorized. All 722,511 historical records through 07:01:20.941369 UTC are being exported with original fields and timestamps. A first 10,000-row file passed upload/download SHA-256 verification and complete typed PostgreSQL restoration. Full archival, cleanup and runtime recovery are still in progress at this checkpoint.

Current prices already retain their latest source quote arrays. Once the complete durable archive is verified, the admin-only archive helper will require an exact full-table content checksum under a lock, record the private Drive receipt, and reclaim the archived history storage in one transaction. New or changed rows invalidate the receipt and block cleanup. Current prices, cards, inventory and audit events are excluded. See [the reviewed archive runbook](REFERENCE_HISTORY_ARCHIVE_RUNBOOK.md).

After archival and space reclamation, verify actual committed size and write mode, apply the tested FX-only history guard, merge/deploy write-aware readiness, and verify a fresh successful operations-monitor run. Recheck current-price and owner/status/Store Price fingerprints. Resume bounded missing-price source evaluation only after recovery; the Flipzi key remains unconfirmed and free evaluation quotes do not imply commercial display permission.

## Sources

- [Supabase database size and read-only mode](https://supabase.com/docs/guides/platform/database-size)
- [Supabase pricing](https://supabase.com/pricing)
- Railway deployment/runtime logs and read-only Supabase SQL inspected in this session.

## Validation

Focused HTTP tests cover writable, read-only, unavailable and invalid readiness responses, plus independent liveness. The existing disposable PostgreSQL integration job is extended to exercise all three history triggers, preserve original history/current-cache metadata, retain substantive evidence changes and test real session/transaction read-only modes. Final test/CI receipts are recorded in the pull request; no production recovery is claimed until the steps above pass.
