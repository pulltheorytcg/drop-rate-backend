# Yu-Gi-Oh! — one-time Workers Paid D1 catch-up, 9 November 2026

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What / why

The user reports upgrading the Cloudflare Workers account to Paid and explicitly requests prompt completion of the Supabase exit. On 9 November, protected D1 read-only financial and operational parity tests that had failed with `DAILY_ROW_READ_LIMIT` ran successfully during the same UTC day; this is evidence the former Free hard read stop is no longer affecting those reads, although independent billing/subscription and monthly usage endpoints were not read. Cloudflare's official D1 Paid plan includes 25 billion rows read and 50 million rows written per month before usage charges; monthly usage and overages still require monitoring.

The **application**, independently of Cloudflare billing, had a hard Free-safe **8,000 new Yu-Gi-Oh D1 rows per UTC day**. The verified current Yu-Gi-Oh source is 45,419 R2 records; the new immutable generation last reported 8,000 staged, so a purely Free-era importer would require multiple daily windows despite the upgrade. This patch adds a one-time, strictly bounded **up to 40,000 additional rows** after the original receipt, only on `2026-11-09`, and only when a maintainer separately sets the repository Actions variable `DR_D1_PAID_CATCHUP_APPROVAL` to the exact approval marker. The workflow no longer hardcodes that approval; merging the PR by itself cannot authorise the extra 40,000-row supplement. It cannot run on any other UTC day. Original `DAILY_NEW_ROWS=8_000` remains intact for all other runs.

**No production API, Auth, ownership, finance, Market Value or Shopify route changes.** This advances only isolated Yu-Gi-Oh reference-catalogue D1 staging.

## Connections

Existing GitHub protected R2 source export (OIDC) → original provider/scope/source-content SHA and complete stable-key/identity/name-fold review → retained immutable D1 old generation → current immutable content-addressed D1 generation in `drop-rate-d1-real-yugioh-shadow` → exact prefix+full projection checksum → isolated partition activation only. This is NOT storefront serving or D1 financial authority.

Old `shadow_daily_write_budget` receipt (up to 8,000) stays immutable. Additional `shadow_paid_catchup_receipts` uses one unique `utc_day` and pins the verified `manifest_sha`, trusted `GITHUB_RUN_ID`, `start_rows` and exact `rows_limit` of at most 40,000. The supplementary receipt is written **before** any extra card inserts. If D1 crashes or a response is lost after partial inserts, only a GitHub rerun with the **same original run ID** can finish the reserved prefix; a new run ID cannot mint more paid rows that day or overwrite the receipt. Immutable original and new generation rows, source verification and rollback pointers remain untouched.

Potential extra inserts for the latest verified new generation: **37,419** rows, provided current live D1 prefix is still exactly 8,000 and source remains 45,419. This is an **expected target, not a post-run claim**. Updated protected job timeout 35 minutes to accommodate full checksum/readback; original 8k staging and concurrency group are preserved.

## Failure points

- Missing maintainer-set approval variable, wrong date or wrong approval text → no supplemental schema/rows; ordinary 8k/day control is retained.
- Wrong manifest, missing old source keys, changed non-name identity/rights, corrupt R2 part/source hash, changed name folds, unreviewed mass rename, unknown prior D1 generation → fail closed before new D1 inserts.
- Concurrent/replayed paid GitHub runs or a different trusted run ID → cannot consume the same reserved additional capacity; original run may resume only up to its original exact target.
- D1 rows-read/write/storage limitations, network failures, GitHub timeout or incomplete prefix → no active-pointer change; source PostgreSQL remains authoritative. Do not falsely mark D1 fully imported on an incomplete receipt.
- No automatic financial/owner writes or price promotion, and no secrets/source IDs in committed files or public logs.
- D1 Paid is **not unlimited**; monitor actual `rows_read`/`rows_written`, per-database size, billable usage and job duration. This patch is one-time scoped rather than a general paid-tier quota removal.

## Tests and verification

The existing offline fake D1/real SQLite staged source suite now covers: original receipt preserved byte-for-byte; single same-day extra receipt; full 23/23 synthetic catalogue activation only after checksum; bad approval; expired date; crashed partial paid batch; another run blocked; same-run recovery to reserved target; previous source drift/owner/price/non-publication and original 8k daily tests retained. Full backend/n8n/dashboard CI and source/capacity checks are merge gates. **After merge** the protected main push run must produce an exact D1 source count, staged rows, new source SHA and verified full activation result. No approval to switch public catalogue reads, Auth or Shopify.

Rollback: keep both immutable generations, stop the existing protected importer and revert the date-locked supplemental code/workflow. No source deletion or D1 shadow overwrite. Future catalogue refreshes need their own reviewed immutable generation and monthly capacity policy.

**This is partial catalogue migration, not a completed Supabase exit.**
