# Archive backlog monitoring (16 October 2026)

## What is being built and why

Drop Rate has a **daily 04:00 Europe/London** *ChatGPT task* for full verified cold archival and a separate **07:00 UK** conditional watch for missed archives. The existing Railway backend does **not** have an independently authorised Google Drive uploader, so simply changing a schedule cannot claim unattended production archiving. As of 16 October, Supabase retains **50,378 unarchived history rows**, approximately **77 MB**, with ~405.5 MB / 500 MB database bytes; the **400 MB bulk pricing guard correctly defers** even the now-weekly Monday market refresh.

This release adds a **zero-write, once-per-day** overdue-history diagnostic to the existing Railway `drop-rate-api-live` FastAPI catalogue worker. It answers: did price history that existed before the *eligible* 04:00 UK window remain live after 07:00 UK? It does **not** itself back up, export, certify, purge or unpause pricing.

## Connections and security

- **Railway:** Existing `backend/app/catalogue_maintenance.py::run_loop`; no new service, network endpoint, cron, token, secret or subscription. Only the pre-existing admin-scoped catalogue worker runs this check, independent of Shopify and unaffected by the existing bulk price capacity guard.
- **Supabase:** `tcg.reference_market_history` only. The read is `SELECT count(*), min(recorded_at), max(recorded_at)` through the existing authenticated `user_connection` and `require_platform_admin` with RLS. It does **not** access the admin-only archive receipt table from an unauthorised context or circumvent `tcg_api` restrictions.
- **Google Drive:** The existing `dropratetcg@gmail.com` private folder is untouched. Correct account, complete NDJSON archive, typed restore, actual upload/download/checksum verification and `tcg.archive_verified_reference_history` are strictly the responsibility of the separately scheduled archival operation and its reviewed runbook.
- **ChatGPT:** Separate newly enabled *Drop Rate Archive Watch* checks actual Supabase archive receipts and original Drive metadata after the 04:00 slot, and can notify when verification is missing. Notifications still depend on the user's app settings.

## Failure points, tests and expected operation

- Before the initial Saturday **17 October 2026 07:00 BST** grace cutoff, no archive-missed warning is logged. From 07:00, if the oldest unarchived `recorded_at` predates or equals today's 04:00 London archive boundary, log one `CATALOGUE_ARCHIVE_BACKLOG_OVERDUE` warning per observed day. When no such history remains, log a diagnostic informational result. Do **not** mistake a clear live table for proof that Drive backup succeeded.
- The London IANA timezone handles DST; check both October GMT transition and regular BST days. 07:00 is three hours after the 04:00 scheduled task.
- If the diagnostic cannot authenticate or read its own protected table, log `CATALOGUE_ARCHIVE_BACKLOG_CHECK_FAILED` with the exception **class only** (no credentials or SQL contents), retry on the next normal worker tick, and leave all data intact.
- This is a read-only metric executed at most once per eligible London-day window on the running service, not another provider importer or storage writer. Other nightly sources and Shopify processing remain separate.
- Tests: exact first-run and DST boundary, negative/corrupt evidence fail-closed, admin/RLS-scoped SQL with no writes, missed-history log, probe failure isolation and unchanged worker path. Full repo CI and Railway predeploy/readiness required.

## Deployment acceptance

Verify the exact merged commit on Railway and `/health/ready`, the number and checksum of physical inventory/owners/Store Prices, `reference_market_history` rows and database capacity before/after. The fact that the *monitor* is live must **not** be described as successful native daily archiving. True unattended Google Drive export cannot be installed into the Railway worker until a secure permitted uploader identity/credential is explicitly configured. Do not create a paid bucket or back up into the same 500 MB database as a substitute.
