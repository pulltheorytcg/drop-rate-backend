# Drop Rate — asking-based Market Value release gates (12 November 2026)

## Change accepted by founders
The visible `Market Value` for **canonical ungraded single-card catalogue references** may now be derived from a robust median of comparable **current eBay UK asking prices**, rather than waiting for completed sales. This is a change in business pricing policy, **not** proof of transaction-clearing value. Prices remain source-labelled in the API (`DROP_RATE_UK_ASKING_MARKET_V1`; `CURRENT_UK_ACTIVE_ASKING_LISTINGS`).

## Why this belongs
Current catalogue coverage is limited partly by lack of completed-sale access. The existing official Browse asking-price collection has exact-game/name/set/number/finish/language/condition checks, independent seller deduplication, shipping-inclusive GBP pricing, robust median, outlier and dispersion tests, 3-day TTL and an append-only evidence history. Reusing this stack is simpler and auditable; do NOT create a competing pricing engine.

### Connected components
- `reference_asking_estimator.py`: existing deterministic comparable matching and median; unchanged.
- `reference_asking_backfill.py`: existing official eBay Browse quota/reservation, detailed item checks and append-only `reference_asking_history` + short-lived `reference_asking_prices` cache; **not automatically scheduled in this PR**.
- `reference_asking_display.py`: projects eligible cached asking estimate into the single catalogue `market_value_minor` / `market_value_high_minor` field, with source, evidence, confidence, timestamps and expiry.
- `catalogue_browser.py`: existing page-limited reference display; **no physical inventory or Shopify writes**.
- `catalogue_coverage.py`: exact eligible asking caches count as `ASKING_BASED_MARKET_VALUE` (not verified sales); still excludes digital products and expired caches.
- `pricing_health.py` + founder widget: source metric shows current asking caches rather than falsely blocking on missing sold data.

## Hard safety boundary
- The model currently covers **RAW Near Mint/Mint English/Japanese and other supported-language single-card printings only**, where exact listing details prove set, card number, finish, language, seller, GBP price and current UK item location. Not an automatic grade-specific/slab/sealed/comic/figure value.
- Minimum **three independent sellers**; de-duplicate listings; include UK shipping; reject outliers and high dispersion; cache expires within 3 days. Fewer observations or unknown condition/language => `Market Value` remains unavailable.
- `Market Value` on the *catalogue* does **not** automatically change `inventory_items.market_value_minor`, `store_price_minor`, acquisition cost, Shopify price, founder/consignor ownership or settlements. Those require separate identity-compatible audited rules and an approved release.
- Source basis is never represented as a completed sale. No AI guess, no arbitrary retail/RRP proxy. Storefront remains independent.
- No paid scraper, no Cloudflare migration; stack is existing GitHub, Railway, Supabase Pro, Shopify.

## What we verified in production (read-only)
- Asking cache `tcg.reference_asking_prices`: **0 rows** (also 0 fresh).
- Earlier `reference_asking_runs`: seven `INCOMPLETE` runs, with **zero READY and zero writes**. Latest historical run made 860 requests, 259 searches, evaluated item details but no qualifying three-seller estimate.
- `reference-pricing-batch` Railway service currently runs only a **quota diagnostic command** and has no recurring asking-valuation acquisition. It is not a price worker today.
- Supabase organization Pro subscription verified using connected organization details, database 428,362,899 bytes, under Pro safety headroom. **Batch service currently does not declare `DROP_RATE_SUPABASE_PLAN=pro`** so free-plan safety thresholds may block writes. Do not bypass actual capacity/backup checks.
- Full site-wide card/slab/sealed/figures coverage requires separate source-safe adapters and pilot evidence. This PR does not claim a gain until new records appear.

## Deployment and collection plan (separate gates)
1. Full Python/UI/Postgres/n8n CI; merge PR; Railway API deployment confirmed via SHA.
2. Read back app API and empty asking cache; mark 0 visible change until new data.
3. Confirm DB backups / operator bulk hold status, provider quota and `reference-pricing-batch` config; if verified safe, set explicit Supabase Pro capacity guard for batch.
4. Change existing batch command **only in a controlled pilot** to invoke `backend/scripts/backfill_reference_asking.py --from-settings --run --apply --max-queries 25` with UK marketplace and existing origin postcode. This is max 25 total Browse calls, not 25 products. No unknown broad scraping; retain quota headroom and durable run receipts.
5. Check `reference_asking_runs` receipt: `matched>0`, `written>0`, and physically verify `reference_asking_prices` cache and an exact canonical reference displaying `market_value_source=DROP_RATE_UK_ASKING_MARKET_V1`. If still zero, **stop**, inspect `reference_outcomes`, candidate rejection reasons (language, set, finish, number, seller count) and improve *correctly*, not by silently dropping exact-match checks.
6. Only after a positive pilot, use existing batch-service cron/scheduler, fixed daily request quotas, an idempotent cursor strategy, and alerting for **actual new priced references**, stale caches, missing seller information and failed jobs. Avoid blind bulk updates; preserve append-only provenance.
7. Expand game/language cards. Separate future pilot for slabs, sealed, comics, figures, R2-first catalogues: each has different exact identity and condition match requirements.
8. Measured dashboard KPIs: fresh caches, `ASKING_BASED_MARKET_VALUE` reference count, new independently matched references per day and percentage of exact catalogue printings with values; distinguish stored physical item counts and never claim an estimate is a sale.

## Failure tests and rollback
- No valid comparable / stale cache / single seller / wrong grade: do not display estimate.
- Code, deployment, source cache and UI release receipts must all match; CI alone does not prove live value changes.
- Revert this PR to restore earlier sold-only policy. No schema migrations, Shopify price changes, inventory writes or replacement pricing engine were introduced.
