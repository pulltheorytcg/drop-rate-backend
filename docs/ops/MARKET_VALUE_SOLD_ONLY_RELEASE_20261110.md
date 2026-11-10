# Drop Rate — Market Value source-only display correction (10 Nov 2026)

## Scope and why
Continuation of original reviewed [PR #964](https://github.com/pulltheorytcg/drop-rate-backend/pull/964), rebased as a separately tested integration PR to protect the active November production release. Only current **Market Value** derived from accepted, exact, recent UK sold evidence may populate financial-sounding valuation labels, founder portfolio totals, sorting and recommendation aggregates. Cardmarket catalogue GUIDE, retail asking prices, active eBay listings, unverified reference estimates, unrelated-condition comparisons and dated stale sale snapshots must **not** be re-labelled as market values.

Existing PostgreSQL tables, prices, ownership, Shopify selling prices, acquisition costs, fees, refunds, settlements, archival data, and snapshot writes are unchanged. This is a **read-only response/display contract correction**, not a market-price backfill or a change to deterministic calculation formulas. The frontend also rejects known guide-origin fallbacks in older cached API responses.

## Observed source evidence and blockers
- Production Supabase: `ozrxenrdladkooixutmm`. Bounded 505 approved/published physical CARD and SEALED copies. The earlier 14-day sold-variant eligibility screen was **0 INSERT / 0 UPDATE / 505 SKIP**.
- Extended **read-only** 90-day UK/GBP, exact catalogue/language/condition/grade, distinct sold-record pilot found **160/505** physical copies with >=5 historical matches, but only **one currently unpriced copy** with >=5 matches. It was English Near Mint Charmander, Phantasmal Flames 011/094. Its five Trawl-derived records sold between **20 and 30 September 2026**; last ingested **9 October 2026**. These do not meet an independently fresh current evidence check. A simple historical median or today's model output must not be published from this old batch.
- Trawl publicly states their API output can be used in one's own products subject to rights and limits; this is **not** an endorsement, authorization from eBay, or a guarantee of accuracy. Original source-sale identities and provider quotas still need review.
- eBay Browse supplies active offers, not sold sales. The official eBay Marketplace Insights sold API is restricted/limited release.
- Image verification is independent. First R2 audit found 90/100 byte/resolution checks passed, 10 exceptions, and none visually certified. Founders HQ media review has been deployed. This PR does not touch image approval, object storage, R2 media jobs or the reversible `DROP_RATE_CATALOGUE_BULK_HOLD=true` policy.

## What connects
`inventory_reference_values.resolve_reference_value`, `catalogue_display_prices.shared_prices`, founder recommended/portfolio aggregates, `reference-value-display.js`, and `catalogue-browser.js`. Physical portfolio counts must remain owner-scoped and never multiply a shared price without a permitted source. Stored market guide rows remain in PostgreSQL for internal diagnostics; only display contracts are tightened.

## Risks, failure testing and rollback
1. A decrease in displayed Market Value/portfolio coverage is **expected** where previously labelled numbers were Cardmarket guides or stale sales. Do not fill these with Store Price, retail MSRP or active offers. Display `Value unavailable` until eligible sold evidence is verified.
2. Incorrect current-value suppression of a truly eligible sold snapshot: test exact-source `AVAILABLE` cases, raw condition, grade and language, plus portfolio totals.
3. Stale account/cache response retaining the old monetary field: regression-test frontend fallback and reject-list.
4. App startup/performance: require full GitHub Python/Node/browser tests, the unmodified Railway 11,485+ pre-deploy tests, and `/health/ready=200` and stable API build.
5. Financial or owner mutation: none permitted by this change. Review changed files; verify settings `DROP_RATE_SUPABASE_PLAN=pro`, `DROP_RATE_CATALOGUE_BULK_HOLD=true` unchanged.
6. Rollback: Git revert this display-only PR and redeploy if legitimate verified sold values disappear unexpectedly. Never restore guide values as a workaround.

## Separately gated data work
Before writing **any** new prices: obtain fresh permitted sold evidence with stable sale IDs, individual GBP prices/shipping, sale date, precise printing/variant, graded company/grade, language and condition; remove duplicates and outliers; run existing deterministic FastAPI v4 pricing in read-only bounded mode, inspect at least 20 examples and disclose INSERT/UPDATE/SKIP; then approve the exact application. The current pilot has **no publishable fresh unpriced values**.

## Evidence and acceptance
Use [the existing 20-item read-only price SQL/report](../audits/2026-11-10_tier1_pro_sold_dryrun.md) and [the R2 100-item receipt](./SUPABASE_PRO_R2_TIER1_FIRST_RUN_20261110.md). This branch is derived from the original tested #964 source to make GitHub recompute all CI checks against the **current** main before the controlled production release. No bulk refresh, no Trawl requests, no database/R2/Shopify writes.
