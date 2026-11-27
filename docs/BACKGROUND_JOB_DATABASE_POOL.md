# Background-job database pool (DR-OPS-1)

## Incident

On 27 Nov 2026 in production (`drop-rate-api-live`, commit `4e12782c`), with
`DROP_RATE_CATALOGUE_BULK_HOLD=false`, refresh jobs acquired all five `tcg_api`
API-pool connections at startup (19:05:45 UTC) and held them. The last
statements on those connections were `pg_try_advisory_lock` and the capacity
check. Every DB-backed route hung:

- `/automation/control/heartbeat` and `/receipt` returned 499 after 15 s;
- `prepare-enrichment-worklist` returned 499 after 180 s.

Restoring the hold at 19:33 recovered the app. Full timeline:
`claude/Change-Log-2026-11-27.md`.

**Cause:** every background task started by the API lifespan shared the API
request pool:

- R2 prewarms and the R2-first import;
- the reference-image mirror;
- the Shopify waitlist sync;
- the daily catalogue and Shopify loops;
- the live eBay refresh;
- the catalogue bootstrap;
- linked-draft reconciliation.

Each lock-holding loop used `async with pool.acquire() as lock` to keep a session
advisory lock. That pinned one pooled connection idle for the whole pass,
including across provider HTTP, while the work took further connections. With
the hold lifted, those loops start together and exceed five connections.

## Design

`backend/app/job_database.py` gives all startup background tasks a
`JobDatabase`, which the lifespan stores at `app.state.job_db`:

| Part | Size | Purpose |
|---|---|---|
| API pool (`app.state.db_pool`) | `TCG_DB_POOL_MAX` (default 5) | API requests and readiness only. Startup jobs never receive it. |
| Job pool | `TCG_DB_JOB_POOL_MAX` (default 4, range 1–8), `min_size=0` | Short job reads, writes and receipts |
| Lock session | 1 connection | Holds every job session advisory lock |

- **Advisory locks:** `lock_session(pool)` is a one-line replacement for
  `pool.acquire() as lock`.
  - With a `JobDatabase`, the lock handle sends only `pg_try_advisory_lock` and
    `pg_advisory_unlock` to the shared session, and holds no pooled connection.
  - The lock keys and session-level semantics are unchanged, so replicas and
    overlapping deployments still exclude each other.
  - PostgreSQL session locks are re-entrant, so a per-process key set refuses
    a second local holder, exactly as a second pooled session was refused before.
  - Locks are released when the block exits, including on cancellation.
  - A lost lock session is logged as `JOB_LOCK_SESSION_LOST`, and the next pass
    re-acquires the lock.
  - A plain pool (scripts, n8n-triggered API routes, test fakes) keeps the
    previous behaviour exactly.
- **Converted lock sites:**
  - `catalogue_maintenance` (daily and Shopify passes)
  - `catalogue_r2_live` and `catalogue_r2_market` publishing
  - `live_market_refresh`
  - `r2_first_import`
  - `r2_reference_images` (its capacity check now uses a short lease)
  - `reference_history_archive`
- **Bounded waits:** job `acquire()` waits at most
  `TCG_DB_JOB_ACQUIRE_TIMEOUT_SECONDS` (default 30, range 1–300). Contention
  between jobs becomes an ordinary job failure, handled by the existing
  receipts, logs and next-tick retry. It never hangs indefinitely.
- **Capped concurrency:** linked-draft reconciliation runs at most
  `min(4, TCG_DB_JOB_POOL_MAX - 1)` at once, which leaves one job connection for
  the other loops.
- **Still held over HTTP:** Shopify publication keeps the connection it is given
  for the duration of the call, and takes its own advisory lock on it. In the
  background loop that connection now comes from the job pool, so it cannot
  starve the API. It is left as is because Shopify behaviour is out of scope.
- **Unchanged:** pricing rules, price authority, Store Prices, RLS
  (`user_connection` still sets `tcg.user_id` on every job transaction), Shopify,
  ownership, receipts, the bulk hold, the capacity guard, provider rate limits
  and cooldowns. Unknown values stay unavailable, never £0.

## Not covered

- **API-route work:** n8n-triggered API routes still run their work on the API
  pool. This includes `automation_commands` running R2-first, legacy scout,
  reference images and Shopify price reconciliation, and routes that call
  `publish_inventory_to_shopify` inside a transaction. These are request-scoped,
  not startup jobs. Moving them to the job pool is a separate change.
- **Other Railway services:** these connect independently and are unchanged:
  - `reference-pricing-batch`
  - `shopify-reconciliation-worker`
  - `drop-rate-payout-scheduler`
  - `drop-rate-n8n-e840`
  - the one-shot services

## Railway and connection budget

There is **no new Railway service**. The jobs still run inside `drop-rate-api-live`.

Server connections per API replica rise from 5 to at most
`TCG_DB_POOL_MAX + TCG_DB_JOB_POOL_MAX + 1`, which is 10 with the defaults. The
job pool opens no connections until a job needs one.

Read-only check on 27 Nov 2026:

- `max_connections` is 60;
- `tcg_api` has `rolconnlimit = -1` (no per-role limit);
- about 8 client sessions were open.

A deployment overlap, where two replicas each run full pools (2 × 10), fits
within that budget. The other services' own pools are not included in that
figure. In `pg_stat_activity`, connections are
labelled `drop-rate-api:<env>`, `drop-rate-jobs:<env>` and
`drop-rate-jobs:<env>:locks`.

## Verification

- **CI, real PostgreSQL:** `tests/job_pool_isolation_postgres.py`, run by
  `.github/workflows/job-pool-isolation.yml`, with the bulk hold set to `false`.
  - Runs the real `daily_pass` twice concurrently, with simulated slow
    providers and more connection hogs than the job pool holds.
  - Asserts that every API-pool `user_connection` request completes within 1 s.
  - Asserts that the lock session holds the daily lock and another replica
    cannot take it.
  - Asserts that job acquires time out rather than hang, and that only one pass
    ran, with an intact receipt.
  - Negative control: the same load on the API pool reproduces the starvation.
- **Unit tests:** `tests/test_job_database.py`.
- **Production, only after merge and deploy:**
  1. With the hold still `true`, deploy. Confirm `/health/ready` and that the
     three application names appear in `pg_stat_activity`.
  2. Lift `DROP_RATE_CATALOGUE_BULK_HOLD` for **one bounded batch**, with a small
     `TCG_CATALOGUE_PRICE_REFRESH_LIMIT`.
  3. During the run, show n8n heartbeats every 5 minutes and a signed-in
     catalogue request succeeding.
  4. Then restore the hold, or keep it lifted, according to the result.

## Rollback

Set `DROP_RATE_CATALOGUE_BULK_HOLD=true` on `drop-rate-api-live` and redeploy.
Reverting this code returns the jobs to the shared pool, which is safe only
while the hold stays on.
