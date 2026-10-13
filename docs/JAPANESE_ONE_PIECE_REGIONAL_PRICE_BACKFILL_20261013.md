# One Piece Japanese base-print Cardmarket regional guide recovery — 13 October 2026

## Requirement
The entire shared Drop Rate card catalogue (not just physical inventory) needs trustworthy GBP context. For equivalent canonical physical profiles, all accounts must see the same source-priced reference or the same missing-data state. Ownership, costs, Store Price, Shopify publication and payout calculations remain untouched.

## What has been built
Reuse the **existing official public Cardmarket game-18 singles / packaging / daily price-guide feeds** and the existing `REFERENCE_PRICES` worker. A new isolated deterministic adapter only accepts an independently attested pair of **official English and Japanese One Piece base printings**, and a distinct **Non-English / Japanese / Asia Region Legal** Cardmarket market expansion with an unambiguous exact marketplace product ID.

The adapter checks *all* of the following before preserving a price quote:

1. Both publisher records explicitly identify One Piece, Punk Records, and their own English/Japanese languages. Japanese set title must have an official bracketed `【OP-XX】` / `【EB-XX】` code; English set must have the same independently printed `[OP-XX]` / `[EB-XX]` code.
2. Base-print reference ID is literally the printed collector number in **both** official languages. Its release-code prefix must equal the declared set code. No `_pN`, `_rN`, reprints, PRB, promos, impossible/ambiguous collector IDs, alternative art, or a sibling's price.
3. Unique official English counterpart for that code/number, with the **same published rarity** and distinct source-set ID. The English name is used **only to identify the localized marketplace product**; its English market price is never used.
4. The **separate** Cardmarket marketplace region expansion must be indicated by a packaging item labelled Non-English, Japanese or Asia Region Legal; its distinct ID comes from that export. A title mapping to two expansions fails.
5. Exactly **one** marketplace singles product matches that separate expansion, complete English-transliterated name, and printed collector number. Multiple products, including unpriced variants, fail without choosing a price.
6. A valid fresh Cardmarket guide trend and correct category/ID must exist. Use existing ECB EUR/GBP conversion. The database write is guarded by the **Japanese** reference's full original identity and preserves the price's source, marketplace region, product ID, FX evidence and timestamp.

The quote carries `valuation_role=MIXED_NON_ENGLISH_REFERENCE`, `physical_language_confirmed=false`, `physical_valuation_eligible=false` and `condition_specific=false`. It is an **indicative non-English marketplace-region guide, NOT an exact Japanese-language, Near Mint, graded or completed-sale market price**. It must not establish a physical-copy recommended price or activate automatic Shopify repricing. Unqualified JP alt-art or promo cards remain explicitly unavailable.

The existing global catalogue browser displays **"Raw · Cardmarket Non-English regional guide (Japanese language not verified)"** rather than falsely calling it a verified Japanese market value. Seller Hub and account-specific views continue using the same owner-independent Supabase reference lookup.

## Measured read-only replay (before integrating/deploying)
One-shot GitHub Actions job **38377797794** (public source and checklists, no production writes) compared exactly **3,931 official base reference records** (2,040 JP and 1,891 EN) to Cardmarket game-18 public source exports, including source export dates. It found:

- **1,424** strict exact marketplace product matches from 2,040 eligible Japanese base references, all with positive regional Cardmarket guide quotes.
- 17 independent release codes with matches: EB01=42, EB02=44, EB03=44; OP01=89, OP02=89, OP03=94, OP04=93, OP05=95, OP06=95, OP07=93, OP08=95, OP09=94, OP10=94, OP11=91, OP12=92, OP13=89, OP14=91.
- Every matched Japanese reference points to a distinct marketplace product ID; no accidental same-ID alias/crossregion borrow. Region markers remain stored and language uncertainty explicit.
- This is **1,424 candidates, not evidence of 1,424 live persisted prices until the post-deployment readback**.

It does not alter 7,166 unpriced Naruto reference records or provide graded Japanese sold evidence. The 1,424 are regional market guides, so the exact-Japanese-sale coverage percentage remains lower.

## What it connects to
`one_piece_japanese_market.py` exact matcher → `one_piece_market.refresh_one_piece_prices` (one download set per job for English+Japanese) → `tcg.reference_market_prices` and immutable quote history → shared catalogue browser / Seller Hub reference views.

The existing maintenance job revision is advanced **8 → 9** to run a scoped backfill without another service, cron, n8n type, scraper, schema or paid provider. The owner-backed Cardmarket valuation fallback already requires English reference language and exact physical basis, so these JP regional guides cannot silently price owner inventory or sales.

## Risks, limits and tests
- Public price guides are not independently verified Japanese sold transactions; expansion suffix **Non-English** can be broader than Japanese. Users see the explicit limitation.
- False matches from translations, parallel artworks, release variants, promos, missing marketplace products or regional ambiguity must return no price. Never infer a grade/condition premium.
- API failures and stale/invalid EUR quotes preserve immutable historical evidence, and current-view freshness controls must fail closed.
- Written commercial presentation/redistribution rights for Cardmarket data must be established under their current terms. This work reuses the previously connected public feed; do not add scraping or assume that a public download grants unrestricted syndication rights.
- Tests include wrong provider, contradictory set codes, incorrect name/number, mixed-language, two market products/expansions, negative/nonpositive prices, exact GBP conversion and deterministic stress collision checks.
- Validate complete GitHub CI, Railway deployment/readiness, reference jobs revision 9 terminal status, actual source-guide count increase and unchanged physical owner ID/Store Price/status fingerprint. Never promise 100% exact-price coverage where data does not exist.

## Rollback
Revert the feature PR through the existing main deployment. No database schema changes. Do **not** delete historical provider observations or user inventory, prices and settlements.
