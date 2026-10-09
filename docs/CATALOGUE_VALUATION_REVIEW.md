# Catalogue valuation review — 9 October 2026

The owner requires valuations for the whole database, daily cards/sets/sealed
refreshes and immediate Shopify processing of approved For-sale inventory.
Brand Redesign remains unpublished. No paid provider upgrade is authorized.

## What the existing algorithm actually does

`drop-rate-market-v4` first rejects non-comparable condition, language, grade and
sealed-state evidence. Exact printing/source mapping must already be established.
It rejects broad outliers, computes a recency/quality-weighted median per source,
then a weighted median of eligible UK/EU source estimates. eBay GB and Cardmarket
can anchor GBP; US TCGplayer/Collectr are supporting context. Evidence weights
are sold 1.0, aggregate 0.85, guide 0.75 and active asking price 0.35. Half-lives
are 21 days for sold, 7 for aggregates/guides and 3 for active listings.

Confidence considers evidence depth, source diversity, freshness and volatility.
Recommended retail follows the estimate (minimum £1), quick-sale is 92% and
acquisition 70%. These are recommendations, not seller Store Price changes.
The scheduled inventory implementation is stricter than generic v4: exactly
five recent matching eBay UK sales from the last 90 days are required. Shipping
is recorded separately. Owner/version/identity are rechecked before saving
immutable observations and snapshots. Automatic price publication is disabled.

## Source reality, not merely configured adapters

At the audit there were 69,173 reference cards, 3,878 sealed references, 1,447
provider sets and 463 canonical products. Inventory held 510 physical copies;
156 had current eBay-backed valuations. There were 645 persisted eBay sold
observations and one older Cardmarket observation. A configured adapter does
not prove a working ingestion feed. No eBay inventory links existed.

- eBay UK sold evidence comes through the existing Trawl service, not the Browse
  API (Browse supplies active asking prices). Free monthly capacity was exhausted.
  Daily retries cannot overcome the quota or create five sales for sparse cards.
- TCGdex details supply explicit Cardmarket and TCGplayer variant IDs and dated
  prices. The earlier cache fetched English Pokémon/Cardmarket only. This
  release adds Japanese requests using the Japanese endpoint and exact locale,
  name, set, number, variant and product-ID checks. TCGplayer USD market prices
  are retained as US context only, never converted into a UK sold valuation.
- Cardmarket's public daily non-singles catalogue and price-guide exports cover
  Pokémon and One Piece in this release. CardTrader's explicit singleton `card_market_ids` (legacy `cardmarket_id`)
  joins the packaging reference to the guide; category/type must also agree.
  No name-only product matching is used. Exact Cardmarket category labels
  `Pokémon Display` and `One Piece Preconstructed Decks` map to their packaging
  equivalents; lots/accessories cannot inherit box/deck prices. These mixed-language, mixed-condition guides
  are labelled separately from physical sealed-product valuations.
- CardTrader imports packaging identity/artwork, not sold-market prices. The
  existing marketplace adapter returns active listings and cannot become sold
  evidence. No verified daily price feed is currently established for Naruto.
- Other One Piece/Dragon Ball card references still need exact marketplace
  mappings. Their broad provider checklists have no confirmed finish field;
  assigning a Normal/Near Mint value to every row would invent a physical basis.

Provider documentation: [TCGdex prices](https://tcgdex.dev/markets-prices),
[CardTrader blueprints](https://www.cardtrader.com/docs/api/full/reference),
[Cardmarket public price guides](https://www.cardmarket.com/en/Pokemon/PriceGuide).
Public download paths are fixed in `sealed_market.py`; caller-supplied URLs are
never fetched. Provider/FX failures retain recent known data with original dates.

## Daily operation and full-database accountability

Existing source imports update all supported card, set and packaging catalogues
at 03:00 Europe/London, independent of inventory. Revision 4 handles the current ID-array contract and preserves the
explicit Cardmarket cross-ID from CardTrader. Pokémon price work now covers
all English and Japanese references. Revision 2 refreshes old caches once;
subsequent passes select by the daily slot rather than repeatedly refreshing
already-completed portions of a large catalogue. Bounded batches continue after
an hour when the configured pass limit is reached. Provider failures retry after
backoff; a whole failed batch stops rather than exhausting calls.

Sealed bulk feeds run before the longer Pokémon fill, with separate durable
receipts. Complete-database coverage receipts count every card and sealed
reference by game/language/status, including unmapped, unsupported, missing,
stale and US-only evidence. COMPLETE describes the audit/job, not 100% price
coverage. A missing quote remains unknown, never £0. Public price history is
append-only, retains original dates, deduplicates identical retries and contains
no ownership data. Search reads cached database values before background work.

This release expands independent reference values; it does not claim every
reference now has our five-sale eBay algorithm value. Universal daily eBay
coverage still requires a lawful licensed/bulk sold feed or sufficient approved
provider capacity, exact language/finish/product mappings and genuine sold depth.
Fetching one page per ~73,000 reference per day would exceed two million monthly
requests before graded/condition variants. A small plan upgrade would not solve
that requirement. No plan was purchased and no missing price was fabricated.

## Channel behavior

Inventory approval/edit/For-sale transactions wake the Shopify worker after
commit; the minute sweep survives restarts. Only approved For-sale inventory
passes existing exact identity, owner, media, shipping and price gates. Draft,
personal and archived inventory remain protected. Reference refreshes never
create stock or publish catalogue entries. Store Price changes use existing
verified channel reconciliation; market-value changes alone do not reprice an
owner's listing. eBay publishing still needs its exact governed listing linkage
and acceptance check; zero linked listings cannot prove a live integration.

## Release checks and rollback

Backend and UI tests cover locale/printing/finish mismatches, stale and malformed
sources, US-only values, provider failure and duplicate/retry behavior. Actual
PostgreSQL CI applies the original cache migration and the new migration and
checks forced RLS, denied history deletion, retry deduplication, stale writes,
sealed browsing, mixed-language labels and existing Shopify gates.

Apply `20261009183154_catalogue_market_evidence.sql` only after current-head CI.
Then deploy through normal pre-deploy checks and verify source receipts, price
coverage and history growth. Application rollback leaves additive evidence in
place; do not delete observations or relax publication/ownership boundaries.

## Independent eBay catalogue values

A separate daily calculation scans every canonical product, whether owned or
not. It reads immutable eBay UK sold observations and successful exact-identity
ingestion receipts, rechecks current printing/language/condition/grade against
the saved titles, and passes the five newest distinct matching sales to the
same v4 engine. This process makes no provider calls and reads no inventory
rows or seller policies. It cannot substitute US prices, guides or asking prices.

Each resulting catalogue snapshot has its own exact physical basis and source
evidence. Its identity digest is checked again during insertion and display;
a renamed/reassigned printing cannot inherit the prior value. Source timestamps
come from the original ingestion or an actual successful provider recheck. Daily
recalculation alone never makes an old quote appear fresh. Evidence older than
seven days, sales older than 90 days and fewer than five matches stay unavailable.
Immutable history survives the last copy being sold or removed from inventory.

Release `20261009184349_independent_catalogue_valuations.sql` first to create
the additive snapshot table and job type,
deploy and verify the first CATALOGUE_VALUES receipt, then activate the versioned
`20261009185130_activate_catalogue_reference_values.sql` helper migration. This prevents an empty cache from briefly hiding
existing catalogue values during deployment. Rollback can restore the preceding
reference helper definition while retaining every new snapshot.
