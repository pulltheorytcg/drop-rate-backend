# Pricing recovery — verified live results, 13 October 2026

The deployed repairs recovered **5,703 additional GBP reference prices/guides**, including **471** from the latest pass. Coverage rose from **33,972 to 39,675 of 69,538 card reference records**. This is a verified improvement, **not completion of pricing for every card**. All counts are shared catalogue references, independent of an owner's stock. These source guides are not individually verified sold, graded or condition-specific valuations.

## Current database position

| Measure | Before this session | Verified after revision 20 |
|---|---:|---:|
| All card reference records | 69,538 | 69,538 |
| Current supported GBP references/guides | 33,972 | 39,675 |
| Records without a supported GBP value | 35,566 | 29,863 |
| Digital Pocket records within that gap | 2,480 | 2,480 |
| Physical reference denominator | 67,058 | 67,058 |
| Physical references without a supported price | 33,086 | 27,383 |

The all-record missing rate is now **42.94%**. The physical-only missing rate is **40.83%**. The 2,480 digital Pocket records were not deleted, priced or counted as recoveries; physical resale pricing is explicitly not applicable.

| Game | Language | Physical references | Priced | Missing |
|---|---|---:|---:|---:|
| Dragon Ball Fusion World | English | 4,360 | 1,152 | 3,208 |
| Dragon Ball Fusion World | Japanese | 3,227 | 383 | 2,844 |
| Dragon Ball Masters | English | 9,002 | 4,416 | 4,586 |
| Naruto Bandai | Unknown | 4,487 | 0 | 4,487 |
| Naruto Kayou | Unknown | 2,679 | 0 | 2,679 |
| One Piece | English | 4,527 | 2,198 | 2,329 |
| One Piece | Japanese | 4,480 | 1,424 | 3,056 |
| Pokémon | English | 21,290 | 20,648 | 642 |
| Pokémon | Japanese | 13,006 | 9,454 | 3,552 |
| **Total** | | **67,058** | **39,675** | **27,383** |

English physical Pokémon coverage is **20,648/21,290 (97.0%)**.

## Fixes and actual gains

