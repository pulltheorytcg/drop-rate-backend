# Pricing recovery — verified live results, 13 October 2026

The deployed repairs recovered **5,232 additional GBP reference prices/guides**, including **176** from the latest pass. Coverage rose from **33,972 to 39,204 of 69,538 card reference records**. This is a verified improvement, **not completion of pricing for every card**. All counts are shared catalogue references, independent of an owner's stock. These source guides are not individually verified sold, graded or condition-specific valuations.

## Current database position

| Measure | Before this session | Verified after revision 19 |
|---|---:|---:|
| All card reference records | 69,538 | 69,538 |
| Current supported GBP references/guides | 33,972 | 39,204 |
| Records without a supported GBP value | 35,566 | 30,334 |
| Digital Pocket records within that gap | 2,480 | 2,480 |
| Physical reference denominator | 67,058 | 67,058 |
| Physical references without a supported price | 33,086 | 27,854 |

The all-record missing rate is now **43.62%**. The physical-only missing rate is **41.54%**. The 2,480 digital Pocket records were not deleted, priced or counted as recoveries; physical resale pricing is explicitly not applicable.

| Game | Language | Physical references | Priced | Missing |
|---|---|---:|---:|---:|
| Dragon Ball Fusion World | English | 4,360 | 1,152 | 3,208 |
| Dragon Ball Fusion World | Japanese | 3,227 | 383 | 2,844 |
| Dragon Ball Masters | English | 9,002 | 4,020 | 4,982 |
| Naruto Bandai | Unknown | 4,487 | 0 | 4,487 |
| Naruto Kayou | Unknown | 2,679 | 0 | 2,679 |
| One Piece | English | 4,527 | 2,123 | 2,404 |
| One Piece | Japanese | 4,480 | 1,424 | 3,056 |
| Pokémon | English | 21,290 | 20,648 | 642 |
| Pokémon | Japanese | 13,006 | 9,454 | 3,552 |
| **Total** | | **67,058** | **39,204** | **27,854** |

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
| **Total** | | **5,232** |

The 344 leader records represent **172 two-sided card identities**, not 344 separate physical cards. The conservative replay counted 314 positive normal-trend candidates; production also found eligible foil-field prices for the remaining 30 records. Every new leader quote carries both official face IDs and is explicitly excluded from physical stock valuation.

Revision 19 increased supported references from **39,028 to 39,204**. Offline candidates (150 Delta Species positive matches and 34 Kalos identities) are not the live net gain: previously covered records overlap and exact-source eligibility still applies. The independently measured gain is **176**, all English Pokémon records. The printed delta symbol, full-checklist identity, edition distinctions and ambiguity guards remain in place. The existing CardTrader bridge completed with zero provider failures and excluded one cross-source conflict.

Fixes run in the existing daily maintenance pipeline. No new subscriptions, credentials, services or workflows were introduced.

## Remaining evidence requirements

| Current classification | Physical records | Concrete next requirement |
|---|---:|---|
| Source access / coverage required | 13,066 | Eligible exact-print pricing for Naruto Bandai (4,487), Naruto Kayou (2,679), Japanese One Piece (3,056) and Japanese Fusion World (2,844). Existing connected adapters do not have qualifying quotes for these rows. |
| Exact provider mapping required | 10,594 | Confirm the exact English Masters (4,982), Fusion World (3,208) and One Piece (2,404) product/printing. Parallel art, promos, reprints and duplicate source IDs cannot be chosen by name, price or list order. |
| Exact usable quote unavailable | 4,166 | Eligible quotes and variant identities for 614 English and 3,552 Japanese Pokémon references. |
| US context only | 28 | Supported UK/GBP reference evidence; the existing USD context alone does not qualify as a UK market value. |

These are operational classifications, not proof that a new paid feed will cover all remaining cards. Measure coverage and confirm permitted marketplace display before committing to any provider.

A read-only source check illustrates the Pokémon distinction: Japanese E1-001 and PCG4-001 return no root prices or variant marketplace mappings. SV11W-001 and M2-001 expose root aggregate prices, but no variant-level marketplace IDs or prices. These samples were not used to assign unsupported finish-specific prices. No English prices were copied to Japanese cards.

The current source feeds also have no positive usable regional quotes for Japanese Fusion World FB06–FB11 in this pass. More refresh calls cannot create missing source evidence. Generic Naruto asking-price lists, different Naruto game lines, US-only listings and unlicensed datasets were not substituted for qualifying values.

## Verification

- Final code: `dc3f8951ac4913af53aa1a0ad93c23f6bb5bea13` (PR #633).
- All nine applicable CI workflows passed, including backend, catalogue/market persistence, independent valuations, seller inventory and book intake/browser checks.
- Full local suite: **5,776 passed**, one existing dependency deprecation warning.
- Railway deployment `153c2c40-94f4-41ef-9c0a-87d50428f907`: **SUCCESS**.
- Live readiness returned `status=ready`, `database=connected`; deployed Seller Hub assets matched the committed files byte for byte.
- `REFERENCE_PRICES` revision **19**: **COMPLETE**, **2026-10-13 22:49:51.645823 UTC**. No provider failures; zero leader-pair conflicts.
- Source-aware coverage was independently queried after completion. It validates current source dates and original reference identities, rather than counting populated cache rows blindly.
- The revision 18 receipt verified leader quotes dated **2026-10-12 00:47:48 UTC**. Original evidence timestamps are retained rather than replaced with the import time.
- Physical inventory remained **614 items / 327 valued** across this deployment. This fresh predeployment baseline had one more row than the earlier revision 18 receipt; this release inserted no production stock.
- Ownership/Store Price/status fingerprint remains `692a601c4d0629871826cc9a3a031708`.
- No ownership, seller Store Price, stock status, Shopify publication or launch changes.

All-card pricing remains incomplete until the missing exact identities and eligible pricing evidence are available. Missing values remain explicitly unavailable; no placeholder zeros or invented prices were added.

Manual comic, graded-comic and manga entry shipped in the same release. See the [Seller Hub book-intake receipt](SELLER_BOOKS_LIVE_RESULTS_20261013.md) for entry points, supported fields and verification scope. This does not introduce automatic comic/manga market pricing.
