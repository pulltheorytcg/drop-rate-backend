# Market-value recovery — 5 November 2026

**State:** Read-only production reconciliation verified; capacity/source recovery not released. All figures below are dated, and are not live user-interface acceptance. This document is not permission to purge records, buy a provider, relax the guard, or alter store prices.

## Source-of-truth and evidence

- PostgreSQL/Supabase project `ozrxenrdladkooixutmm` is the authority for physical inventory, ownership, current price records and settlement. Cloudflare R2 is an immutable/versioned source-copy and media/archive layer; a verified R2 backup is **not** an operational PostgreSQL cutover.
- On **5 Nov 18:11 UTC**, `select pg_database_size(current_database())` returned **430,419,091 bytes**. The FastAPI `database_capacity.py` safeguard pauses bulk refresh at **400,000,000 bytes** against a configured **500,000,000-byte** Free-plan boundary. Railway `drop-rate-api-live` reported repeated `CATALOGUE_BULK_REFRESH_DEFERRED` and `CATALOGUE_R2_REFERENCE_MEDIA_DEFERRED` on 5 Nov, including at 16:39 UTC. Do not bypass this guard.
- Last recorded large `REFERENCE_PRICES` job: **3 Nov 22:27–22:39 UTC**, **INCOMPLETE**; `CARDMARKET_VALUES` at 22:39–22:39 UTC was COMPLETE. No evidence that a new bulk reference-price refresh completed on 5 Nov.
- Original SQL physical-card references: **67,217**, of which **39,680** were classed as currently supported *reference pricing* in the 5 Nov 00:12 UTC reconciliation; **27,537** lacked such coverage (**59.03%** supported-reference coverage). This metric includes Cardmarket guides; it is **not** verified sold-market-value coverage and does not include the new R2-first catalogues. At 89%, the original denominator alone would require **59,824** reference prices, **20,144** more than the 39,680 dated receipt, not necessarily sold-grade valuations.
- R2-first imported TCG source printing/finish references: **45,215 Yu-Gi-Oh!**, **3,505 Disney Lorcana**, **153,662 Magic: The Gathering**. Together with the original SQL physical references, **269,599** published TCG source references. These new feeds contain metadata, **not** independently validated market prices or artwork. Riot Riftbound has **no active publication**. Printed/finish records are not distinct owned stock.
- Read-only query on 5 Nov found **133 distinct catalogue IDs** with a `CATALOGUE_EBAY_V4` snapshot dated within seven days (three with a grading-company field). These are **candidate dated snapshots**, **not** 133 newly certified/usable exact-profile UK sold prices; per-copy proof must pass the current strict selector and, for grades, the five-comparable check.
- `reference_market_prices` currently includes **21,007 `TCGDEX_CARDMARKET`**, **10,605 `CARDMARKET_BULK_SINGLES`** and **902 `TCGDEX_CARDMARKET_VARIANT`** priced source rows. A Cardmarket guide is not proof of five UK sales; asking prices, RRP, a converted USD quote or a generic retail recommendation are not sold market values. Do not aggregate counts across reference tables or reuse a mixed-language quote as a physical-copy valuation.
- Original SQL artwork links: **63,901/67,217**, with **3,316 missing URL references**. The approved bounded 380-candidate exact TCGdex repair ended with 380 HTTP 404s and zero substitutions. A graded item must only use its **own** exact authorised `GRADED_SLAB` image, not the raw card reference.

## R2 backup: verified, but no space was reclaimed

At 3 Nov 15:17 UTC, the dedicated Railway `r2-quote-backup-once-20261103` service logged `REFERENCE_QUOTE_BACKUP_COMPLETE` after `R2_RESTORE_VERIFIED`. It read, uploaded, downloaded, checksummed and typed-restored:
- `tcg.reference_market_prices`: **59,693** rows, **1,251,949** compressed bytes, complete per-row source fields;
- `tcg.reference_catalogue_prices`: **27,676** rows, **1,505,401** compressed bytes, complete per-row source fields.

The combined **87,369 source rows** remain in PostgreSQL; the operation reported **0 rows and 0 bytes reclaimed**. Their R2 version is a historical shadow copy from 3 Nov, not fresh market evidence, and must not overwrite newer PostgreSQL values. A separate R2 *delivery publication* was CURRENT at generation **122413** on 5 Nov with counts 59,693 market rows, 27,676 catalogue rows, 3,889 sealed rows, 0 asking rows; published identity and byte parity do not certify provider freshness or legal reuse.