| Release | Repair | Verified new priced reference records |
|---|---|---:|
| [PR #627](https://github.com/pulltheorytcg/drop-rate-backend/pull/627) | Exact Pokémon EX / Dragon Ball release-title aliases and One Piece PRB packaging identities | 758 |
| [PR #628](https://github.com/pulltheorytcg/drop-rate-backend/pull/628) | Fusion World repeated character names resolved by exact distinct collector numbers | 422 |
| [PR #629](https://github.com/pulltheorytcg/drop-rate-backend/pull/629) | Read-only verification of the existing CardTrader identity connection | 0 |
| [PR #630](https://github.com/pulltheorytcg/drop-rate-backend/pull/630) | Pokémon numeric level labels and explicit CardTrader number/Cardmarket product-ID links | 3,532 |
| [PR #631](https://github.com/pulltheorytcg/drop-rate-backend/pull/631) | Both official Masters leader faces matched to one exact combined-name product | 344 |
| [PR #633](https://github.com/pulltheorytcg/drop-rate-backend/pull/633) | Exact Pokémon Delta Species label normalization and corroborated XY Kalos Starter Set identity | 176 |
| [PR #636](https://github.com/pulltheorytcg/drop-rate-backend/pull/636) | Exact Masters expansion/anniversary/expert releases and One Piece deck-title mappings | 471 |
| **Total** | | **5,703** |

The 344 leader records represent **172 two-sided card identities**, not 344 separate physical cards. The conservative replay counted 314 positive normal-trend candidates; production also found eligible foil-field prices for the remaining 30 records. Every new leader quote carries both official face IDs and is explicitly excluded from physical stock valuation.

Revision 19 increased supported references from **39,028 to 39,204**. Offline candidates (150 Delta Species positive matches and 34 Kalos identities) are not the live net gain: previously covered records overlap and exact-source eligibility still applies. The independently measured gain is **176**, all English Pokémon records. The printed delta symbol, full-checklist identity, edition distinctions and ambiguity guards remain in place. The existing CardTrader bridge completed with zero provider failures and excluded one cross-source conflict.

Fixes run in the existing daily maintenance pipeline. No new subscriptions, credentials, services or workflows were introduced.

Revision 20 increased supported references from **39,204 to 39,675**. The independently verified gain is **396 English Masters** and **75 English One Piece** records. All new guides preserve dated source/FX provenance and remain excluded from physical-copy valuation. The Seller Hub catalogue read path returns previously missing examples: Comrades Combined Vegeta `EX01-02` at **£0.20–£0.53**, and Trafalgar Law `ST10-001` in The Three Captains at **£6.11**. See [the detailed release receipt](SUPPLEMENTAL_RELEASE_PRICE_RECOVERY_20261013.md).

## Remaining evidence requirements

| Current classification | Physical records | Concrete next requirement |
|---|---:|---|
| Source access / coverage required | 13,066 | Eligible exact-print pricing for Naruto Bandai (4,487), Naruto Kayou (2,679), Japanese One Piece (3,056) and Japanese Fusion World (2,844). Existing connected adapters do not have qualifying quotes for these rows. |
| Exact provider mapping required | 10,123 | Confirm the exact English Masters (4,586), Fusion World (3,208) and One Piece (2,329) product/printing. Parallel art, promos, reprints and duplicate source IDs cannot be chosen by name, price or list order. |
| Exact usable quote unavailable | 4,166 | Eligible quotes and variant identities for 614 English and 3,552 Japanese Pokémon references. |
| US context only | 28 | Supported UK/GBP reference evidence; the existing USD context alone does not qualify as a UK market value. |

These are operational classifications, not proof that a new paid feed will cover all remaining cards. Measure coverage and confirm permitted marketplace display before committing to any provider.

A read-only source check illustrates the Pokémon distinction: Japanese E1-001 and PCG4-001 return no root prices or variant marketplace mappings. SV11W-001 and M2-001 expose root aggregate prices, but no variant-level marketplace IDs or prices. These samples were not used to assign unsupported finish-specific prices. No English prices were copied to Japanese cards.

The current source feeds also have no positive usable regional quotes for Japanese Fusion World FB06–FB11 in this pass. More refresh calls cannot create missing source evidence. Generic Naruto asking-price lists, different Naruto game lines, US-only listings and unlicensed datasets were not substituted for qualifying values.

## Verification

- Final pricing code: `e3a2ff802daf361fab748b983785d23d87c29ca0` (PR #636).
- All four applicable CI workflows passed: backend, catalogue maintenance persistence, independent valuations and live market persistence. Earlier Seller Hub/book/browser release checks remain recorded in their release receipts.
- Full local suite: **5,805 passed**, one existing dependency deprecation warning.
- Railway deployment `737c3c71-8901-42a3-a1f7-d434995a0664`: **SUCCESS**.
- Live readiness returned `status=ready`, `database=connected`; the shared Seller Hub catalogue SQL returned the recovered prices and original evidence dates.
- `REFERENCE_PRICES` revision **20**: **COMPLETE**, **2026-10-13 23:32:25.882622 UTC**. No provider failures; zero leader-pair conflicts.
- Source-aware coverage was independently queried after completion. It validates current source dates and original reference identities, rather than counting populated cache rows blindly.
- The revision 18 receipt verified leader quotes dated **2026-10-12 00:47:48 UTC**. Original evidence timestamps are retained rather than replaced with the import time.
- Physical inventory remained **614 items / 327 valued** across this deployment. This fresh predeployment baseline had one more row than the earlier revision 18 receipt; this release inserted no production stock.
- The revision-20 pre/post owner/status/Store Price fingerprint is unchanged at `de5af2619bdfbc03127b64c179df03c5`; its exact recipe is recorded in the detailed release receipt.
- No ownership, seller Store Price, stock status, Shopify publication or launch changes.

All-card pricing remains incomplete until the missing exact identities and eligible pricing evidence are available. Missing values remain explicitly unavailable; no placeholder zeros or invented prices were added.

Manual comic, graded-comic and manga entry shipped previously in PR #633, with category-specific grading choices in PR #635. See the [Seller Hub book-intake receipt](SELLER_BOOKS_LIVE_RESULTS_20261013.md) for entry points, supported fields and verification scope. This does not introduce automatic comic/manga market pricing.
