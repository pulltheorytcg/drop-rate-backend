# Accurate market-value coverage — 10 November 2026

## What changed

The existing `backend/app/catalogue_coverage.py` marked `MIXED_LANGUAGE_GUIDE` as a priced/reference-available status and used a 7-day local cache-expiry rule to decide whether a reference was priced. This inflated the displayed verified-value percentage when mixed-language guide prices were present and also let eligible source-dated quotes age out of the displayed KPI prematurely.

The revised read-only coverage SQL only returns `REFERENCE_AVAILABLE` when a `reference_market_prices.quotes[]` source observation contains:
- `physical_valuation_eligible=true`;
- a positive normalized GBP minor-unit price;
- `reference_language` matching the canonical reference;
- `observed_at` within 14 days.

**IMPORTANT:** This proves *at least one* eligible quote for the reference, **not** every print/finish/condition/grade. Full variant coverage remains unmeasured and is not represented by this KPI. The rule does not promote provider guide estimates, retail prices, USD asking listings, digital Pocket cards, or stale evidence into true market values. It **does not write any prices**, rewrite price history, create images or call provider APIs.

`MIXED_LANGUAGE_GUIDE` remains visible as a distinct diagnostic status, but no longer contributes to `priced` or the physical 89% target. Existing asking-price context is still separately labelled and **must not** be presented as achieved market-value coverage.

## Why this matters

Verified production read-only SQL at 12:17 UTC on 10 Nov showed:
- 69,867 reference rows including 2,480 digital Pokémon Pocket records.
- Existing seven-day `expires_at`-driven status had **0** current `reference_market_prices` cache rows across the four launch games at that instant.
- **21,091** Pokémon physical reference identities had at least one permitted, language-matched and GBP-positive `physical_valuation_eligible` quote observed within the requested 14-day evidence window.

These 21,091 are not 21,091 currently verified physical **inventory prices** and not full variant coverage; they are only qualifying source evidence under the stated fields.

## Connections and failure points

- `FastAPI/shared_price_coverage` renders read-only global reference coverage from Supabase Postgres.
- `catalogue_maintenance.record_coverage` records the daily read-only KPI receipt.
- All founder ownership, store-price, Shopify, payouts, RLS, D1 and market-persistence logic remain untouched.
- Full scan can be expensive; the existing two-minute request-level cache and bounded 45-second SQL timeout remain.
- Quote `observed_at` and `price_gbp_minor` field formats are prevalidated by existing ingestion; any unexpected malformed timestamp requires a separate investigation (no coercion to valid price).
- A quote is never the store price. The result must not trigger auto-publication or waive source licensing checks.
- **No Supabase backup needed to test this read-only query;** production schema, provider sources and physical records are unchanged. Production merge/deploy still needs passing CI and monitoring.

## Tests

- `tests/test_catalogue_coverage_gaps.py` now explicitly checks the 14-day source rule, exact language and physical flags, and that mixed guides are excluded from verified priced statuses.
- `tests/test_catalogue_coverage_target.py` recalculates target percentages consistently with verified evidence only, including digital exclusion and mixed-language source cohorts.
- Full repo CI must pass before merging. No production backfill, image mirroring, Railway variable change or new paid source is authorised by this PR.

## Rollback

Revert only this isolated PR; it contains no migration or stateful writes. Supabase remains the source of truth and Cloudflare D1 remains paused.
