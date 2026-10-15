# Physical-card market reference coverage — 95% acceptance target (15 October 2026)

## What is being measured

**Customer requirement:** 95% of physical card-printing reference records across the complete Drop Rate catalogue should show a supportable GBP market reference on search, set browsing and inventory, independent of owner/account. This is a global source-coverage target, **not** a pledge that each physical copy has a verified UK sale-based valuation, and not permission to fabricate prices.

The existing `CATALOGUE_COVERAGE` daily receipt now reports a deterministic `summary.coverage_target`:
- `eligible` physical reference identities (digital Pokémon Pocket excluded).
- `priced`, `missing`, `coverage_percent`, and `minimum_priced = ceil(0.95 * eligible)`.
- `additional_needed = max(0, minimum_priced - priced)` and exact `target_met`.
- Per game/language cohort: priced, missing, coverage, additional needed and target met.
- The priced sources are **CURRENT GBP references or explicitly labelled source guides**. `US_CONTEXT_ONLY`, missing, stale, disputed and digital entries do NOT count.
- No artificial low-price floor or invented `market_value_minor`. No pricing, stock, financial, media, identity or provider access mutations.

Existing pricing adapters/cache → Supabase reference prices → deterministic FastAPI coverage aggregation → existing daily `CATALOGUE_COVERAGE` report. No new service, schema, n8n workflow or user-facing paid feature.

## Live audit — 15 October 2026

Read-only production query using the currently deployed coverage logic:

| Cohort | References |
|---|---:|
| Physical card-printing references | 67,060 |
| Eligible with priced GBP reference / labelled guide | 40,443 (60.31%) |
| Unpriced physical references | 26,617 |
| Prices needed to reach 95% | **23,264** |
| Minimum required priced references | **63,707** |
| Excluded digital Pocket references | 2,480 |

Missing physical references split into **13,064 SOURCE_ACCESS_REQUIRED**, **9,358 PROVIDER_MAPPING_REQUIRED**, **4,167 EXACT_QUOTE_UNAVAILABLE**, **28 US_CONTEXT_ONLY**. The source-access cohort includes 7,166 legacy/Kayou Naruto printings, 3,056 Japanese One Piece and 2,842 Japanese Fusion World.

These counts are a snapshot, not projected recoveries and not additional source prices. All 9,358 mapping gaps could be resolved and 4,167 missing quotes found, yet the global target would remain unmet without more permitted new source data. Since Naruto alone represents 7,166 unpriced references, and total permissible missing at 95% is 3,353, **at least 3,813 Naruto references must receive real eligible evidence** even if every other physical reference were priced.

## Implementation sequence for actual price growth

1. **Data-mapping repairs in existing feeds:** prioritize 9,358 English One Piece / Dragon Ball exact-print mappings. Use independent official set/number/rarity/finish and CardTrader↔Cardmarket cross-identifiers where available. Log collisions and stop; never guess `V1/V2`, rarity or parallel art by price/order. Preserve current cross-language safeguards. Measure recovered *unique live priced rows* after a complete scheduled run.
2. **Existing source gaps:** 4,167 Pokémon printings have no eligible exact quote. Check permitted full source fields and finish mapping, distinguishing source absence from a parser failure. Never give a root product price to the wrong Japanese or foil version.
3. **New commercial source eligibility:** 13,064 printings need sources that the connected adapters do not currently support. Before implementing a new provider or spending money, run a bounded, read-only exact-sample test with clear commercial-display, attribution, retention, provider-terms and language/region permission. Prioritize Naruto because omitting Naruto makes 95% mathematically impossible. A US ACTIVE asking price is **not** a UK sold-market valuation.
4. **Live verification:** require exact-identity coverage, timestamp and positive GBP amount, source provenance, separate graded/condition values, stable inventory/owner/Store Price checksums, full backend/real PostgreSQL/browser tests, Railway success, signed-in smoke, and honest shortfall reporting.

## Failure points and tests

Source/API quota exhaustion, revoked display rights, same-number parallel ambiguity, regional/language contamination, out-of-date price guides, and free database capacity can all destroy the reliability of apparent coverage. All fail closed: preserve historical data, retain missing status, and do not promote false prices.

New regression suite `tests/test_catalogue_coverage_target.py` checks live-sized count arithmetic, exact threshold without percentage-rounding loopholes, digital exclusions, US-only unpriced evidence, zero-card case and per-language breakouts. No live data is mutated.

## Release discipline

A coverage-target calculation alone does not raise market coverage from 60.31% to 95%. The `target_met` property must remain false until source-derived, verified live coverage actually reaches at least 63,707/67,060 (or the recomputed 95% threshold when the catalogue changes). Existing storefront publish gates are separate; do not infer approval from this metric.
