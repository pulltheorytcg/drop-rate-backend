# Cloudflare D1 keyset readback and finance HTTP-400 diagnosis — 9 November 2026

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## 1. What / why

The verified 45,419-row Yu-Gi-Oh R2 source is being staged in an isolated Cloudflare D1 database. On 9 Nov run 42542647042 created and exact-readback-verified the **first 8,000 records in the NEW generation**, preserving the older 24,000 rows. The importer and shared exact-source checksum verifier previously used `LIMIT 100 OFFSET N` for every batch. With a 24,000-row retained generation, offset-based pagination can scan roughly 2.9 million index entries during a single proof; repeated verification and other imports can consume an account-wide Cloudflare free daily read quota even when importing only 8,000 new records.

At 01:42 UTC the newly merged protected financial typed-column parity gate [run 42546890921](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42546890921) failed on an HTTP 400 from the first private `ops_shadow_owners` query. **The cause is NOT yet established.** Possible causes include daily account read exhaustion, schema errors, or a Cloudflare platform fault. It is not evidence of mismatched owner pennies or that the database is gone.

## 2. Connections and changed components

- `tools/d1_r2_real_shadow.py`: exact full-source SHA proof uses indexed cursor `(manifest_sha, card_key > prior_key)`, paginated by 100, retaining the existing original column ordering, SHA calculation and fail-closed checks. The old exported SQL constant remains for legacy Lorcana refresh calls, so their calling convention does not silently change.
- `tools/d1_yugioh_shadow.py`: old-generation comparison and new-generation prefix verification use the same keyset cursor. Identity, missing-key, name-only correction, exact-row parity and daily 8,000-row write budget safeguards remain. `shadow_cards` already has a composite primary key on `(manifest_sha,card_key)` so no D1 schema/index or production write migration is required.
- `tools/d1_remote_catalogue_pilot.py`: classify Cloudflare HTTP errors using only a fixed-category allowlist, never freeform provider messages, SQL, customer/card IDs or secrets. `tools/d1_operational_financial_integrity.py` preserves just that allowlisted category plus the already-fixed schema table label. This is diagnosis only; it never retries finance writes or bypasses Cloudflare quotas.

## 3. Failure points and verification

Unexpected pagination order, incomplete readback, missing/duplicate key, tampered typed fields, partial generation, source manifest mismatch, quota exhaustion, schema mismatch and provider HTTP failures **must all fail closed**. Offline tests cover resumed Yu-Gi-Oh rows and full source checksum with keyset-only SQL, plus Cloudflare HTTP 400 daily-read, daily-write, missing-table and unknown-error classifications without leaking response strings. Full backend and independent catalogue/finance workflows remain CI gates.

When deployed, use one protected main-branch read-only financial gate and its fixed-label error category to establish the actual HTTP-400 cause. If the daily quota is exhausted, **do not** retry within the same UTC day or buy an upgrade without explicit approval; wait for the next quota window and measure usage. Do not rerun importer to evade its durable same-day write receipt. If schema mismatch appears, review D1 table/index state before another read. A D1 health/status check is not a complete historical or financial cutover.

## 4. Rollback and release state

Revert the code and stop the protected staging workflows to return to their prior pagination behavior. No source data, old D1 generation, owner balance or pricing is changed by this patch. Supabase Auth, PostgreSQL owner/financial source of truth, Shopify and live Railway consumers remain unchanged. A successful next-stage import and typed financial parity must be recorded separately before any read/financial/identity cutover is considered. Zero-Supabase exit remains **NO-GO**.
