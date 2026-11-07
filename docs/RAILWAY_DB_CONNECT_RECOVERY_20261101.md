# Railway/Supabase fresh-connection failures — 1 November 2026

## Live evidence (UTC)

The existing `drop-rate-api-live` deployment remained healthy while its
replacement failed twice on commit `b7e7a3b3` (catalogue-filter hotfix #847):

- `b46202b1`: the code built and all 8,646 pre-deploy Python tests passed,
  but `stripe_financial_sandbox_selftest.py` timed out opening a **new**
  PostgreSQL connection. It was correctly rejected by the release gate.
- `bae1fe9e`: the full pre-deploy suite, sandbox checks, and evidence probe
  passed. Uvicorn then failed to initialize its asyncpg pool on another new
  connection timeout, so Railway did not promote the replacement.
- Hourly payout worker `cc72b6d8` failed on a `TimeoutError` at
  `PAYOUT_SCHEDULER_DB_CONNECT_START`, before beginning a financial run.
- The independent 30-minute operations monitor `af08ef70` failed its
  Shopify reconciliation step with `TimeoutError`; other checks were green.
  A successful monitor run at 23:31 UTC demonstrates this is intermittent.

Supabase still identified the project as `ACTIVE_HEALTHY`. A live read-only
database check found seven idle and one active client connection at one
checkpoint, so saturation is not established. Subsequent new SQL sessions
also timed out intermittently, then recovered. Railway DNS/network-flow
telemetry repeatedly showed the project's direct, IPv6-only PostgreSQL
endpoint on port 5432. This supports a connection-path incident; it does not
prove whether the fault lies inside the source, destination or their route.

The earlier API deployment `5c3082cd` is unrelated: an application test
assertion failed and correctly blocked release. Do not disable tests, payment
gates or health checks to treat these distinct causes as one problem.

## Safeguard added in this follow-up

Retry **only** transient PostgreSQL connect failures (socket errors,
connect timeout, server connection failure or `CannotConnectNowError`),
with at most four attempts separated by 1, 2 and 4 seconds.

Applied to live API pool startup, hourly payout worker, Shopify reconciliation
database setup and the financial sandbox's database setup. The API pool's
per-attempt connection timeout is 15 seconds. Authentication failures and
SQL errors are not retryable; every original role, privilege, valuation,
payment and readiness check still executes and fails closed if unavailable.
No secret, role, RLS rule, schema, payment request or production data changes.

## Network follow-up

Supabase documents the direct database host as IPv6-only without the paid
IPv4 add-on, and its **session-mode** pooler as the supported IPv4 alternative
for persistent backend clients:

https://supabase.com/docs/guides/database/connecting-to-postgres

If fresh direct connections continue to time out after the bounded retries,
obtain the project's **exact Session pooler connection string** through the
Supabase Dashboard `Connect` dialog and set the existing `TCG_DATABASE_URL`
securely in the corresponding Railway service(s). Do not paste the secret in
issues, logs or chats, or infer the region's hostname. The restricted API
role's pooler connectivity, role search path, prepared statement behavior and
full sandbox checks must be verified before broad rollout. Railway OAuth
connections currently expose variable names, not the underlying secret value;
no unattended credential rewrite is authorized here.

## Release gates

1. GitHub backend CI green; focused bounded-retry tests green.
2. A new Railway production deployment must pass the **existing** finance
   and full-test pre-deploy commands and become `SUCCESS`.
3. Public `/health/ready` must report database connected/writable.
4. Human-authenticated filtered catalogue searches must be fast and return
   correct items, prices and owner scope.
5. Observe at least one successful subsequent payout and operations-monitor
   cron run; no payment actions should be triggered just for verification.

No connection-path remediation is claimed successful until those checks pass.
