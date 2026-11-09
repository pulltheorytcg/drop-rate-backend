# Yu-Gi-Oh: bounded immutable name-only D1 refresh — 9 November 2026

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## Why this exists / live evidence

Main-branch protected run 42541564741 on 9 Nov 2026 reported exact, non-private source divergence: 45,419 verified R2 records vs 45,418 originally pinned; 24,000 staged old D1 rows; **three** retained rows differ only in `name` and `name_fold` (3 each); **zero** missing stable keys. The importer correctly failed closed before writing. This is not evidence that the whole source, historical prices, artwork, Shopify or operational data has already migrated.

## What changes

The existing source-verified, quota-limited `tools/d1_yugioh_shadow.py` importer now accepts **at most ten** old staged records corrected **only** as coupled `name` and `name_fold` differences. It checks that both old and new search fold strings precisely equal `name.casefold()`, and all provider IDs, stable keys, set IDs, card numbers, grades, languages, cardmarket ID, rarity and every other D1 projection field match. A new R2 manifest is staged into a **new immutable D1 generation** and receives exact checksum/readback before its isolated D1 active pointer can change. Old generations/records are kept.

The revised source is independently verified via the existing signed R2 export. This change adds no new Cloudflare service, database, direct public read path or cost commitment. It does not grant permission to update prices or canonical card IDs.

## Connections

R2 verified Yu-Gi-Oh source -> existing GitHub Actions signed source-export reader -> existing isolated Cloudflare D1 `drop-rate-d1-real-yugioh-shadow` -> exact-row parity and daily quota receipt. Up to 8,000 newly staged rows per UTC day; duplicate-day receipts cannot be evaded. Do not confuse D1 staging with production serving.

## Failure / rollback

Any missing or changed stable key; different owner/identity field; unexpected non-name metadata; unpaired name/fold change; normalization mismatch; more than 10 corrected rows; corrupt D1 previous-generation row; missing source part; wrong token; quota clash; checksum mismatch; concurrent pointer change -> fail closed. Logs contain only counts and fixed column labels, never identifiers or names. Stop the existing importer and revert this code to return to the previous strict rule. The old D1 generation is not modified or deleted, and Supabase continues to serve operations.

## Tests and release gates

Offline simulated D1 + authenticated R2 fixtures: accept three corrected names with one new source row, retain old staged rows, complete new generation only after all new rows and exact SHA, reject bulk name changes, wrong search folds and non-name identity/rarity changes; preserve existing tests for source corruption, repeat daily budgets, wrong tokens and tampered rows. Python 3.12 CI must pass, including backend full suite and migration isolated-source suite. After merge, inspect the **protected production D1 readback**: published stage is partial until 45,419 exact source rows are verified; no other references, owners, payments, Shopify/consumer routes or Auth are switched. Historical Supabase operational exit remains blocked until all tracker gates pass.
