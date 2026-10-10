# Catalogue market continuation — 10 October 2026

## Handoff verified

The latest work chat left starter matching deploying and the detailed refresh incomplete. PR #566 deployed successfully as `2267946c8c3cc73e42113cab0f5eef1460f74e46`; Railway deployment `d6001a3d-c949-4254-8f10-8df8b347aa4c` reached SUCCESS. Its revision-6 reference receipt completed at 12:53:20 UTC without provider failures.

The 12:53:54 coverage receipt reports 29,851 priced card references out of 69,538, plus 2,725 priced sealed references out of 3,879. All references have identifying/source fields. These figures are independent of the 510 physical items (324 with market values). The last healthy Shopify heartbeat found no publication or selling-price candidates. A separate database comparison found no difference between linked recorded Shopify prices and approved inventory Store Prices; this alone is not a fresh remote Shopify read-back.

The user's agreed policy remains: refresh the whole reference database daily; synchronise approved For Sale stock promptly; preserve seller asking prices. Market values and seller Store Prices are separate. The Brand Redesign launch hold remains in place.

## Defects and repair

Dragon Ball Masters' official `Series 1` through `Series 9` booster titles failed a parser that accepted only letter/number prefixes. Later releases frequently have no Cardmarket `DBS Set` product even though ordinary booster/box products explicitly identify their expansion. Both omissions prevent trustworthy existing guides from reaching the shared catalogue.

The repair accepts the actual numbered booster-title form and identifies expansions from full ordinary booster/box titles and matching category IDs. Regional, collector, release-event and prerelease qualifiers are retained; they cannot silently become base releases. Every source identifying the same release participates in ambiguity detection, so contradictory expansion IDs block a match.

Fusion World supplemental references use explicit `MANGA BOOSTER NN [SBNN]` / `STORY BOOSTER NN [STNN]` labels with agreeing numbers and the provider's `[Fusion World]` marker. Single-card collector numbers must match exactly. Multiple cards or marketplace products, including unpriced candidates, still block a match. Supplemental and starter guides remain excluded from physical-copy valuations because finishes/reprints require their own evidence.

The coverage query previously counted bulk guides after an identity change even though the browser correctly hid them. It now applies the same identity check while retaining the record in the full denominator.

Reference revision 7 runs through the existing worker. Existing detailed Pokémon checks are reused; no cache reset or new worker is needed. Source dates, EUR/ECB provenance, immutable history, physical-copy safeguards, owner boundaries, seller prices and Shopify approval rules remain intact.

## Read-only replay

Replay inputs: all 17,889 English One Piece/Dragon Ball reference rows and Cardmarket's own game-13/game-18 singles, non-singles and price-guide exports. The Dragon Ball guide is dated `2026-10-10T02:49:01+02:00`; ECB conversion is 0.84763 GBP/EUR effective 9 October. The replay invokes the actual matcher and quote normaliser without writing the database.

| Reference group | Previous matches | Repaired matches | Additional priced references |
|---|---:|---:|---:|
| Dragon Ball Masters | 1,210 | 2,797 | 1,587 |
| Dragon Ball Fusion World | 631 | 730 | 99 |
| Total Dragon Ball | 1,841 | 3,527 | 1,686 |

Every prior match retains its marketplace product ID. All 1,686 additional matches have usable current GBP guides. The 99 supplemental guides are 52 Manga Booster 01 and 47 Manga Booster 02 references. Story Booster parsing is tested but no recovered live Story Booster guide is claimed.

Example: Manga Booster 01 Son Gohan : Childhood, official printing `583201:FB01-088_p2`, collector `FB01-088`, maps to Cardmarket product `831639`, expansion `6171`, foil trend EUR 0.05 / GBP 0.04. This is a labelled mixed-language reference, not an English Near Mint sold transaction or an instruction to sell at that amount.

## Release verification

Local verification passed 4,995 backend tests and every dashboard suite, including 39 catalogue interaction scenarios. Added regressions cover numbered releases, packaging category errors, contradictory expansions, collectors/regional/event packs, supplemental code mismatches, wrong numbers, wrong games, duplicate/unpriced alternatives and physical-copy exclusions. The actual PostgreSQL maintenance test now verifies that an identity-changed guide disappears from both displayed price and priced coverage without removing the reference.

