# 10 November 2026 — Production Supabase Pro capacity and isolated Tier 1 R2 audit

## Task, ownership and scope
Founder-approved continuation of the existing Supabase Pro backup/capacity and Tier 1 artwork verification work (PRs #1049, #1050, #1053). Implementation owner: this ChatGPT task, **not** a concurrent D1-migration workstream. No new market data source, storefront publication, R2 import, price mutation or Supabase exit.

## WHY / WHAT / CONNECTIONS
1. Pro database capacity is blocked by the old default 500 MB Free setting, although Supabase organisation `nqfcumedzjhmnjinmyit` reports plan `pro`. The established FastAPI `database_capacity` check accepts `DROP_RATE_SUPABASE_PLAN=pro`; it retains 8,000,000,000-byte included-limit, 7,000,000,000-byte bulk pause and 7,500,000,000-byte urgent threshold. Database remains source of truth.
2. An isolated Railway **single-run** service `tier1-r2-readonly-audit-20261110` (ID `c0f61c4e-3a3a-459e-bcb8-ff10ff47824c`) should read at most 100 approved or Shopify-published Tier 1 physical CARD/SEALED inventory items, through read-only Postgres transactions and R2 GET/HEAD. It uses only existing credential **references** from the existing `r2-quote-backup-once-20261103` service, never raw tokens in GitHub, with a reviewed exact repository SHA and a subprocess hard timeout of 180 seconds. The audit deliberately cannot establish visual identity or copyright rights from bytes alone.
3. The live API starts background catalogue, R2 media and price jobs on startup. Enabling Pro on the API with active refresh loops would start or unlock automatic writes. Therefore **hold** automated catalogue maintenance and R2 reference-media import before enabling the Pro runtime option. Keep existing background commerce/order reconciliation, customers and ledger unchanged. A standalone operations monitor may safely change to Pro for read-only capacity reporting; it does not run catalogue imports. Do not re-enable refreshes until a separate approved batch and dry-run.
4. Price/artwork UI changes require separately verified, exact-identity/source-rights repairs followed by R2/SQL cache delivery and app readback; audit or capacity alone does not update missing images or values.

## Evidence BEFORE any production change
- Supabase Management API read-only backup inventory workflow completed successfully: [GitHub Actions run 42873462449](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42873462449), checked main `02859aac9734b8a7bd61196475b83376dfb8f112`, eight COMPLETED backups, latest `2026-11-10T07:19:02.684Z`. **RESTORE NOT TESTED; R2 OBJECTS NOT INCLUDED**.
- Supabase project `ozrxenrdladkooixutmm` healthy; organisation subscribed to Pro as read from connected API.
- Read-only PostgreSQL at `2026-11-10T18:23:47Z`: 428,133,523 bytes, `default_transaction_read_only=off`. Current Free guard refuses bulk jobs (production log 18:24 UTC), as expected before activation.
- Production API `6aa92310-153f-4fc9-9e22-dc338282605b`, operations monitor `4307b725-08be-47fd-b85f-b8617a785d31`. Do **not** alter startup commands, cron schedules, price/provider quotas, owners, payments or archived service `7f97fa17-3975-4d76-8313-dd3089a746e4`.
- The temporary Railway service is **staged only** as of preflight, with no source/startup/variables/deployment yet. The R2 script includes the RLS fix merged in #1053; a previous, older attempt returned **zero rows** and is not a successful verification.

## Required release/test sequence
A. This BUILD_STATUS entry must be merged before making the temporary Railway service live.
B. Stage exact-SHA `02859aac9734b8a7bd61196475b83376dfb8f112` source, approved `PYTHONPATH=backend python -m scripts.tier1_r2_media_bytecheck --limit 100` command enclosed in a **hard 180-second Python subprocess timeout**; restart NEVER, no cron, zero volumes and zero public domains; resource limits bounded to ≤1 vCPU and ≤1 GB. Use Railway cross-service references for `TCG_DATABASE_URL`, `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID`, and `TCG_OBJECT_STORE_*` from the existing backup service. Inspect whole staged patch; commit only if it changes the temporary service.
C. Check deployment stdout for `examined`, per-game counts, verifiable bytes and distinct failure codes. Validate exactly ≤100, JSON receipt and exit code. A green deploy with zero rows is **failure**; do not equate mirror metadata to actual R2 verification. Save SHA/receipt and tear down the temporary service without touching the backup/archive workers.
D. Operations monitor: stage `DROP_RATE_SUPABASE_PLAN=pro` only, verify no other production patch and commit safely. Read logs for plan/limit/remaining/healthy.
E. API: before Pro activation, prevent automatic provider data refresh/write loops, including `TCG_CATALOGUE_DAILY_REFRESH_ENABLED`, `TCG_R2_REFERENCE_CACHE_WORKER_ENABLED` and `TCG_R2_FIRST_IMPORT_SOURCES`. Only after checking all enabled startup tasks, use minimal reversible flags; configure Pro and deploy the API; verify app readiness and log `database_plan=pro`. If safe isolation is impossible, leave API untouched, and report the exact blocker. Do not weaken RLS, ownership or price semantics.
F. Prepare read-only, bounded pricing INSERT/UPDATE/SKIP preview with 20 examples; no market-value or media writes absent separate founder approval and a suitable restore test.

## Failure points and rollback
- Bad service source, broken credential references, runtime/budget overrun, RLS visibility, unsafe GET fallbacks: stop with nonzero, do not retry unboundedly.
- User seeing missing images after successful audit: separate image-source rights, exact-print match, approved physical slab photo (for graded), SQL/R2 updates and UI readback remain required.
- Pro change accidentally starting a job: revert guard flag to `free` and disable the offending maintenance task without altering customer-facing API routes; verify monitor/API state and record all actual effects. Never auto-resume an archived one-shot.
- Database backups here provide recent recovery inventory, not an independently restored database. Do not conduct production restore; future restoration should be rehearsed in a separate project.
- Service cleanup requires verifying no attached volume or domain and that audit stdout is recorded, then delete this specific ephemeral service in production.

### Railway staged-only creation limitation
The first staged service was cancelled *before any deploy* because Railway rejected a staged start-command update while the service existed only in a pending patch (error `Service Instance not found`). The replacement service above is staged as an **empty service only**. After merging the BUILD_STATUS entry, commit its empty creation (no source, no variables, no runnable workload), then stage the entire source+command+limits+credential references on the now-existing idle service, inspect the patch and commit precisely that isolated audit workload.

## Verified first audit receipt — 10 November 2026

**The one-shot job completed and its temporary service has been deleted.** Receipt was posted to [PR #1056 conversation](https://github.com/pulltheorytcg/drop-rate-backend/pull/1056) before cleanup. First attempt `950a4960-46e6-41cb-a41d-54fac74db405` failed on network-unreachable; enabling IPv6 egress solely for the isolated service fixed the connection. Successful deployment `bc923f69-c572-4b1a-89e3-819d4b8a37e9` completed at 18:41:54 UTC. **100 examined**, **90 R2 byte/SHA/size/pixel checks passed but visual identity remains unreviewed**; **5 no approved asset, 4 no mirror record, 1 too small**. 88 unique mirror keys examined; five physical items shared a key (not automatically an error). Audit cursor was returned with `more_available=true`; do not imply 505/505 coverage. No SQL or R2 writes.

### Revised production activation: preserve archives and prior flags

Do **not** disable the entire `TCG_CATALOGUE_DAILY_REFRESH_ENABLED` loop: that loop also runs archival and backlog checks. Instead use the reviewed **reversible operator hold** introduced in this PR:

- Live API `6aa92310-153f-4fc9-9e22-dc338282605b`: stage `DROP_RATE_SUPABASE_PLAN=pro` and `DROP_RATE_CATALOGUE_BULK_HOLD=true` **together**. The capacity report then shows Pro's included 8 GB and headroom but returns `BULK_REFRESH_DEFERRED_OPERATOR_HOLD`, allowing zero new bulk price/image writes.
- The same flag suppresses independent startup of `r2_first_import.run_loop` and `run_live_market_refresh` without resetting or losing their configured source lists. Normal Shopify/order work and daily archive/backlog checks remain configured. The mirror worker continues its existing lock/preflight but receives `refresh_allowed=false`.
- Existing operations monitor `4307b725-08be-47fd-b85f-b8617a785d31` was updated with `DROP_RATE_SUPABASE_PLAN=pro` only; its scheduled log readback must still prove it uses the newly deployed code and reports the actual Pro limit.
- An invalid bulk-hold setting fails closed; unset/false has the original semantics. At 7 GB pause and 7.5 GB urgent, capacity urgency still overrides manual hold. Do not remove operator hold until sources, provider rate limits, market-value rules and exact preview have passed review.
- Live application health, monitor log lines, and new deployment IDs **remain required evidence**. A successful CI check alone does not mean these API settings have been activated.

**Pricing preview:** [the read-only SELECT](../audits/2026-11-10_tier1_pro_sold_dryrun_select.sql) and [20-example report](../audits/2026-11-10_tier1_pro_sold_dryrun.md) verified 505 physical items, 98 with any source-constrained recent UK sold match, 33 with 3+, **0 INSERT / 0 UPDATE / 505 SKIP** under narrow recency/condition/grade rules. Old Trawl API sales are not an official Browse API sold feed. No price or artwork mutations.
