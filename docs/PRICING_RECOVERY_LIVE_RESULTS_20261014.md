# Pricing recovery — verified live results, 14 October 2026

Revisions 21 and 22 recovered **745 additional GBP catalogue guide records**. Independently measured coverage rose from **39,678 to 40,423 of 69,538 card references**. **26,635 of 67,058 physical references remain unpriced (39.72%)**. All-card pricing is incomplete.

The 745 records represent **670 distinct priced products**: 595 ordinary printings plus 150 face records for 75 two-sided leader cards. Both faces belong to the same card and must not be counted as two physical assets. These are shared catalogue guides, not new condition-, grade- or language-verified physical-copy valuations.

## Current database position

| Measure | Before this pass | Verified after revision 22 |
|---|---:|---:|
| All card reference records | 69,538 | 69,538 |
| Supported current GBP guides/references | 39,678 | 40,423 |
| Records without a supported GBP value | 29,860 | 29,115 |
| Digital Pocket records within that gap | 2,480 | 2,480 |
| Physical reference denominator | 67,058 | 67,058 |
| Physical references without a supported price | 27,380 | 26,635 |

The all-record missing rate is **41.87%**; the physical-only missing rate is **39.72%**. Digital Pocket entries remain N/A for physical resale and are not counted as price recoveries. The previous 13 October receipt ended at 39,675; the intervening scheduled refresh added three net references before this pass. Those three are not attributed to these code changes. Verified code-recovery gains across the two receipts total 5,703 + 745 = **6,448**.

| Game | Language | Physical references | Priced | Missing |
|---|---|---:|---:|---:|
| Dragon Ball Fusion World | English | 4,360 | 1,152 | 3,208 |
| Dragon Ball Fusion World | Japanese | 3,227 | 387 | 2,840 |
| Dragon Ball Masters | English | 9,002 | 5,161 | 3,841 |
| Naruto Bandai | Unknown | 4,487 | 0 | 4,487 |
| Naruto Kayou | Unknown | 2,679 | 0 | 2,679 |
| One Piece | English | 4,527 | 2,198 | 2,329 |
| One Piece | Japanese | 4,480 | 1,424 | 3,056 |
| Pokémon | English | 21,290 | 20,647 | 643 |
| Pokémon | Japanese | 13,006 | 9,454 | 3,552 |
| **Total** | | **67,058** | **40,423** | **26,635** |

All non-Masters counts were unchanged during this pass. Sealed catalogue coverage remains 2,726/3,880, with 1,154 missing; this release did not change it.

## Changes and production evidence

