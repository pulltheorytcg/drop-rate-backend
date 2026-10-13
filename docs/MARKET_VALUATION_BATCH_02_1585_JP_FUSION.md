# Market valuation recovery — high-throughput batch 02 (FB02–FB11)

Date: 13 October 2026.

## What / why / connections

Batch processing replaces one-set-at-a-time PRs with a single existing-source pass covering **1,585 Japanese Dragon Ball Fusion World reference identities across ten FB releases**. There are **1,263 independently published base-print candidates** in those ten official Japanese catalogues, plus 322 parallel/alternate entries not eligible for base-guide inheritance.

**Source:** existing first-party Cardmarket game-13 singles, nonsingles and daily price-guide files, already consumed by `dragon_ball_market.refresh_dragon_ball_prices`. There is **no new provider, scraping, account, paid API, Railway service, n8n flow or database schema**. All 10 sets' reference identities are considered in one pass using the same bulk downloads and EUR/GBP ECB conversion as before. Existing `REFERENCE_PRICES` job revision **11 → 12** triggers the pass.

Existing immutable `tcg.reference_market_prices` remains the sole persistence target. The global catalogue/seller browser consumes its source-qualified GBP reference/guide, not per-owner copies. No inventory owner, acquisition cost, Store Price, payout, settlement or Shopify change.

## Source evidence and realistic throughput

The official Cardmarket public file snapshot dated 11–12 October was replayed read-only. It shows distinct Non-English/Asia Region Legal marketplace expansion IDs separate from English expansions for FB02–FB10 and a regional FB11 entry. **However, source availability is not quote availability.** At that snapshot:

| Release | Japanese reference records | Cardmarket regional expansion | Source data issue |
|---|---:|---|---|
| FB02 Blazing Aura | 163 | 5767 | Positive trends available; region identified by booster BOX |
| FB03 Raging Roar | 163 | 5903 | Positive trends available |
| FB04 Ultra Limit | 158 | 5906 | Positive trends available; region identified by booster BOX |
| FB05 New Adventure | 154 | 6076 | Positive trends available |
| FB06 Rivals Clash | 143 | 6523 | Regional release listed, but no singles in the regional expansion |
| FB07 Wish for Shenron | 158 | 6524 | No regional-expansion singles |
| FB08 Saiyan's Pride | 158 | 6525 | No regional-expansion singles |
| FB09 Dual Evolution | 164 | 6526 | No regional-expansion singles |
| FB10 Cross Force | 162 | 6620 | No regional-expansion singles |
| FB11 Brightness of Hope | 162 | 6785 | Region has listings but no positive-price `trend`; provider spelling differs |

Total **1,585 records processed**; *about 300 potential positive product-price matches* at most **before official cross-checklist validation**, not 1,585 new prices. The database-wide 33,096 / 69,538 GBP reference coverage is the pre-release baseline. Genuine 1,000–2,000 **new values** per batch is not possible from this source slice until more eligible price evidence exists; do not falsely label a processed record as priced.

## Guardrails and source limitations

1. Each official English/Japanese Bandai base-print pair must have its exact published set ID, original language-specific set title, provider ID `set-id:FBnn-NNN` and same independent card number. Reject alternative art, `_pN`, promotions, reprints and missing identities.
2. The independently discovered Cardmarket English and Non-English/Asia Region Legal booster or booster-box packaging products must point to different *unique* marketplace expansion IDs. A conflicting expansion anywhere in the source makes that release ineligible.
3. Exactly **one** marketplace single with the complete official English card name and printed card number must match that separate regional expansion. Unpriced duplicates still block automatic price selection; never choose the cheapest/first/priced listing.
4. Require a fresh positive price `trend`, correct product/category IDs and original EUR→GBP ECB FX evidence. No data means **no market value**, not £0, £1 or the English price.
5. Output source `CARDMARKET_BULK_SINGLES`, `MIXED_NON_ENGLISH_REFERENCE`, `physical_language_confirmed=false`, `physical_valuation_eligible=false` and `condition_specific=false`. These are labelled **Non-English regional guides (Japanese language NOT verified)**, not verified Japanese completed sales or graded values.
6. The existing worker skips unpriced Japanese sources without overwriting existing records. All historical quote observations remain immutable.
7. The per-set receipt reports `checked`, `base_candidate_count`, `unique_market_matches`, `source_trend_present` and **`priced`** separately, plus batch totals. This prevents processing-volume claims being confused with actual recovered values.

## Testing and acceptance

- Source-contract unit tests reproduce public Cardmarket FB02/FB03/FB04/FB05 marketplace expansion and product IDs; fixture sources are independent of prices.
- Full **1,585 Japanese references / 1,263 base candidates** synthetic stress fixture proves large-batch processing and exact printed-number separation; this is capacity testing, not a promise of 1,263 commercial prices.
- More than 20 negative false-match variants plus 512 deterministic randomized market collisions.
- Full repository Python, dashboard, source regression and real restricted-Postgres pricing/coverage tests.
- Release only on green exact-head CI, Railway terminal SUCCESS / readiness 200, existing `REFERENCE_PRICES` revision 12 COMPLETE and post-write Supabase per-set readback, with unchanged owner/Store Price/status fingerprint.
- If a provider is missing/rate-limited, never erase historical source observations, never invent a quote. Rollback via normal GitHub revert; no database schema rollback.

## What is required for consistent 1,000–2,000 **new values** per batch

Batch scheduling alone cannot create data. After this ten-set technical batch, prioritize **high-yield real-price sources**: official/licensed Cardmarket printing-level catalogue identities and confirmed eBay sold-data quota/entitlement, or a written commercial feed agreement that covers Japanese One Piece/Fusion World and Naruto. A commercial Collectr pricing feed is not currently licensed, and market-name similarities do not justify importing its data. Measure source coverage first, and set a batch's expected newly valued yield before launching its code.

This milestone remains incomplete until newly priced counts actually rise in production. No follow-on Batch 03 is bundled in this branch.
