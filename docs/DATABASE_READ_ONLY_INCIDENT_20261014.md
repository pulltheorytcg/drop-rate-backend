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

The recommended immediate capacity option is Supabase Pro, publicly listed from **USD $25/month**, including 8 GB disk per project and compute credit for one Micro instance. Actual organization checkout, taxes, other projects and usage must be reviewed. Keep the spend cap enabled. The operating manual's Section 0 requires founder approval for this new commercial dependency.

A free-plan alternative needs an explicit archival/retention decision, a durable verified export and restore procedure, then approved removal of historical records and space reclamation. No such deletion is authorized or performed here. Existing price history is immutable evidence; do not truncate it to clear the alert.

After capacity is approved and changed:

1. Verify the organization plan/capacity and `default_transaction_read_only=off` on a new connection. Do not force read-write mode to work around the allowance.
2. Apply the reviewed trigger migration after its real PostgreSQL CI check passes; verify the installed function and existing history count.
3. Merge/deploy the readiness fix only after all required CI checks pass and the database is writable. Verify the exact Railway deployment succeeds and `/health/ready` returns 200.
4. Verify a fresh operations-monitor cron run completes, maintenance receipts advance and new read-only errors cease. Check inventory ownership/status/Store Price fingerprint before and after. Do not run a money-transfer operation as a health test.
5. Resume the bounded pricing-source evaluation. The Flipzi account is verified with 500 free units, but `FLIPZI_API_KEY` was absent from `drop-rate-api-live` at the last check. Free evaluation quotes still require commercial permission before Seller Hub use.

## Sources

- [Supabase database size and read-only mode](https://supabase.com/docs/guides/platform/database-size)
- [Supabase pricing](https://supabase.com/pricing)
- Railway deployment/runtime logs and read-only Supabase SQL inspected in this session.

## Validation

Focused HTTP tests cover writable, read-only, unavailable and invalid readiness responses, plus independent liveness. The existing disposable PostgreSQL integration job is extended to exercise all three history triggers, preserve original history/current-cache metadata, retain substantive evidence changes and test real session/transaction read-only modes. Final test/CI receipts are recorded in the pull request; no production recovery is claimed until the steps above pass.