[PR #567](https://github.com/pulltheorytcg/drop-rate-backend/pull/567) passed all four CI workflows / six jobs on exact head `314bb71f452c7d94d22c3cdf27d87255c944bfba`, including Catalogue maintenance persistence, Independent catalogue valuations and Live market persistence against real PostgreSQL. It merged as `926745d2186ea37429601fa48c9c78fc8e6df257`. Railway deployment `01247982-7743-422c-929f-9d5faf9c1bd2` reached SUCCESS at 13:29:36 UTC. The unchanged pre-deploy sequence passed all 4,995 tests and configured financial checks; the existing sold-source probe still reports its quota limit. Readiness returned 200, and unauthenticated catalogue coverage access returned 401. No infrastructure settings or schema were changed.

The revision-7 reference receipt completed at 13:32:37 UTC with zero provider failures. It rechecked all 23,770 English Pokémon references (9,258 broad catalogue guides), all 4,527 English One Piece references (2,037 guides), and all 13,362 English Dragon Ball references (3,527 guides). Completed detailed Pokémon cache work was reused. Post-refresh production coverage, calculated using the deployed coverage query, is:

| Reference group | Total cards | Priced cards |
|---|---:|---:|
| Pokémon English | 23,770 | 16,524 |
| Pokémon Japanese | 13,006 | 9,449 |
| One Piece English | 4,527 | 2,037 |
| One Piece Japanese | 4,480 | 0 |
| Dragon Ball Masters English | 9,002 | 2,797 |
| Dragon Ball Fusion World English | 4,360 | 730 |
| Dragon Ball Fusion World Japanese | 3,227 | 0 |
| Naruto Bandai Legacy, language unspecified | 4,487 | 0 |
| Naruto Kayou, language unspecified | 2,679 | 0 |
| **All card references** | **69,538** | **31,537** |

The increase is exactly 1,686 cards. Sealed coverage remains 2,725 / 3,879. All card and sealed identifying/source fields remain complete. These are current query results after the refresh; the earlier stored coverage receipt at 13:29:43 UTC predates completion.

The actual Seller Hub `product_query` was run read-only against production for the following references. All four had no guide before refresh, and all have zero owned copies. Each now returns source `CARDMARKET_BULK_SINGLES`, showing that guide availability is independent of inventory:

| Card | Exact provider printing | Cardmarket product | GBP guide |
|---|---|---:|---:|
| Destructive Terror Champa, BT1-004 | `428001:BT1-004.png` | 316508 | £0.31 |
| Metamorphic Android Cell, BT26-139 | `428026:BT26-139.png` | 792115 | £420.59 |
| Son Gohan : Childhood, FB01-088 | `583201:FB01-088_p2` | 831639 | £0.04 |
| Son Goku : Childhood, FB06-119 | `583202:FB06-119_p2` | 859266 | £122.98 |

These are explicitly labelled mixed-language/condition references with original source evidence, not exact physical-copy sold valuations. Automated dashboard coverage passed, but no fresh signed-in browser or real-iPhone acceptance has been performed during this continuation.

The physical Cardmarket receipt completed at 13:33:05 UTC: 463 canonical products checked, 244 guide bases, 80 snapshots inserted, 76 inventory rows refreshed, zero provider calls and zero Store Price updates. Exact final comparison against all 510 baseline items confirms zero owner/Store Price/status changes, zero changed market/recommended amounts among previously valued copies, and zero removed inventory rows. Three previously unvalued copies gained eligible estimates, so physical coverage is now **327 / 510**. The 76 refreshes are not 76 new valuations.

Shopify's connected shop was verified as Drop Rate (`fqu56y-hm.myshopify.com`, GBP). Eight active products, two per game, were read directly from Shopify; all matched their linked variant, exact inventory SKU and approved Store Price. The production database records zero linked selling-price differences. The last worker heartbeat at 13:26:16 UTC is COMPLETE with zero candidates/failures; no artificial listing change was made to manufacture a sync. Existing immediate post-approval processing, the minute recovery sweep and the daily 03:00 Europe/London catalogue schedule remain in place. These remote samples do not claim an exhaustive remote-price audit.

## Remaining work

There are still **38,001 card references**, **1,154 sealed references** and **183 physical inventory copies** without usable values. Gaps include ambiguous parallel/promo printings, Japanese One Piece/Fusion World and Naruto without a supported exact-source mapping. Digital Pokémon Pocket records are not physical cash-market cards. The eBay sold-feed quota is still an independent constraint. These remain unknown in the product; zero priced counts in the audit table mean no usable guide, not a zero monetary value. Full signed-in mobile acceptance remains outstanding. The Brand Redesign launch hold remains in place.
