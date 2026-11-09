# Indexed D1 keyset parity on source catalogue generations — 9 November 2026

Migration tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## Source of this work

Protected read-only [financial parity run #42546890921](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42546890921) failed at the **first tiny** `ops_shadow_owners` read with Cloudflare HTTP 400, after a prior initial attempt and retry failed similarly. The financial source hash/typed-column acceptance gate has **not** passed; no mismatch was established and no data was changed.

One independently visible catalogue source of avoidable D1 read pressure is `tools/d1_yugioh_shadow.py`: it re-reads the original 24,000 immutable Yu-Gi-Oh staged cards using 100-row pages and `ORDER BY card_key LIMIT 100 OFFSET ?`. Summed offsets across 240 pages are roughly **2.89 million skipped/visited row positions per pass** even before other readbacks; the true Cloudflare `rows_read` depends on the SQLite query plan and indexes. Multiple verification passes in the same UTC day can accumulate significant account-wide D1 reads. D1 Free daily allowance and exact account-plan/consumption are **not directly verified here**; quota exhaustion is a plausible cause of the HTTP 400, **not a confirmed diagnosis**. Only Cloudflare's account metrics or relevant safely classified error codes can confirm it.

Cloudflare references:
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/d1/observability/metrics/

## What, why and connections

Switch the existing **read-only** old-generation comparison, current-generation full staged-prefix comparison and final checksum pass to **indexed keyset paging**:
`SELECT [fixed canonical columns] FROM shadow_cards WHERE manifest_sha=? AND card_key>? ORDER BY card_key LIMIT ?`.

Existing composite `PRIMARY KEY (manifest_sha,card_key)` is used directly; no index, D1 schema, database, Worker, API route or Cloudflare plan is added. The verified R2 source, isolated D1 source generation, daily write budget, exact physical card identity, permitted name-fold-only correction gate and end-to-end SHA are unchanged. The old `D1_READBACK_SQL` constant is preserved for compatibility with other callers, but the protected critical scans now use the new keyset helper. Other smaller Lorcana refresh routines still use OFFSET and should be audited separately.

## Failure points / tests

A page with missing rows, duplicate/replayed keys, missing/extra/incorrect typed columns, out-of-order key, changed D1 row or checksum disagreement still raises `MigrationGuard` before any isolated D1 activation. Source generations stay immutable, with no public read switch, payment, owner, finance, auth or Shopify action.

Offline real-shaped synthetic tests must pass:
1. 180 old Yu-Gi-Oh rows (120 staged), new source 181 (3 name corrections), multiple 100+ row D1 pages; retain old generation, import new under daily quota, verify exact final SHA and refuse any protected scan containing OFFSET.
2. Full 1,002-row Lorcana source parity verifies source SHA using keyset from blank cursor; no deep offset page.
3. Out-of-order/malformed D1 cursors fail before publication; existing source corruption, owner isolation, quota and SHA tests stay green.

Protected production acceptance requires a scheduled future read/write gate to complete under real D1 budget and a new read-only finance parity receipt. Existing **8,000 new rows/UTC day** reservation remains non-bypassable; a second attempt today cannot be used to evade quota. Never move financial/auth or Shopify public reads on the strength of a catalogue-only readback.

Rollback: revert this importer helper to the previous fail-closed read path or pause the existing staging workflow. Do not delete or rewrite any prior D1 generation. Supabase remains operationally authoritative.
