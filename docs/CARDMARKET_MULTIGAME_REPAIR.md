# Multi-game pricing repair — 10 October 2026

The founder requested the remaining pricing failures be fixed and supplied the Phase 2 Operating Manual. This repairs the existing Cardmarket/catalogue pipeline. Pricing remains deterministic in FastAPI/Postgres; no new Railway service, paid subscription, storefront launch or n8n decision logic is introduced.

## Confirmed causes

- Inventory fallback was hardcoded to Pokémon. The 316 newer One Piece reference guides could appear in search but could not produce a physical-copy estimate.
- One Piece bulk pricing excluded every older Punk Records English checklist. The full set data already included rarity, but the importer discarded it.
- Dragon Ball public Cardmarket game-13 exports had no connected reference-price pass. Masters and Fusion World share that export but need separate release and printing identities.
- Japanese translations, unverified provider mappings, ambiguous parallels, slabs and absent source quotes are separate evidence gaps. They cannot be fixed by assigning an unrelated card's value.

Baseline: 510 inventory copies / 251 valued. Owner/Store Price/status fingerprint `ab62e1122c7e51df7a2288288a3c3005`; valued-amount fingerprint `deb7d73c61d3f2b264a3bd85871004d7`.

## Final production verification

PR #563 merged as `6248f03f1820ad8485dfb0b47297f837f1c61860`. Railway deployment `38d759f7-4cf4-4216-b284-015fab10e0f2` is SUCCESS with readiness 200. All four relevant exact-head workflows passed, including the PostgreSQL tests for cached catalogue reads, ownership, physical pricing and both sealed Dragon Ball systems. CI and Railway each passed **4,893 backend tests**. Original deployment commands, financial/social checks, networking and infrastructure configuration are unchanged; nothing is staged.

At 01:24:35 UTC, Cardmarket revision 4 completed all 463 canonical products, found 241 guide bases, inserted eight additional shared snapshots and recovered six more physical copies. The two releases together recovered **73 inventory prices: 251 → 324 of 510**. Exact row comparison preserves all 510 owners/Store Prices/statuses, and every value/recommended-price/snapshot from both the original 251 and intermediate 318 valued copies.

At 01:24:55 UTC, sealed revision 3 completed **3,878 checked / 2,717 priced**, with no provider failures: Pokémon 2,136, One Piece 269, Masters 246 and Fusion World 66. All 312 new Dragon Ball guides from the source replay are persisted. Two additional Pokémon sealed quotes also became available in today's guide. Original source timestamps are 00:48–00:49 UTC, distinct from the refresh completion time. The 01:25:01 UTC coverage audit records all 73,416 card/sealed references. Current priced-card-reference total is **24,928**.

| Game | Valued inventory copies | Pending inventory copies |
| --- | ---: | ---: |
| Pokémon | 177 | 25 |
| One Piece | 134 | 139 |
| Dragon Ball Masters | 13 | 16 |
| Dragon Ball Fusion World | 0 | 6 |
| **Total** | **324** | **186** |

This repairs confirmed ingestion/matching/calculation omissions; it does not claim universal coverage. The remaining identities need exact printing/grade/language evidence or unavailable quotes. The eBay sold-data probe still reports a provider credit/rate limit. Cardmarket aggregates remain labelled reference estimates through the existing v4 engine, with zero invented sales and no automatic publication eligibility. Fresh eBay evidence keeps priority. Seller asking prices are independent. Daily maintenance remains due at 03:00 Europe/London with recovery, and seller-approved Shopify processing remains unchanged. No new paid provider, service or storefront publication occurred. Fresh signed-in/iPhone acceptance remains outstanding.

## Initial production verification

PR #562 merged as `377c571a262332d962c5b9a3bf07b179c0b5f3fc`. Railway deployment `25a62932-d944-428d-bbd8-423e9696682f` reached SUCCESS with readiness 200 and original financial/social pre-deploy checks retained. All five exact-head CI workflows passed; backend CI and Railway each passed 4,874 tests. The catalogue browser's 37 UI scenarios also passed. The applied migration has the intended SECURITY INVOKER/search-path/grant configuration, and security-advisor findings are unchanged from baseline. No fresh authenticated iPhone acceptance is claimed.

The 01:15:51 UTC reference receipt is COMPLETE: One Piece 4,527 checked / 1,823 priced; Dragon Ball 13,362 checked / 1,755 priced (1,124 Masters, 631 Fusion World), zero provider failures. The 01:16:15 UTC Cardmarket calculation is COMPLETE: 463 canonical products checked, 233 guide bases, 69 new shared snapshots and 67 newly valued inventory copies, with zero provider calls and Store Price updates.

