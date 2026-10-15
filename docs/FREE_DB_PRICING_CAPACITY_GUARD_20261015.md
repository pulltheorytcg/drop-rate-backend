# Free Supabase capacity guard for catalogue pricing — 15 October 2026

## 1. What we're building and why

The Drop Rate production database is on Supabase **Free** with a stated **500 MB database-size allowance**. The verified 14 October archive reduced the database to 321,334,419 bytes. After one 15 October pricing job, it has already grown to **405,499,027 bytes**, including **50,378 genuine new reference-market-history rows** (~77 MB with indexes). Running another full daily reference import without verified archival could put production back into read-only mode.

This change adds a **read-only quota check** to the existing scheduled operations monitor and a **fail-closed preflight** to the existing daily catalogue-import worker. It adds no service, database table, paid plan or archive mutation.

## 2. Connections

- Existing Railway `drop-rate-api` operations-monitor cron → `backend/scripts/check_database_capacity.py` → `SELECT pg_database_size(current_database()), current_setting('default_transaction_read_only')`.
- Existing Railway `drop-rate-api-live` daily maintenance → same pure `assess_capacity` rules through its authorized `user_connection`, **before** catalogue/pricing imports.
- If DB **<400,000,000 bytes** and write mode is `off`: normal jobs run unchanged.
- At **≥400,000,000 bytes**: operations monitor emits `DATABASE_CAPACITY_WARNING`. Daily catalogue sync/reference-price/bulk pricing maintenance is temporarily **DEFERRED** to protect existing data; the job takes no writes and logs a structured reason. Existing customer-facing cached prices, search, inventory, Shopify and finance are not altered.
- At **≥450,000,000 bytes** or DB read-only: the monitor emits `DATABASE_CAPACITY_URGENT` and fails the existing cron execution (nonzero) to surface the incident. Daily imports remain deferred.
- If capacity evidence is missing/invalid, fail closed. Never assume success from a Supabase `ACTIVE_HEALTHY` label or a successful read-only SELECT.
- After a **fully verified** archival cleanup reduces the database below the safe threshold, the next normal worker tick automatically resumes.

A 500 MB limit here refers to the *current Free environment*. If the organisation changes plan, review the thresholds before continuing. This intentionally sacrifices a few daily freshness updates rather than risking a database outage; normal 7-day guide validity is unchanged and can expire if archival is delayed.

## 3. Failure points

Monitoring process cannot connect, has no `TCG_DATABASE_URL`, receives an invalid size/mode, or hits a query timeout → reports `DATABASE_CAPACITY_PROBE_FAILED` and nonzero exit; no deletion or retry loop. Monitor is read-only. A growing database can still reach quota through **other** routes such as user uploads; this is a bulk-catalogue safety gate, not a universal quota guarantee.

The safe archive remains separate and intentionally unimplemented here: follow `docs/REFERENCE_HISTORY_ARCHIVE_RUNBOOK.md` with original IDs/fields, typed disposable restore, Drive account ownership verification, verified upload/download hash and atomic database digest before reclaiming **only archived history**. Do not truncate or purge evidence to resolve a capacity warning.

## 4. Verification

`tests/test_database_capacity_guard.py` checks thresholds at exact byte boundaries, Free quota excess, active database read-only, invalid inputs, read-only SQL, source worker early exit with advisory-lock release, no provider/price/stock writes and cron failure signalling. Existing `test_sealed_only_refresh_updates_the_coverage_receipt` uses an explicitly safe synthetic quota to preserve normal worker coverage. CI/backend and production readback remain release gates.

No price data changes, no automatic archive, no paid services and no scraping are performed. The return to normal is confirmed by actual database capacity and a successful next scheduled refresh.