## Recovery sequence (gated)

1. **Capacity choice and preflight.** Prefer a legitimate PostgreSQL capacity expansion **only with founder spend approval**; alternatively build a dedicated, reviewed R2 quote-evidence offload. The latter is NOT a straight export/delete: inventory, shared price selection, catalogue browser, source normalisation, refresh writers, audit, RLS and rollback must first read the same exact identity and verified provenance across storage boundaries. Measure projected DB growth and leave headroom for at least one complete ingestion plus retries. Do not increase thresholds or change schedules just to make green reports.
2. **Offload engineering (if selected).** Implement behind a disabled flag on a test branch, beginning with **copy and read-parity only**. Enumerate all SQL readers/writers and their `quotes` dependencies; provide content-addressed R2 receipts, per-row integrity checks, typed restore tests, load-time failure fallback, and a documented restore procedure. Never delete/compact source SQL until a new complete current backup plus actual staging cutover and signed-in/mobile/desktop parity is independently verified and explicitly authorised. The old 3 Nov backup alone is insufficient.
3. **Resume refresh only when safe.** Once a normal capacity check is below the guard with adequate projected headroom, observe the existing scheduled reference/Sealed/Cardmarket jobs. Reconcile reference IDs, source evidence timestamps, expired vs current, eligible physical values and provider failures. Never refresh by merely changing the evidence date; never silently convert an asking price or internal estimate into `market_value_minor`.
4. **New-game valuation feeds.** For Yu-Gi-Oh!, Lorcana, Magic and, when authorised, Riftbound, select legitimate permitted source/licence per game and region, then exact set/printing/finish/language mapping. Establish UK GBP normalization, source timestamps and outlier screening *before* any coverage claim. Prioritise previously available exact printings and seller inventory. eBay Browse reports active listings, **not** completed-sale prices. Keep third-party Cardmarket and artwork display/redistribution permissions explicit.
5. **Media repair separately.** Check source URL versus transport/mirror failure, then only replace exact reviewed references with permitted, visually verified matches. Do not use alternate-language/edition artwork or another physical copy's slab photo.

## Acceptance and failure tests

- No RRP/retail/asking/model-only amount masquerades as a verified sold-based Market Value. One Market Value field in normal collector UI; source/uncertainty may be explained in details, but no competing Guide Estimate amount. Unknown is null, never zero.
- 5 independent exact-profile UK sold comparisons for graded valuation, with seller/item uniqueness, verified UK location, correct sale-price basis, language, condition, grade and printing.
- Historical evidence remains immutable and retrievable; one-to-one SQL/R2 identity, currency, value, hash, date and owner-scope parity; corrupt/missing R2 object fails closed without cross-item media or valuation substitution.
- Auth/RLS, founder ownership isolation, Shopify Store Prices, settlements and webhook idempotency remain unaffected by read-only recovery. Test a real graded slab and raw counterpart separately.
- Before announcing improvement, publish **source-specific** counts with denominators: original SQL physical references, expanded TCG references, exact current source-backed market references, *separately* guide-only, stale, asking-only and missing; artwork URL counts and actual image-delivery smoke. Tests and production receipts must be timestamped.

## Existing release evidence / unresolved work

- [#912](https://github.com/pulltheorytcg/drop-rate-backend/pull/912): eBay Browse and Cardmarket **provisional** raw estimate, live bounded probes could not meet minimum exact sellers; not a sold-value feed.
- [#913](https://github.com/pulltheorytcg/drop-rate-backend/pull/913): single Market Value presentation and verified original/R2 inventory-media fallback.
- [#914](https://github.com/pulltheorytcg/drop-rate-backend/pull/914): exact own-slab media and stricter graded sold-value evidence.
- [#915](https://github.com/pulltheorytcg/drop-rate-backend/pull/915), [#916](https://github.com/pulltheorytcg/drop-rate-backend/pull/916): expanded catalogue vs original SQL denominator and bounded coverage reads.
- [#881](https://github.com/pulltheorytcg/drop-rate-backend/pull/881): R2 quote source backup prerequisite only; no SQL offload.

**Changes made in this reconciliation:** documentation only. No price writes, provider requests, catalogues, archives, storage deletion, production feature flags, API changes, migrations, images, owner stock or Shopify changes. Live signed-in Market Value/artwork acceptance remains unverified.