Inventory coverage is **318/510**, compared with 251/510 before this repair. An exact comparison of all 510 rows found zero owner/Store Price/status changes, and zero value/recommended-price/snapshot changes among all 251 previously valued copies. An additional pre-refresh snapshot was captured before the new deployment's first worker run, so this does not rely on comparing only aggregate totals.

| Game | Valued copies | Pending copies |
| --- | ---: | ---: |
| Pokémon | 177 | 25 |
| One Piece | 128 | 145 |
| Dragon Ball Masters | 13 | 16 |
| Dragon Ball Fusion World | 0 | 6 |

Remaining stock includes 103 raw Japanese singles, two Japanese sealed products, four slabs, English special/promotional/pre-release printings, conflicting or decorated imported identities, absent exact guides and an explicit review mapping. Fusion World references now have prices; this does not imply every held Fusion World promo has an exact physical-copy match. Trawl/eBay sold-data capacity still reports a credit/rate limit. No paid upgrade or fabricated sold evidence was introduced.

## Sealed and imported-title follow-up

The same investigation found 464 Dragon Ball sealed references, 342 with explicit cross-provider IDs, excluded by the old two-game sealed worker. Extend the existing pass to game 13 for both systems, fetch shared exports once and keep packaging types separate. Current source replay finds 246 Masters plus 66 Fusion World guides. Eleven case/display records whose source category describes a single booster box remain excluded, as do missing IDs and missing prices. These are catalogue guides with mixed-language/condition limitations, not physical-stock asking prices.

Only an exact repeated collector number at the end of an imported card title can be omitted during matching (`Card (OP15-022)`, `Card (022)` or `Card - OP15-022`). A conflicting number, parallel/pre-release qualifier or ambiguous candidate remains blocked. Stored canonical identities are not rewritten. This follow-up uses Cardmarket calculation revision 4 and sealed revision 3; final CI/deployment/production counts are recorded above. Coverage receipts update after a sealed-only refresh.

## Changes and evidence rules

The existing daily pass reads older One Piece English boosters and Dragon Ball Masters/Fusion World bulk guides. Complete release names, game, collector numbers where Cardmarket publishes them, full card names and uniqueness across both checklists establish a match. A duplicate number, conflicting name, alternate printing or regional expansion cannot be resolved through price/order. Masters' export omits collector numbers: both the official name and collector number must identify one official printing and its full release/name must identify one Cardmarket SKU. Normal and foil prices retain separate fields.

The existing v4 guide calculation now supports those exact cached English references. It still scans all canonical products, including unowned ones. Only identity-confirmed, ungraded Near Mint copies of the matching language can receive an estimate. Ordinary One Piece booster bases require matching published rarity/finish; special printings remain reference context. Intrinsically foil Dragon Ball rarities imported as Normal require review. Existing fresh eBay sold values keep priority.

Cardmarket observations stay PRICE_GUIDE, with zero invented sales, capped confidence, original EUR/date/ECB GBP evidence and the mixed-language/condition limitation. Store Price, owners, status and publication eligibility are not changed. Rarity is preserved from the already-downloaded complete One Piece packs.

The additive `cardmarket_multigame_guard` migration keeps SECURITY INVOKER and fixed search paths. Cached catalogue/intake reads and guarded writes check that a bulk quote still belongs to the current reference identity and cache. Review/rejected mappings from any provider block the fallback. Historical quotes and snapshots are retained.

## Checks and rollout

Read-only source replay found 1,823 One Piece and 1,755 Dragon Ball priced references. The initial physical-copy replay identified 63 pending copies before the additional foil-rarity exclusion; this is diagnostic evidence, not a production coverage claim. The pending stock contains some wrong/insufficient identity fields that remain blocked.

Tests cover actual bulk-export shapes, independent normal/foil prices, regional/printing/name/number collisions, stale/future evidence, invalid FX, changed source identities, review status, owner isolation, unowned guides, retries, unchanged Store Prices and eBay priority. Real PostgreSQL exercises the new joins, migration and cached intake. Current-head CI, applied migration, successful deployment and production read-back remain required before reporting live counts.

Initial release revisions: Punk import 2, reference-price job 4, Cardmarket calculation 3. The existing daily schedule and recovery loop perform the refresh; no provider calls are made by the physical-copy calculation. Rollback reverts the worker changes while retaining the additive helper and all historical evidence.

Primary sources: Cardmarket `products_singles_13.json`, `products_nonsingles_13.json`, `price_guide_13.json` and corresponding game-18 exports under https://downloads.s3.cardmarket.com/productCatalog/; Bandai English Masters/Fusion World/One Piece checklists; exact Punk Records full-pack snapshots already used by the reference importer.
