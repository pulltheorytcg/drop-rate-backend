# Pricing recovery — verified live results, 13 October 2026

The deployed repairs recovered **5,056 additional GBP reference prices/guides**. Coverage rose from **33,972 to 39,028 of 69,538 card reference records**. This is a verified improvement, **not completion of pricing for every card**. All counts are shared catalogue references, independent of an owner's stock. These source guides are not individually verified sold, graded or condition-specific valuations.

## Current database position

| Measure | Before this session | Verified after revision 18 |
|---|---:|---:|
| All card reference records | 69,538 | 69,538 |
| Current supported GBP references/guides | 33,972 | 39,028 |
| Records without a supported GBP value | 35,566 | 30,510 |
| Digital Pocket records within that gap | 2,480 | 2,480 |
| Physical reference denominator | 67,058 | 67,058 |
| Physical references without a supported price | 33,086 | 28,030 |

The all-record missing rate is now **43.88%**. The physical-only missing rate is **41.80%**. The 2,480 digital Pocket records were not deleted, priced or counted as recoveries; physical resale pricing is explicitly not applicable.

| Game | Language | Physical references | Priced | Missing |
|---|---|---:|---:|---:|
| Dragon Ball Fusion World | English | 4,360 | 1,152 | 3,208 |
| Dragon Ball Fusion World | Japanese | 3,227 | 383 | 2,844 |
| Dragon Ball Masters | English | 9,002 | 4,020 | 4,982 |
| Naruto Bandai | Unknown | 4,487 | 0 | 4,487 |
| Naruto Kayou | Unknown | 2,679 | 0 | 2,679 |
| One Piece | English | 4,527 | 2,123 | 2,404 |
| One Piece | Japanese | 4,480 | 1,424 | 3,056 |
| Pokémon | English | 21,290 | 20,472 | 818 |
| Pokémon | Japanese | 13,006 | 9,454 | 3,552 |
| **Total** | | **67,058** | **39,028** | **28,030** |

English physical Pokémon coverage is **20,472/21,290 (96.2%)**.

## Fixes and actual gains

| Release | Repair | Verified new priced reference records |
|---|---|---:|
| [PR #627](https://github.com/pulltheorytcg/drop-rate-backend/pull/627) | Exact Pokémon EX / Dragon Ball release-title aliases and One Piece PRB packaging identities | 758 |
| [PR #628](https://github.com/pulltheorytcg/drop-rate-backend/pull/628) | Fusion World repeated character names resolved by exact distinct collector numbers | 422 |
| [PR #629](https://github.com/pulltheorytcg/drop-rate-backend/pull/629) | Read-only verification of the existing CardTrader identity connection | 0 |
| [PR #630](https://github.com/pulltheorytcg/drop-rate-backend/pull/630) | Pokémon numeric level labels and explicit CardTrader number/Cardmarket product-ID links | 3,532 |
| [PR #631](https://github.com/pulltheorytcg/drop-rate-backend/pull/631) | Both official Masters leader faces matched to one exact combined-name product | 344 |
| **Total** | | **5,056** |

The 344 leader records represent **172 two-sided card identities**, not 344 separate physical cards. The conservative replay counted 314 positive normal-trend candidates; production also found eligible foil-field prices for the remaining 30 records. Every new leader quote carries both official face IDs and is explicitly excluded from physical stock valuation.

Fixes run in the existing daily maintenance pipeline. No new subscriptions, credentials, services or workflows were introduced.

## Remaining evidence requirements

| Current classification | Physical records | Concrete next requirement |
|---|---:|---|
| Source access / coverage required | 13,066 | Eligible exact-print pricing for Naruto Bandai (4,487), Naruto Kayou (2,679), Japanese One Piece (3,056) and Japanese Fusion World (2,844). Existing connected adapters do not have qualifying quotes for these rows. |
| Exact provider mapping required | 10,594 | Confirm the exact English Masters (4,982), Fusion World (3,208) and One Piece (2,404) product/printing. Parallel art, promos, reprints and duplicate source IDs cannot be chosen by name, price or list order. |
| Exact usable quote unavailable | 4,342 | Eligible quotes and variant identities for 790 English and 3,552 Japanese Pokémon references. |
| US context only | 28 | Supported UK/GBP reference evidence; the existing USD context alone does not qualify as a UK market value. |

These are operational classifications, not proof that a new paid feed will cover all remaining cards. Measure coverage and confirm permitted marketplace display before committing to any provider.

A read-only source check illustrates the Pokémon distinction: Japanese E1-001 and PCG4-001 return no root prices or variant marketplace mappings. SV11W-001 and M2-001 expose root aggregate prices, but no variant-level marketplace IDs or prices. These samples were not used to assign unsupported finish-specific prices. No English prices were copied to Japanese cards.

The current source feeds also have no positive usable regional quotes for Japanese Fusion World FB06–FB11 in this pass. More refresh calls cannot create missing source evidence. Generic Naruto asking-price lists, different Naruto game lines, US-only listings and unlicensed datasets were not substituted for qualifying values.

## Verification

- Final code: `9a7096e498c59019bdd2a57c750a46a7655eac1c` (PR #631).
- All four applicable CI workflows passed: backend checks, catalogue maintenance persistence, live market persistence and independent catalogue valuations.
- Full local suite: **5,750 passed**, one existing dependency deprecation warning.
- Railway deployment `3904737b-3d75-463d-b3b4-1f238a52cc13`: **SUCCESS**.
- Live readiness returned `status=ready`, `database=connected` after revision 18 completed.
- `REFERENCE_PRICES` revision **18**: **COMPLETE**, **2026-10-13 18:06:15.952883 UTC**. No provider failures; zero leader-pair conflicts.
- Source-aware coverage was independently queried after completion. It validates current source dates and original reference identities, rather than counting populated cache rows blindly.
- Leader quotes remain dated **2026-10-12 00:47:48 UTC**, not falsely redated to their import time.
- Physical inventory remains **613 items / 327 valued**.
- Ownership/Store Price/status fingerprint remains `820fee0063fe48d9e4a774b4b9f98301`.
- No ownership, seller Store Price, stock status, Shopify publication or launch changes.

All-card pricing remains incomplete until the missing exact identities and eligible pricing evidence are available. Missing values remain explicitly unavailable; no placeholder zeros or invented prices were added.
