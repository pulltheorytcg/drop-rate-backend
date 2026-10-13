# Large-batch coverage receipt recovery — 13 October 2026

## Failure observed
During the 1,585-reference Japanese Fusion World multi-set refresh, revision 12 `REFERENCE_PRICES` finished at 14:40:30 UTC, persisted **297** new source-qualified regional guide rows, and `CARDMARKET_VALUES` finished at 14:40:54 UTC. But the subsequent 73,417-reference `CATALOGUE_COVERAGE` full aggregation timed out at 14:41:18 UTC under the ordinary backend 15-second statement/query budget. Its last receipt was from **before** the source refresh and showed 33,096 instead of 33,393 priced/guided cards. Direct Supabase queries and per-set source receipts confirmed the real 297-card price gain; Store Prices/ownership were unchanged.

## Surgical repair (what/why/connections)
- Existing private maintenance-only `record_coverage` now sets a **transaction-local PostgreSQL statement_timeout of 45 seconds** and an explicit 50-second asyncpg client timeout for the full coverage aggregation. All regular user/browser query limits remain unchanged. Local means this special allowance cannot persist on pooled sessions or affect other requests.
- Add `coverage_lags_pricing(latest)` to the existing maintenance worker: if a **completed** reference/sealed/Cardmarket/canonical valuation job began later than the most recent completed coverage receipt, retry **coverage only**, without re-running/charging providers or repricing stock.
- The same existing 5-minute maintenance loop, advisory lock, admin context, PostgreSQL source-of-truth receipt and RLS remain. No new service, schedule, n8n automation, plugin, database migration or provider.

## What could fail
Slow/failed aggregation will still fail within 45 seconds and log an exception; the next existing maintenance tick tries again rather than hiding a stale receipt. If the database is unhealthy, do not endlessly issue external source refreshes; leave the completed source receipts intact. A full catalogue identity/ownership/payout mutation is not permitted here.

## Tests and acceptance
- Unit tests prove PostgreSQL timeout is locally scoped and client fetch limit explicit, retry occurs only when a completed price job has a newer timestamp than the last coverage report, and a successful later coverage receipt suppresses further retries. Already-RUNNING source jobs do not trigger a false fresh coverage assertion.
- Exact-head full Python/UI and real PostgreSQL source consistency CI.
- Production: Railway terminal SUCCESS/readiness; new `CATALOGUE_COVERAGE` receipt must show **69,538 cards, 33,393 priced/guided, 36,145 missing** and `store_price_updates=0` without generating a second revision-12 source-refresh job.
- Revert the PR for rollback. No data rollback, immutable prices remain.

This is a separate reliability repair after market Batch 02. It **does not** itself create new prices and must not be counted as another 297-card backfill.
