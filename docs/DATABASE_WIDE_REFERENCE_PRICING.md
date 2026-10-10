# Database-wide reference pricing

The founder's 10 October correction makes the whole reference database the acceptance scope. Ownership is an overlay; adding, selling or removing an inventory copy must not determine whether a card exists, is searchable or has a reference price.

## Audited scope

Before this change production contains 69,538 card references and 3,879 sealed references. Every card has a provider, provider ID, set ID, name, collector number and source URL. Only 24,928 cards have a cached GBP guide; 44,610 do not. The 463 canonical products used by physical intake are not the full reference catalogue.

The shared browser already reads the reference catalogue independently of ownership. This change fixes actual missing source coverage, makes the card/set reference and marketplace product IDs visible in Product Details, and adds an authenticated `/api/v1/catalogue-browser/coverage` read for all cards and sealed products, grouped by game, language and evidence status.

## New source path

`pokemon_catalogue_market.py` downloads the three existing first-party Cardmarket Pokémon exports once per daily pass. It checks every released English Pokémon reference, including unowned cards. It requires an unambiguous full expansion title, a complete imported release checklist, and exactly one matching name in both checklists. All competing products count, even without a price. Edition, version and number qualifiers are not removed. The public product export does not supply collector numbers: the evidence explicitly says this rather than claiming a number match.

Direct guides use their own `reference_catalogue_prices` cache and the existing immutable quote-history trigger. A successful unmatched refresh clears the old guide; provider/FX failures preserve previous evidence. Source timestamps, source fields, original EUR amounts, IDs, identity and ECB conversion are retained. Current detailed TCGdex variants take display priority; otherwise the independent guide is used. Stale or changed-identity guides disappear from prices but remain in the coverage denominator. A TCGdex miss or outage cannot erase the direct guide.

The read-only replay of all 23,770 English references matched 9,258 guides, including 4,257 previously unpriced references, before deployment. That is a replay, not a production result. No paid provider or service is added.

## Variant repair

TCGdex supplies explicit IDs and prices for some `unlimited`, stamped and other named treatments. The former blanket exclusion discarded them. They are now retained with their treatment label and a distinct `TCGDEX_CARDMARKET_VARIANT` source. Different editions sharing the same marketplace ID and price field are rejected as ambiguous. Distinct exact variants can appear as a labelled reference range.

Named treatments and direct broad guides are not accepted by the physical-copy Cardmarket calculator. They do not confirm a printing, value a slab, change a seller's Store Price or publish stock. TCGplayer remains labelled USD market context. Existing exact eBay UK observations and the v4 physical valuation engine are unchanged.

## Daily operation and limits

Reference job revision 5 triggers the direct catalogue pass and revised detailed-variant fill in the existing daily/continuation worker. Reference refresh revision 3 invalidates prior rejected detailed-variant results. Daily scheduling stays at 03:00 Europe/London; ongoing provider recovery remains bounded. Existing seller-approved Shopify processing is unchanged, and Brand Redesign remains unpublished.

Universal reference identity coverage does not imply a trustworthy price for every record. Japanese One Piece/Fusion World and Naruto still need supported source/printing mappings. English alternate arts with duplicate marketplace names stay unmatched. The Pokémon source also includes digital TCG Pocket releases, which have no physical cash-market valuation. These records must not receive invented prices or be silently removed from the coverage denominator.

Collectr describes combining TCGplayer, eBay, Cardmarket and other markets; its product pages can refresh every one or two days. This implementation uses the same catalogue-first principle, not Collectr's proprietary data or an assertion of identical coverage. Sources: [Collectr pricing explanation](https://getcollectr.notion.site/Everything-You-Wanted-to-Know-About-Prices-f64d490171a549a2bcd1a037e7f74602), [TCGdex pricing FAQ](https://tcgdex.dev/faq), [TCGdex market fields](https://tcgdex.dev/markets-prices).

## Verification and release

