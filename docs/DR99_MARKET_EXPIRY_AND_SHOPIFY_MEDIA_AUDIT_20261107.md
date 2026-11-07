# DR-99 — Fail-closed Market Value freshness and source integrity

**7 November 2026.** User asked for fully automated, accurate artwork, market values, Shopify listings and Riftbound data. This patch addresses a confirmed **production pricing bug** and makes no claims that missing legal source data has been provided.

## Build, reason and connections

**What:** Legacy reference browse SQL and `/market-values` cached reads must honour the provider/DB's explicit `expires_at` in addition to the seven-day recency of the quote. Catalogue/coverage SQL must mark expired source evidence as stale rather than quote available. The browser's canonical `catalogue_reference_value_v2` function can return Cardmarket guides and exact sold-evidence snapshots; when populating the *Market Value* field, select only `STORED_SNAPSHOT`, the SQL function's current source code for verified `CATALOGUE_EBAY_V4` evidence. Never infer fresh data by extending `expires_at`.

**Why:** Live 7 Nov DB verification: `reference_market_prices` holds 59,693 rows across four games; all precomputed price rows have `expires_at < NOW()` (latest 4 November); earlier browse paths still considered recent `pricing_updated_at` sufficient until seven days elapsed, so expired values could incorrectly display as live Market Value. This is a correctness/data-integrity issue, not a permission to republish stale data. All 506 approved/for-sale physical inventory items currently have non-test `PUBLISHED` Shopify links, with 0 candidate rows. This patch **does not** modify inventory ownership, Store Prices, Shopify status or orders.

**What it connects to:** `backend/app/catalogue_browser.py` (reference cards, sealed entries, canonical v2-snapshot view), `backend/app/catalogue_coverage.py` (evidence status), `backend/app/reference_market.py` (bounded cached quote-view) and the original `expires_at` columns. R2 immutable price history/quotations and SQL snapshot evidence are retained unchanged.

## Failure cases and tests

- A quote observed two hours ago but expired one minute ago is **unavailable**, never a current Market Value.
- A valid unexpired quote can still display if the existing source/identity/age rules pass.
- An exact catalogue fallback may substitute only with its *own* future expiry and exact provider-print identity.
- Missing, invalid, timezone-naïve or old expiration fails closed.
- Both value sort and regular browse filters exclude `CARDMARKET_ESTIMATE` canonical snapshots from Market Value. Sources labelled guide remain historically available as separate evidence; they cannot silently become sold Market Values.
- Coverage dashboard reports expired evidence as `STALE_EVIDENCE`, including sealed products; it does not improve percentages by dropping rows from the denominator.
- Tests: `PYTHONPATH=backend pytest -q tests/test_dr99_price_expiry.py`, whole backend suite, n8n pinned-runtime, dashboard regression and Railway API predeploy suite. No DB migration or source-write operation.

## Live rollout and remaining dependencies

Green CI → merge → verify Railway API success and predeploy counts, then production read of `reference_market_prices` freshness/Shopify status. Production user display must be checked with an authenticated account; this patch does not claim a specific UI screenshot passed.

This does **not** populate new prices: current legacy source refresh is blocked at 430,484,627 bytes by a 400MB bulk-refresh safeguard, and eBay live market provider recently reported HTTP 429. Sold-price sources require an approved API/provider, legitimate terms and exact grade/printing/language. EBay Browse active listings are asking prices, *not* sold evidence. Cardmarket currently declines new API applications and its API terms restrict downstream pricing publication without prior written permission. Do not bypass these controls to fill 100% coverage.

### Separate artwork/Shopify/Riftbound audit

- 66,218 legacy exact-reference images already verified in private R2; 3,475 Pokémon `reference_cards` have no source image URL. Several missing images are in `2021swsh`; the source is missing, so don't guess by name. Four TCGdex image mirrors are `RETRY` with `SOURCE_UNAVAILABLE`.
- Six R2-first sources total **204,411 factual catalogue references**; metadata access does not establish commercial reproduction rights to each alternate-art printing. DR98's six enrichment queues are live, but no private batch result has yet been independently verified through an actual run at this checkpoint.
- Eight physical graded cards have non-test published Shopify database links. The `media_assets` register shows no **approved/rights-verified, Shopify-ready `FIRST_PARTY_CAPTURE` slab photos**. Existing `action_required_items` includes graded-photo reviews, including four resolved and two open; review overrides and provider certificate images may exist. **Do not silently unpublish a product or overwrite a founder review just from this aggregate**. Exact-copy licence/photo, Shopify remote listing/image readback and owner review must precede a decision. Media policy already requires physical capture for graded items.
- Riftbound cards/art remain blocked until a product registered/approved in Riot's developer portal has a valid App-specific key or written licence. Riot explicitly forbids unofficial non-API assets in developer apps. No unapproved public gallery scraping.

See [Riot Riftbound policy](https://developer.riotgames.com/docs/riftbound), [Cardmarket API application status](https://help.cardmarket.com/en/cardmarket-api), [Cardmarket API use restriction](https://help.cardmarket.com/en/general-terms-and-conditions), and [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html).

**Exit conditions for user's full four-feature request remain:** original print image + redistribution authority + signed R2 and actual slab photo; complete eligible UK sold-price dataset/valuation and freshness for each card (or explicit unknown); physically owned approved stock only on Shopify with live GraphQL readback; Riot production App-specific access. None can be truthfully marked complete solely because schedulers are active.
