# Market pricing source-integrity hardening — 13 October 2026

## What was built and why

Hardens the existing FastAPI deterministic `calculate_price` v4 engine, rather than introducing another provider, user-specific valuation system, a new database, or AI-based arbitrary price decisions.

**Verified exposure in existing implementation:** fresh marketplace guides and active listings could contribute to a sufficiently high confidence and source-diversity score even without five independent regional sold records. An eBay ACTIVE listing could alone become the UK price anchor. One provider sold record with a large `sample_size`, or duplicate rows, could inflate sold evidence. A single-source sale set could be wildly volatile while the source-level MAD returned zero volatility. Invalid/future/stale evidence could be weighted as current. These are price-integrity issues, especially for grails and graded cards.

## New deterministic rules

- **Only UK eBay SOLD or appropriately regional Cardmarket non-ACTIVE evidence can anchor displayed GBP market value.** US/other country benchmarks may only support confidence, not set GBP price. This preserves Cardmarket estimates as labelled guides, never sold-price evidence.
- Limit evidence windows by type: **SOLD ≤90 days; market aggregates and price guides ≤7 days; ACTIVE ≤3 days**. More than five minutes into the future, invalid timezone, unknown source, unknown observation type, nonpositive/bool/absurd money, partial graded identity, NaN/Inf or invalid sample metrics fail closed. Historical rows are not erased.
- Deduplicate independent sales by **source + provider sale ID**. Conflicting values on one sale ID invalidate that ID rather than picking the highest, lowest or latest. Exact repeated legacy facts are also deduplicated; one SOLD observation always counts as one transaction regardless of a claimed `sample_size`.
- Preserve existing weighted median and MAD outlier rejection. Additionally detect **within-source sold-price dispersion**; otherwise five highly divergent eBay sales produce a misleading `volatility_pct=0` with only one eBay source.
- **At least five independent eligible UK/EU SOLD observations** for auto-publish eligibility; multiple guides or active listings cannot substitute. Any excluded/contradictory evidence or incomplete language/condition matching **blocks auto eligibility** and creates explicit deterministic reasons. A valid guide can still yield a labelled estimate when no exact sales exist.
- Validate all policy multipliers and review thresholds before calculations to avoid nonfinite auto decisions.
- Canonicalise source case and timestamps, cap large non-sold sample weights, and keep original input/historical observations immutable.
- Add a distinct `ruleset_revision=2026-10-13-source-integrity-1` to future pricing evidence, preview responses and calculation results, **without changing the persisted `algorithm_version=drop-rate-market-v4`**. Existing catalogue DB CHECKs and v4 snapshot consumers remain compatible. Historical snapshots are unchanged.

## Connections

Existing normalized provider observations in PostgreSQL → FastAPI price engine → per-owner physical price snapshot/evidence and nonpublishing preview. Provider sale IDs are now carried from both existing `market_observations.source_record_key` and the bounded live eBay comparable `item_id`. Existing Cardmarket snapshots retain original evidence and state a ruleset revision when newly computed. No n8n business rule, schema migration, financial, Shopify, inventory owner or asking price change.

## Failure points and verification

- Missing or stale exact regional comparables: fail closed rather than showing a fabricated value. Restricted Cardmarket guides remain **reference estimates**, not guaranteed English NM sold values.
- Contradictory evidence with the same provider item ID: reject the item, never count it as two sales or use the favourable quote.
- Spike/manipulation, low liquidity and high value: flag manual review and retain auditable computation evidence.
- Regional and cross-language contamination: reject unsupported anchors and grade/language mismatches.
- Ongoing provider credits, access restrictions or exhausted eBay sold-data quota: **not solved by maths**. Existing 37,957 unpriced catalogue references and 286 missing physical inventory values remain explicitly outside this hardening scope until new permitted evidence exists.

Regression suite includes **4,096 deterministic seeded adversarial cases**, duplicate/conflicting provider IDs, inflated sample sizes, stale/future timestamps, unknown/invalid currency evidence, missing condition/grade, active-only UK asks, US-only anchors, independently verifiable five-sale examples, volatility, and NaN or invalid policy configuration. Exact-head GitHub CI must additionally pass full backend, dashboard, source adapters, restricted-Postgres market tests; after merge, verify Railway terminal SUCCESS, readiness 200, no eBay paid social probe, and unchanged owner/Store Price/status fingerprints. Do not claim live success before deployment is checked.

## Commercial limits

Drop Rate cannot guarantee a current correct sold-based price for a printing with no real permitted transaction evidence. No paid TCGGraph source, external Collectr pricing import/redistribution, new scraping or provider access was activated. Raw, graded, language and printing identity always require upstream exact catalogue mapping.

## Rollback

Revert the feature PR and redeploy the previous working main commit. No database/schema rollback. Historical price observations and pricing snapshots remain preserved; do **not** delete them during rollback.
