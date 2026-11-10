# Supabase Pro capacity guard and completed-backup evidence — deployment review

**Priority:** unblock safe market-price and artwork catalogue maintenance. **This PR only adds code and a manual read-only backup verification workflow.** It does not initiate any ingestion, query external market providers, change Railway settings, or update inventory, media, prices, ownership, finance, Shopify, R2 or D1.

## What and why

`backend/app/database_capacity.py` previously hardcoded Free-plan 500 MB disk and a 400 MB bulk refresh pause. Production is **Supabase Pro**, verified through the connected organisation API on 10 Nov 2026, while the catalogue exceeds 400 MB. The old guard therefore suppresses fresh price coverage in a Pro database.

New settings:
- `DROP_RATE_SUPABASE_PLAN` unset or `free`: **existing** 500 MB / 400 MB pause / 450 MB urgent thresholds and original Free reason codes.
- `DROP_RATE_SUPABASE_PLAN=pro`: 8,000 MB included disk, conservative 7,000 MB pause / 7,500 MB urgent. Above this we require another explicit capacity/price review.
- Invalid plan or read-only PostgreSQL mode fails closed.
- The new `database_plan` and `database_limit_bytes` report fields make the active policy visible. The old `free_limit_bytes` report key is retained as an alias for the *effective* limit for existing log consumers; downstream consumers should switch to `database_limit_bytes`.

**Release rule:** Do NOT change the Railway configuration yet. Even if merged, the Free guard remains in force until the owner separately approves the production environment update.

## How to verify Supabase backup without dashboard clicks

Supabase Management API provides **GET** `/v1/projects/ozrxenrdladkooixutmm/database/backups` (requires `backups_read`, no write scope). A one-time workflow on first merge to main (then manual on demand), `.github/workflows/supabase-backup-evidence.yml`, invokes `tools/supabase_backup_inventory.py` with a protected `SUPABASE_ACCESS_TOKEN` GitHub Actions secret. It reports **only completed-backup count, latest completed timestamp and age**. Its failure path prints HTTP status/type, never an upstream body or a token. No recurring schedule, no automatic backup creation/restoration, no physical-DB writes and no Supabase credentials are committed.

A Pro entitlement alone is not accepted as proof of an actual completed backup. **This workflow has not yet produced a completed-backup receipt**. If the `SUPABASE_ACCESS_TOKEN` secret is missing, this fails closed; use a fine-grained token with `backups_read` only, kept in protected GitHub secrets. An OAuth-backed direct backup inventory tool was not exposed to this ChatGPT session.

### Existing backup restoration policy

Before *any* production catalogue write, confirm a completed timestamp from the read-only check and validate recovery runbook. Dashboard recovery via **Database > Backups** restores the whole database to a selected backup, with downtime and loss of later DB changes. Prefer restoring into a **separate project** for testing. Database backups do not restore R2 objects; maintain separate immutable R2 backup/version receipts. **Do not run restore as a test against production.**

References: https://supabase.com/docs/reference/api/v1-list-all-backups and https://supabase.com/docs/guides/platform/backups .

## What connects to what

- Existing FastAPI/Railway import and monitoring code calls `check_database_capacity()`, which still queries `pg_database_size(current_database())` and `default_transaction_read_only` before deciding to pause.
- PostgreSQL remains authoritative for price observations and inventory. Cloudflare R2 retains media and immutable publications. **D1 is not touched.**
- Optional read-only GitHub job calls only Supabase Management API, not the database API, and has no database write role.

## Failure testing

- No env: existing Free pause remains.
- Explicit Pro: current ~428 MB DB is allowed by capacity preflight, no automatic price write.
- Pro 7 GB/7.5 GB boundaries: refresh blocked; no unexpected paid growth.
- Database read-only: blocked even on Pro.
- Unknown plan: raises; refresh fails closed.
- Backup response with PENDING, FAILED, missing status, old timestamp, timezone-naive timestamp, HTTP error or missing secret: no verified backup reported.

Regression files: `tests/test_database_capacity_pro.py`, `tests/test_supabase_backup_inventory.py`. Run `python -m pytest -q tests/test_database_capacity_pro.py tests/test_supabase_backup_inventory.py` from repo root in the usual dependency-managed CI environment.

## Activation — **requires explicit founder approval**

After review/merge and backup receipt, change only the existing pricing/monitoring Railway service(s) that use this guard by setting `DROP_RATE_SUPABASE_PLAN=pro`. Verify deployment log reports `database_plan=pro`, a database limit of `8000000000` bytes, refresh allowed for the actual DB size, and no unbounded/bypassed provider rate limits. Observe a **bounded dry run** before any backfill; report exact INSERT/UPDATE/SKIP and 20 sample rows, then obtain separate permission for each write.

**Rollback**: set `DROP_RATE_SUPABASE_PLAN=free` (or remove it), redeploy the previously working version if needed, and verify it again reports the Free guard. Never lower or remove safeguards silently. No D1 or Supabase exit steps.
