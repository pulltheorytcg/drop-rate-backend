# Drop Rate — current Market Value must be verified sold evidence (10 Nov 2026)

**Status: CODE IN REVIEW — do not claim production pricing corrected until all CI and Railway readbacks pass.**

## What is changing
User-approved policy: display only **Market Value** supported by approved, current, like-for-like UK sold evidence. Cardmarket asking/trend/catalogue guides, eBay Browse active listing asks, stale cached figures, historical guide values, model predictions and recommended retail are **not** current Market Values. The existing reference/store/quote tables, source provenance and historical observations remain unchanged.

This work rebases the tested solution of [old PR #964](https://github.com/pulltheorytcg/drop-rate-backend/pull/964) onto current main without merging that stale 2026-11-early feature branch wholesale. Four code surfaces are deliberately changed:

1. `backend/app/inventory_reference_values.py`: `CATALOGUE_CARDMARKET_V1` may return status `REFERENCE_ESTIMATE` for source-review diagnostics but **no** `market_value_minor` nor `recommended_retail_minor`; stale guide is not a last-known Market Value; portfolio recommendation counts require `AVAILABLE` and sold evidence.
2. `backend/app/catalogue_display_prices.py`: reject `REFERENCE_ESTIMATE` and `CATALOGUE_GUIDE` numeric fields before sending the search/sort reference.
3. `backend/app/static/reference-value-display.js`: **only** `AVAILABLE` sold evidence may supply current displayed Market Value. Stale/history/model/guide amounts are not rendered in physical-owner totals, tiles or dialogs. Store Price is independent.
4. `backend/app/static/catalogue-browser.js`: the Market Value sort considers only eligible current amounts. Explicitly deny prior guide methods in the browser as defence in depth even if cached old API responses remain.

No provider requests, valuation recomputation, migrations, Shopify mutation, inventory ownership, settlements, price-history deletion or R2 media changes are made. Bulk refresh remains held by `DROP_RATE_CATALOGUE_BULK_HOLD=true`. No unverified price is inserted to compensate for guide suppression.

## Why this belongs now
Earlier screenshots and founder reports showed retail/guide data offered under Market Value even though the user instructed a Market Value-only storefront. A source can be a useful research guide without being a verified sale. The old, tested PR #964 had not merged into the growing main branch; this is a bounded compatibility port.

## Connections
- PostgreSQL/Supabase retains all source and shared valuation/history records; FastAPI reads exact `CATALOGUE_EBAY_V4` sale-derived snapshots and diagnostic `CATALOGUE_CARDMARKET_V1` guide snapshots with owner RLS preserved.
- The same response contract feeds founder portfolio totals, Seller Hub list/detail, catalogue sort, inventory editor, mobile presentation and scanning preview. Shopify's **Store Price** is not modified.
- The UI may show more **Value unavailable** fields where real sold evidence is missing. This is an intentional accuracy correction, **not** new price coverage.

## Failures and tests
- **Potential failure:** accidental suppression of a true sold `AVAILABLE` value. Tests assert like-for-like sold remains visible and sortable, guide-only and historical never populate current Market Value, stale amounts do not revive, and Store Price stays separate.
- **Potential failure:** legacy references in mobile UI or owner totals survive through cache. The backend returns null numeric fields and the browser adds defensive method/status checks. Retain original source provenance in historical/research endpoints.
- **Potential failure:** unrelated newer inventory/list/detail UI lost during cherry-pick. The browser was patched by exact hunk, and existing newer owner-inventory/collection tests were patched by exact hunks instead of overwritten.
- **Potential failure:** founder dashboards appear less complete. Treat count decrease as truthful under strict sold-only evidence. Recovery is rollback of this code PR, **not** replacement of missing values with guides.
- **Tests:** run all existing Python pricing, RLS, finance, asset and catalogue tests, UI npm tests with the sold-only regressions, n8n offline validation, Railway unmodified full pre-deploy `pytest` and Stripe sandbox checks, `/health/ready=200` and the existing Pro bulk hold log on release. Run live exact-identity API sample checks before claiming customer-visible correction.
- **Prerequisites for real coverage increase:** permitted fresh sold data access, exact printing/variant/condition/grade and language match, deterministic FastAPI robust statistics, reviewed source-rights, bounded INSERT/UPDATE/SKIP dry-run and separate verified approval for any write. The 505-item Tier 1 prior strict preview remains **0 insert / 0 update / 505 skip** without new evidence.

## Deployment
This branch starts as **review only**. Merge only after green CI and reviewed diff. Railway deployment should be automatic through existing repo branch, preserving `DROP_RATE_SUPABASE_PLAN=pro`, `DROP_RATE_CATALOGUE_BULK_HOLD=true` and all Shopify/R2/settlement runtime settings. A successful CI result alone is not a live app verification.
