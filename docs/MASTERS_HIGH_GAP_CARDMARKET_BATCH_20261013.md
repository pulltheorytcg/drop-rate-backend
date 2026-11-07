# English Dragon Ball Masters: high-yield Cardmarket reference recovery — 13 October 2026

## 1. What and why

One bounded recovery across **seven official English Dragon Ball Super Masters releases** that previously had no GBP source prices because their published Bandai set titles are not covered by the generic `Booster -TITLE-` parser. This is a pricing-data coverage repair, **not** a new pricing algorithm, a catalogue identity rewrite, or a provider expansion.

The seven releases are Draft Box 04 Dragon Brawl (428601), Draft Box 05 Divine Multiverse (428602), Draft Box 06 Giant Force (428603), Themed Booster Tournament of Power (428101), Themed Booster World Martial Arts Tournament (428102), Themed Booster Clash of Fates (428103), and Battle Evolution Booster (428201). Combined **902 official reference printing records**, including promos and faces that are explicitly NOT automatically assigned a guide.

## 2. Actual public data and yield measured *before* implementation

Temporary read-only GitHub Action run **38420057987** downloaded first-party Cardmarket game-13 public product singles (13,363 rows; dated 13 October), product nonsingles (712 rows; dated 13 October), and published price guides (14,075; dated 12 October). It replayed the **902 actual existing official Bandai reference records** fetched read-only from Supabase. No market/owner write or price guessing occurred in the replay.

| Official release | Records checked | Unique source products | Positive eligible GBP-guide candidates |
|---|---:|---:|---:|
| Dragon Brawl DB1 | 128 | 85 | **85** |
| Divine Multiverse DB2 | 199 | 156 | **156** |
| Giant Force DB3 | 167 | 122 | **122** |
| Tournament of Power TB1 | 131 | 70 | **58** |
| World Martial Arts Tournament TB2 | 91 | 47 | **38** |
| Clash of Fates TB3 | 88 | 50 | **50** |
| Battle Evolution Booster EB1 | 98 | 49 | **49** |
| **Total** | **902** | **579** | **558** |

The 558 are **read-only source-supported candidates**, NOT the same as a verified production increase. A matching product can still lack a positive quote; the remaining 344 references are ambiguous, unpriced, promos, other printings, front/back faces or otherwise source-unverifiable. Battle Evolution uses its original two-digit `EB1-NN` collector number; most draft/themed sets use three digits. No fabricated or unrelated amount is assigned.

## 3. What connects to what

The isolated `backend/app/dragon_ball_masters_missing_market.py` module is called from the existing `dragon_ball_market.refresh_dragon_ball_prices` worker. It reuses the **same Cardmarket bulk JSON downloads** and ECB EUR→GBP conversion as the existing English Dragon Ball import, writes only `tcg.reference_market_prices` through the existing identity-guarded SQL with immutable history, and exposes owner-independent source references to existing Founder/Seller Hub and catalogue browsing APIs.

Reference job revision **12 → 13** triggers one normal refreshed pass. Every resulting quote remains an explicitly labelled `CARDMARKET_BULK_SINGLES` mixed condition/language **reference guide**, not a verified exact-condition sold comparison or graded price. The deterministic physical price matcher currently excludes these release formats; this batch is reference-only and does not change owner asking prices, cost, balance, settlements, Shopify products or publication.

## 4. Safety and failure cases

- Require the exact original Bandai provider, game, English language, source `set_id` and published release-title string.
- Determine the Cardmarket expansion from **independently published release booster/booster-box/DBS-set/draft-box product labels**, exact category+category ID and a unique expansion. Pre-release, promo, Power Booster, regional foreign variant and unrelated product labels cannot establish release identity. A contradictory expansion invalidates the set.
- Require a unique official *full card name* and **unique collector number within the official release**, considering variants and front/back faces, then require the literal base printing provider ID `set-id:number.png`. Reject `_PR`, alternate promo files, duplicate source names, face variants, regional crossover and wrong collector suffixes. Battle Evolution is explicitly two digits.
- Require exactly **one** matching marketplace single in that expansion, including unpriced duplicate products. A matching marketplace single with a printed collector suffix must match exactly. Duplicate Cardmarket SKU claims across different references invalidate **all** claims, independent of row ordering.
- Only the existing valid Cardmarket category ID, recent price-guide `trend`, and original ECB FX determine the stored amount. No prices inferred from another parallel, condition, owner, asking price or AI.
- Provider failure preserves historical observations; no new API or paid provider. Exact high-value and uncertain visual identity rules remain in existing system.
- Allow old normal reference-match results; contradictory old vs new provider identities invalidate rather than choose the priced product.

## 5. How to verify and roll back

Tests include real public identifiers, failure cases covering wrong release/game/category/print/number, duplicate official variants, back-face collisions, conflicting expansions/marketplace products, provider-ID multi-claim ordering, 2,048 seeded adversarial collisions and a mock worker proving source-only writes. Exact-head full Python and dashboard CI, real restricted PostgreSQL price/maintenance suites, then existing Railway production rollout and database readback.

**Production gate:** `REFERENCE_PRICES` revision **13 COMPLETE**, no source failures, seven-set per-release checked/unique-matched/actual-priced receipts. Compare baseline **33,393 / 69,538** positive GBP references (36,145 missing) to post-release and ensure **613 physical inventory items / 327 valued** and ownership+Store Price+status+catalogue fingerprint `eb57cf3f922ae61fd42128dadd16a0f3` remain unchanged. The 558 is an *expected eligible source-yield*, not a promise before post-write verification.

Rollback by reverting PR and redeploying main; no schema migration or marketplace secret/permission changes. Do not erase historical quote observations. A temporary read-only replay workflow and public checklist fixture are removed before merging.

## Commercial limitations

Even after successful backfill, tens of thousands of cards may lack legitimate current source prices. This is not solved by assigning random values, copying Collectr prices without written permission, or borrowing a base English raw-card guide for a different Japanese/graded/parallel print. A 1,000–2,000 *new price* batch is only possible when the source provider has that many unambiguously attributable legitimate observations; processing batch-size is independent from price evidence availability.