Regression coverage includes incomplete releases, duplicate names/products/expansions, unknown language, regional releases, different editions, gender markers, wrong currency/category/ID, invalid prices, stale sources, provider outages, independent-cache fallback and named variants. Real PostgreSQL tests exercise unowned/no-canonical browsing, value sorting, exact-source priority, identity races, stale denominators, immutable history and RLS. UI tests inspect source IDs and named-variant labels with zero owned copies.

Apply the additive generated migration only after current-head CI passes, then deploy the application. Read back the daily receipts and full reference coverage before declaring the live backfill complete. No fresh signed-in iPhone acceptance has been performed in this turn.

## Production read-back, 10 October

PR #565 is merged and application `5b991e9` is running on Railway deployment `ad6fb48b-897c-4771-a69c-14e3c8f63c7a` (SUCCESS, readiness 200). All six exact-head checks passed, including three actual PostgreSQL jobs. CI and Railway each ran 4,929 successful backend tests; all dashboard suites passed, including 39 catalogue-browser scenarios. The additive migration is applied, with forced RLS and no browser-role table reads or API deletes. Security findings are unchanged.

The direct guide cache contains 23,770 checked references and 9,258 priced references. It adds 4,257 previously missing GBP guides. The full card-reference total is now 29,185 priced / 69,538 references at this checkpoint:

| Game | Language | References | GBP guide available |
|---|---|---:|---:|
| Pokémon | English | 23,770 | 16,167 |
| Pokémon | Japanese | 13,006 | 9,440 |
| One Piece | English | 4,527 | 1,823 |
| One Piece | Japanese | 4,480 | 0 |
| Dragon Ball Masters | English | 9,002 | 1,124 |
| Dragon Ball Fusion World | English | 4,360 | 631 |
| Dragon Ball Fusion World | Japanese | 3,227 | 0 |
| Naruto Bandai | Unverified | 4,487 | 0 |
| Naruto Kayou | Unverified | 2,679 | 0 |

All card and sealed references have identifying/source fields. The full coverage receipt counts 73,417 references, including the existing 3,879 sealed references. The detailed revision-3 TCGdex sweep is still running (2,600 checks persisted at read-back); this is not a claim that its full backfill has finished. Read-only current provider replay confirms the repaired unlimited/stamped cases for Base Set Charizard/Pikachu and McDonald's 2012 Servine. The remaining 40,353 card-reference price gaps are not represented as zero or as complete coverage.

Live sample: Unified Minds Dwebble `sm11-10`, collector `10/236`, links to Cardmarket product `387882`, with a £0.20–£4.78 mixed-finish guide and original source timestamp `2026-10-10T00:48:43Z`. This was previously unpriced. It is a reference range, not a condition-specific sold valuation.

The actual served JavaScript hash matches the tested file; cache control is `no-store`. The new coverage endpoint returns 401 without authentication. Owner/Store Price/status fingerprint is unchanged at `7db86dd9fbdb662b3f766ea08c14cee8`, and Railway has no staged configuration. No storefront publication occurred. The original eBay sold-evidence pre-deploy probe still reports a provider credit/rate limit, so this release does not claim renewed sold-feed capacity.

## Starter-release follow-up

The existing One Piece and Dragon Ball adapters omitted starter releases. Exact release-title/category joins identify another 214 One Piece and 86 Masters references in the existing catalogue replay. Regional/translated releases, conflicting expansion IDs, duplicate printings and collector-number mismatches remain excluded. Fusion starter parsing is covered, but the current exact source replay found no additional unambiguous Fusion matches; no extra coverage is claimed there.

Starter reference prices remain excluded from the physical-copy fallback: a deck's leader/rarity finish distribution need not equal a booster's. This follows the catalogue-first scope without silently assigning a reference to someone's physical copy.

Job revision 6 rechecks the shared sources. A clean incomplete page with more records pending now resumes at the next five-minute worker tick. Source/detail failures, incomplete source receipts and interruptions retain the existing one-hour backoff. Completed detail-cache rows are reused, so deployment recovery continues from persisted progress rather than starting the whole database again. Regression tests cover both release-matching collisions and the continuation/failure distinction. This follow-up still requires exact-head CI and live read-back.
