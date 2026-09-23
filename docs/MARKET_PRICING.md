# Drop Rate Market Data & Pricing Architecture

_Last reviewed: 23 September 2026_

## Goal

Produce deterministic, auditable GBP market values and recommended retail prices for physical TCG inventory without allowing AI to arbitrarily set prices.

The pricing path is:

`Provider data -> source adapter -> normalized immutable observations -> comparable filtering -> robust pricing engine -> immutable pricing snapshot -> inventory recommendation -> approval/guardrail -> future Shopify sync`

Shopify will never be the source of pricing truth. PostgreSQL/FastAPI remain authoritative.

## Source strategy

### eBay

Use official/permitted eBay APIs only.

- Browse API can provide active listing signals.
- Marketplace Insights can provide sold history where Drop Rate is granted production access.
- Sold transactions are higher-quality evidence than active asking prices.
- UK (`EBAY_GB`) evidence receives a small geographic relevance preference for the UK store.
- Never scrape completed listings pages.

### Collectr

Collectr publicly advertises API access for product details, market prices and trends.

- Apply for API/partner access.
- Treat verified sold/comparable data as strong evidence where the API terms expose it.
- Treat a single market-price aggregate as one source estimate, not hundreds of phantom transactions.
- Keep Collectr source IDs so catalogue mapping is explicit and reviewable.

### TCGplayer

TCGplayer's pricing endpoints expose market/low/mid/high and SKU-level market values, but TCGplayer currently states that it is not granting new API developer access.

- Build and keep the adapter contract ready.
- Enable it only if Drop Rate obtains legitimate access/partnership.
- TCGplayer Market is treated as an aggregate market signal rather than an individual sold transaction.
- US market evidence is useful but receives slightly less UK geographic relevance than UK/EU evidence.

### Cardmarket

Do not depend on the restricted Cardmarket account API.

Cardmarket publicly provides downloadable price-guide and product-catalogue files for all supported games and states that the price guide is updated daily.

- Use the public download mechanism, subject to current terms.
- Match Cardmarket product IDs to Drop Rate canonical catalogue IDs.
- Store each day's price guide as a new observation; never overwrite yesterday's data.
- Cardmarket is particularly relevant for UK/EU pricing.

## Observation types

`SOLD`
: A completed transaction/comparable. Highest base evidence quality.

`MARKET_AGGREGATE`
: A provider's calculated market value based on its underlying marketplace data.

`PRICE_GUIDE`
: Published guide/trend/period-average value.

`ACTIVE`
: Current asking price/listing. Useful for availability and competitive bounds, but intentionally much lower weight than sold evidence.

## Identity and comparability

A price is only useful if it is for the correct item.

Provider mappings therefore attach external product/variant IDs to the canonical `catalogue_products` record.

Pricing then filters observations against physical inventory characteristics:

- exact canonical product/printing/variant mapping
- raw condition
- grading company and grade
- language
- sealed/unsealed state

A known mismatch is excluded. Missing non-critical source metadata may be allowed at a reduced evidence weight. Missing grade information is not accepted for a graded target.

## Currency

Every observation retains:

- original amount
- original currency
- original shipping where available
- GBP-normalized amount
- FX rate used to perform that historical normalization

This makes every historical recommendation reproducible even if exchange rates later move.

## Robust pricing algorithm v1

### 1. Filter comparable observations

Reject wrong language, wrong grade, wrong condition, wrong sealed state, wrong canonical mapping, non-positive prices and stale/unusable evidence.

### 2. Recency weight

Newer evidence matters more. V1 uses exponential decay with different half-lives:

- sold transaction: 21 days
- market aggregate: 7 days
- price guide: 7 days
- active listing: 3 days

### 3. Evidence weighting

Base evidence quality:

- SOLD: `1.00`
- MARKET_AGGREGATE: `0.85`
- PRICE_GUIDE: `0.75`
- ACTIVE: `0.35`

This is multiplied by source reliability, recency, exact-match quality and any real sample-size metadata supplied by the provider.

### 4. Outlier handling

When a source has at least five comparable observations, extreme prices are filtered with Median Absolute Deviation (MAD). The guard is deliberately broad so natural TCG volatility is not mistaken for bad data.

No simple arithmetic average is used.

### 5. One estimate per provider

Each provider produces its own robust weighted-median estimate first.

This is important: 100 active listings from one provider must not drown out a separate provider simply because it returned more rows.

### 6. Cross-provider market value

The final Market Value is a weighted median of the per-provider estimates.

The engine stores the per-source estimates in the pricing snapshot so the result is explainable.

### 7. Confidence

Confidence combines:

- provider diversity
- depth of evidence
- recency
- evidence quality
- disagreement/volatility between providers

Low confidence does not produce an automatic price change.

## Outputs

Every calculation may produce:

- `Market Value`
- `Recommended Retail Price`
- `Quick-Sale Price`
- `Target Acquisition Price`

The multipliers are configurable per owner through a pricing policy and are versioned/audited.

Initial defaults:

- Retail: `1.00 x Market Value`
- Quick-sale: `0.92 x Market Value`
- Target acquisition: `0.70 x Market Value`

These are policy defaults, not hard-coded market facts, and can be changed after real trading data shows better targets.

## Auto-repricing guardrails

Auto repricing is disabled by default.

A recommendation is blocked from automatic publishing when any configured guard fails, including:

- confidence below `0.80`
- fewer than two independent sources, unless one source has sufficient sold depth
- volatility above `20%`
- recommended price at/above the high-value review threshold (initially `£500`)
- proposed move above `10%` from the current store price
- price movement too small to justify storefront churn (initially below both `£1` and `2%`)

Blocked changes enter Action Required rather than changing a customer-facing price.

A high-value threshold is configurable. Expensive items should remain human-reviewed even if the statistical confidence is high.

## Shopify integration later

When Shopify is connected:

1. Pricing engine creates an immutable snapshot.
2. Snapshot updates the inventory's current `market_value_minor` and `recommended_retail_minor`.
3. Pricing policy decides whether the recommendation can be automatically applied to `store_price_minor`.
4. Every store-price change is audited with old/new values and the snapshot that justified it.
5. The Shopify adapter syncs the authoritative `store_price_minor` to the exact physical Shopify variant.
6. Failed Shopify updates enter Action Required and are retried idempotently.

Shopify never recalculates the price.

## Scheduling

Do not continuously hammer providers.

Expected production cadence:

- Cardmarket daily file ingestion after its published refresh
- aggregate market APIs once or a few times daily depending terms/rate limits
- active eBay listing refresh more frequently only where permitted and useful
- pricing recalculation after new observations arrive, plus an overnight full pass

n8n may schedule these API calls, but all normalization and pricing rules stay in FastAPI/PostgreSQL.

## Failure behaviour

The system fails closed:

- unavailable provider -> use remaining evidence, lower confidence
- invalid FX conversion -> observation rejected/quarantined
- duplicate source record -> idempotent rejection, not a second comp
- ambiguous source mapping -> Action Required
- no comparable evidence -> no new price
- source disagreement -> confidence decreases / Action Required
- extreme move -> no auto publish
- Shopify sync failure -> database price remains authoritative; Action Required created

Historical observations and pricing snapshots are immutable.