- [PR #638](https://github.com/pulltheorytcg/drop-rate-backend/pull/638), worker revision 21: exact Masters release, collector number, explicit rarity and singleton Cardmarket identity from the existing CardTrader connection recovered **595 records**. The independent before/after count was 39,678 → 40,273.
- [PR #639](https://github.com/pulltheorytcg/drop-rate-backend/pull/639), revision 22: exact paired leader faces and explicitly labelled Special Leader Rare versions recovered **150 more face records / 75 products**. The independent count was 40,273 → 40,423. Changed reference rarity now invalidates old quotes on catalogue/recognition reads and blocks stale writes.
- Seller Hub printed-number searches now include exact Masters parallel records such as `BT24-013_PR` when entering `BT24 013`. Printings keep separate identities and prices. Real PostgreSQL tests cover spaced, compact, hyphenated and name searches, value sorting, adjacent-number rejection and rarity correction.
- Both revisions retain ambiguity checks, original source/FX timestamps and reference-only provenance. No suffix order, V1/V2 order, guessed artwork or price is used to select a printing.

Revision 22 code is `3ec3692ff6d95ecfcfd30a781184a3b5f9505410`. Railway deployment `55b50ac6-129b-4eb7-b8af-aed5e64e2910` reached **SUCCESS**. Live readiness returned HTTP 200 with `status=ready`, `database=connected`. All seven final-head CI workflows passed: backend checks, catalogue maintenance persistence, independent catalogue valuations, live market persistence, Seller inventory persistence, shared inventory reference consistency and collection-first confirmation. The full local backend suite passed **5,854 tests**; the final search change also passed the real PostgreSQL and full CI gates.

The production `REFERENCE_PRICES` job ran **06:57:36.454354–07:01:26.380611 UTC on 14 October 2026**, completed at revision 22, and reported **zero provider failures**. The Masters bridge checked 31 releases with 34 requests; 3,841 exact candidates include already covered records. Its 745 recovered/priced rows include the previous revision's 595 plus the new 150 leader faces; **745 is not an additional gain on top of 595**. There were zero cross-source or cross-release conflicts.

Independent quote inspection confirmed **745 reference-only rows / 670 distinct Cardmarket products**, including **150 leader faces / 75 products**, with no mismatched rarity. All 745 have `physical_valuation_eligible=false`, `physical_language_confirmed=false`, and `condition_specific=false`. Every quote retains the actual source evidence date **2026-10-14 00:53:42 UTC**.

The deployed Seller Hub catalogue SQL, queried read-only against production, returned:

| Printed number / printing | Guide | Exact evidence |
|---|---:|---|
| BT24-013 — Super Rare | £0.17 | Cardmarket 762000; CardTrader 282431 |
| BT24-013 — Special Rare parallel | £12.17 | Cardmarket 762001; CardTrader 282434 |
| BT24-001 — Special Leader Rare, Vegeta // Vegeta, Awakened Feelings | £78.88 | Cardmarket 761977; CardTrader 282508; both official face IDs |

The BT24-001 Uncommon printing still returns unavailable: its duplicate printing identity is unresolved. It does not inherit the £78.88 SLR guide. This verifies the shared catalogue query and deployed service; it is not a new signed-in physical-device acceptance claim.

Inventory remains **614 rows / 327 stored positive values**. The owner/status/Store Price fingerprint is unchanged at `de5af2619bdfbc03127b64c179df03c5`, using `md5(string_agg(concat_ws('|',id,owner_id,status,store_price_minor),E'\n' order by id))`. No owner, asking-price, stock-status, Shopify publication, service, subscription or schema changes were made.

## Remaining evidence requirements

| Classification | Physical records | Concrete requirement |
|---|---:|---|
| Source access / coverage required | 13,062 | Eligible exact-print evidence for Naruto Bandai (4,487), Naruto Kayou (2,679), Japanese One Piece (3,056) and Japanese Fusion World (2,840). Existing connected adapters lack qualifying quotes for these rows. |
| Exact provider mapping required | 9,378 | Resolve exact Masters (3,841), Fusion World (3,208) and One Piece (2,329) English printings, including indistinguishable parallels, promos and reprints. |
| Exact usable quote unavailable | 4,182 | Eligible quotes for 630 English and 3,552 Japanese Pokémon references; root aggregate prices without finish-specific identity cannot fill exact variants. |
| US context only | 13 | Supported UK/GBP reference evidence; USD-only context is insufficient. |
| **Total physical gap** | **26,635** | |

These classifications identify missing evidence; they do not establish that another paid feed will cover it. Any additional source needs demonstrated coverage of these exact game/language/printing records and permitted marketplace use before commitment. Generic Naruto retail asks and different Naruto game lines do not price the legacy/Kayou catalogue. Unknown parallel suffixes cannot be mapped to provider V1/V2 by order, and English values cannot fill Japanese references.

The reported user-visible error was not reproduced in the observed live API health and sampled logs. The pricing jobs and persisted data were healthy; the separate confirmed printed-number search defect is now fixed. A page name or screenshot is still needed to identify any other screen-specific error.

Manual comic, graded-comic and manga entry was already shipped separately; see [the book-intake receipt](SELLER_BOOKS_LIVE_RESULTS_20261013.md). This pricing pass does not add an automatic comic/manga catalogue or pricing feed.
