# Market-data coverage — Batch 1: Japanese Dragon Ball Fusion World FB01

Date: 13 October 2026. This is an intentionally small, bounded batch. Do not expand to FB02–FB11 in this PR.

## 1. Building
Reuse existing official Cardmarket game-13 public singles, packaging and daily GBP-converted guide feeds to match *only* Japanese **FB01 Awakened Pulse base printings**, with independent official English/Japanese Bandai checklists.

The provider source has a distinct **Non-English Awakened Pulse Booster [Fusion World]** marketplace expansion (5731) and separate English expansion (5552). The source does not prove the item is specifically Japanese; show it as a **Non-English regional guide (Japanese language not verified)**, not a sold/condition/graded value.

## 2. Why
Production baseline before this batch (read-only):
- 69,538 card references, 33,010 with cached GBP value/guide (47.47%). Japanese Dragon Ball Fusion World: **0/3,227**.
- Official catalogue FB01 contains 140 simple base-print English IDs and 140 Japanese IDs, both independently keyed by release/printed number. Both checklists include additional parallel/promo printings that must remain excluded.
- Existing Cardmarket public game-13 marketplace catalogue has separate **English 5552** and **Non-English 5731** FB01 expansions. An offline study of the provider data found 118 uniquely named/numbered region products and 88 with positive `trend` quotes, *before* filtering against the two official publisher checklists. Do not assume all 88 match or can be published.
- These regional quotes remain weak *reference evidence*, not exact Japanese sold valuations.

## 3. Connections
The new, isolated `dragon_ball_japanese_fb01_market.py` is called from the **existing** `dragon_ball_market.refresh_dragon_ball_prices` daily source adapter. No new provider, host, service, schedule, background queue, schema, n8n workflow or permission. Only exact matched Japanese FB01 reference identities are written to the existing historical `tcg.reference_market_prices`. `REFERENCE_JOB_REVISION` advances from 10 to 11 to run the source pass within the existing routine.

Reference-pricing data is *global*, not owned by a founder; its displayed GBP result is shared across all accounts. Physical inventory owners' acquisition costs, store prices, settlement and Shopify product state are unchanged. Existing owner-backed Cardmarket estimates deliberately reject Japanese regional guide quotes.

## 4. Failure points
- Only literal provider `Bandai Official`, system `DRAGON_BALL_SUPER_FUSION_WORLD`, English set `583001`, Japanese set `584001`, original source-set titles and printed `FB01-NNN` codes may match. Reject suffixes `_pN`, promo identities, other sets, other languages, release-event cards and translated-number-only aliases.
- Unique, corroborated English/Japanese base card and exactly one source product in the separately documented marketplace Non-English expansion; duplicate variants or inconsistent expansion identities must fail closed, including unpriced duplicates.
- Current public guide only, correct GBP/EUR FX provenance, correct price category and exact marketplace product ID. No guessed £0/£1 or invented exact Japanese sale or grade adjustment.
- Provider/FX failures must preserve historical source values and not alter owners, physical prices or Shopify. Empty/ambiguous JP matches do not overwrite a prior Japanese cached quote with null.
- Rate-limited eBay sold-price provider is unaffected.

## 5. Acceptance / tests
- Unit fixtures validate the two regional expansion IDs, official source names, exact original publisher IDs, source limitation labels and the guarded global write.
- 23 negative identity/variant/source-mapping cases + 256 deterministic randomized collisions, plus existing full backend, dashboard and restricted PostgreSQL market tests. 
- Real deployment: exact-head CI passes before merge, Railway production build/readiness success, existing revision-11 REF_PRICES and coverage receipts complete.
- Production read-back must report FB01 Japanese new priced count, total catalogue before/after, missing cards, and exact founder ownership/store-price/status fingerprint before/after. Never count marketplace candidate listings as persisted values.

## 6. Next bounded batch
FB02–FB11 Japanese Fusion World can be considered **after** FB01 proves safe. Naruto and Japanese One Piece unpriced/parallel coverage remain separate, requiring suitable legitimate source data and evidence. Do not deploy new source providers or infer comparable prices from English/base slabs.
