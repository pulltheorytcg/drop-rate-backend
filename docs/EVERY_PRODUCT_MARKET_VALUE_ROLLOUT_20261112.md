# Drop Rate — Every-Product Market Value Expansion, Phase 1 (2026-11-12)

## User goal
Continue automatically building accurate Market Values for **every product** in the original
SQL catalogue and newer R2-first catalogues. Keep the existing single deterministic
FastAPI pricing engine, Railway, Supabase Pro, GitHub, Shopify; no Cloudflare
migration or paid scraper. A displayed Market Value must never silently
come from RRP, a live seller's ask, or a price-guide estimate.

## What was built, why, and where it connects

### 1. Source-aware work queue
\`GET /api/v1/pricing/coverage-work-queue\` is authenticated with
\`require_business_founder\` and reads the **existing cached** catalogue
coverage through \`shared_price_coverage\`. It compares the **SQL cards**
by system/language to the **R2-first publication metadata** and returns
all present source partitions, including sports and figures. The UI appends
a section under the existing Live Pricing Health widget, refreshed at most
once every ten minutes while Founder Settings is open.

What it does NOT do:
- Guess missing count from R2 catalogues (value coverage is NOT MEASURED).
- Combine SQL and R2 if the existing publication system reports overlap.
- Count guide-inclusive reference prices as UK paid-sale Market Values.
- Convert unverified provider metadata, artwork counts, or future releases
  into a valuation.

Original SQL reference counts observed during read-only production audit:
English/Japanese Pokémon 37,068; One Piece 9,007; Dragon Ball 16,626;
Naruto 7,166. Combined 69,867 reference records (not unique physical cards).
The exact full R2-first portfolio count is independently fetched via the
existing publication-aware report, rather than guessed from local memory.

### 2. Official eBay Marketplace Insights sold-history source adapter
\`backend/app/ebay_official_sold_source.py\` introduces an **unregistered,
access-blocked-by-default** official API client. It reuses the existing
\`EbayOfficialClient.application_token()\`, rather than inventing a new
OAuth provider or using a third-party paid scraper. It only requests
\`GET /buy/marketplace_insights/v1_beta/item_sales/search\` after ALL of:
- An explicitly recorded eBay partner business approval reference,
- Provider-terms review,
- A specific whitelisted eBay GB category,
- The existing configured EBAY_GB OAuth client.

This is NOT a claim that our account has Marketplace Insights privileges.
eBay Marketplace Insights remains **Limited Release** and cannot simply
be unlocked by signing into eBay Seller Hub. The API may deny all requests
until eBay approves the business/category. If access is not granted,
the client makes **zero** provider HTTP or OAuth calls. It never falls
back to Trawl, account-cookie scraping, or Browse listing asks.

If permission is granted, the separate normalization boundary:
- Reads only real \`itemSales\` with \`lastSoldPrice\`, \`lastSoldDate\`,
  \`itemLocation.country == GB\`, \`currency == GBP\`.
- Rejects unverified Best Offer / sale format, conflicting IDs,
  stale/imprecise/future dates, non-UK goods, unknown or invalid amounts,
  wrong card number/name/finish/language/condition/grading company/grade,
  ambiguous bulk lots and One Piece parallel-vs-ordinary collisions.
- Treats \`totalSoldQuantity\` as context only. One listing ID gives at most
  **one** observed latest transaction, never X independent comps.
- Produces our existing \`NormalizedMarketObservation\` contract,
  a stable source-record key, exact provenance, and an explicit
  **CANDIDATES_REQUIRE_INDEPENDENT_REVIEW** classification.
- Does **not** write to Supabase or auto-publish prices. The existing
  append-only \`_insert_observation\` and deterministic
  \`calculate_price\` can be connected after provider rights,
  accepted-offer amount semantics, quality review, and a bounded pilot.

Existing Trawl price history remains append-only, but archived legacy
transactions with no confirmed paid-price evidence are not suddenly eligible
for new valuations. The adapter does not use old Trawl credentials.

## Source and product coverage
**All published product types** now have a status entry, but not all
have market evidence. The source access matrix is deliberately honest:

- Original Pokémon, One Piece, Dragon Ball, Naruto: SQL catalogue
  listing prices/guides can exist, but exact UK sold-value availability
  requires independent confirmation and recency.
- Yu-Gi-Oh!, Lorcana, Magic, Riftbound: R2-first canonical identities
  already published where available, but metadata publication ≠
  verified sold UK transaction data.
- Sports and figures: R2-first checklists/official facts are partial,
  so they need exact item/year/parallel/variant identification,
  plus a legitimate sale source.
- Slabs: unique grading company and grade must match, and
  physical slab imagery stays distinct from the canonical card.

## Release and testing gates
1. Full GitHub backend, dashboard, PostgreSQL and n8n CI.
2. Production read-only work-queue round-trip via founder access,
   no access to cross-owner inventory, seller gets 403.
3. Under **written confirmed eBay access approval only**, start with a
   read-only 25-item search cap. Verify sample raw Pokémon, One Piece
   parallel, PSA slab, sale amount, actual paid Best Offer and location.
4. Append independently verified sales to existing Supabase history
   idempotently, preserving original raw source; never rewrite history.
5. Use the existing FastAPI five-exact-comp calculation. Pilot Market
   Value only; do not change \`store_price_minor\`, Shopify, artwork,
   owner or settlement data. Review volatility/outliers and rights.
6. Measured improvement: count **new qualifying item-level UK sales**,
   **five-comp eligible physical items**, and separately the global
   catalogue with verified market evidence. Only then expand by game.

## Failure handling and rollback
- OAuth 403 / missing partner category → blocked, no retries into a scraper.
- 429 / quota → rate limited and surfaced to monitoring, no bypass.
- Conflicting sale IDs / accepted offer unknown → quarantined.
- Cross-product / unverified grade → reject the specific comparable,
  never fill with retail or language-adjacent prices.
- Lost founder access → 403 before reading any global coverage.
- R2 caching outages → existing SQL health remains viewable.
- No automated price publication is enabled by this PR; revert it to
  remove the queue and source adapter without data repair.

## Verified external reference
eBay Developer docs:
https://www.edp.ebay.com/api-docs/buy/marketplace-insights/static/overview.html
and the Marketplace Insights item_sales search OpenAPI reference.
Market Insights is **Limited Release** and approved categories are
business-unit-controlled; eBay Browse is active-listing data, not
completed-sale prices. Provider permission may constrain redistribution.
