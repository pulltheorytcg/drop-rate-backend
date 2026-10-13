# Japanese One Piece price-source isolation incident and correction — 13 October 2026

## The incident and verified scope

Following the revised One Piece source backfill (PR #620), a live database audit found two classes of new Japanese One Piece price records:
- **1,424** valid source-backed **Non-English/Asia-region** Cardmarket guide rows: `valuation_role=MIXED_NON_ENGLISH_REFERENCE`, `reference_language=Japanese`, `physical_valuation_eligible=false`, and 1,424 distinct marketplace product IDs. These are indicative regional guides, *not* verified Japanese-language sold prices.
- **454** invalid current quote rows with `valuation_role=MIXED_LANGUAGE_REFERENCE`, `match_basis=UNIQUE_RELEASE_NAME_NUMBER_IN_BOTH_CHECKLISTS` that had inherited **English Cardmarket products** solely through a colliding printed provider ID. Affected Japanese starter/promo/release variants must never use an English source product, even where number and English counterpart are the same.

Root cause: the JP iteration used `jp_match['product'] if jp_match else matches.get(ref['provider_id'])`. The else branch consulted the *English* matching dictionary even for a Japanese reference. This is a **language-isolation bug**, not new market evidence. The 454 wrongly obtained values were caught via source-provenance readback before the 1,424-result feature was signed off.

## Immediate production containment — COMPLETED

On 13 October the 454 invalid current entries were identified by an exact predicate combining provider Punk Records, system One Piece, language Japanese, positive market value, Cardmarket bulk source, `MIXED_LANGUAGE_REFERENCE` and the English-only match basis. With an atomic exact-count 454 guard, the current `tcg.reference_market_prices` quotes, low/high values and effective pricing timestamps were cleared to NULL/empty quotes, with a newer `checked_at` preventing stale in-flight upserts from reinstating those values. PostgreSQL's **`reference_market_history` trigger was left intact**. All 454 incorrect historical records remain available for audit and must not be treated as legitimate pricing history.

Post-containment readbacks: **1,424 valid JP regional guide rows**; **zero** invalid active Japanese English-source rows; the 454 earlier incorrect historical snapshots are preserved. No physical inventory, owner, Store Price, Shopify listing, finance or settlement entry was modified.

## Permanent prevention

1. **FastAPI source selection:** English and Japanese source maps are separated with explicit language dispatch. An unmatched Japanese reference becomes NULL and **never** falls through to the English product index. Unrecognized language becomes NULL.
2. **PostgreSQL constraint:** The new additive `reference_market_one_piece_japanese_source_language` guard rejects any current Japanese One Piece `CARDMARKET_BULK_SINGLES` quote that lacks `reference_language=Japanese` in its evidence. Current valid 1,424 pass the predicate; all 454 incorrect rows were cleared before application. No RLS/role or privilege weakening, no data deletion.
3. **Revision 10** reruns the existing reference-price maintenance worker, preserving valid independent Japanese source guides and keeping missing/unsafe Japanese records unpriced. Source timestamp, FX and immutable market history stay unchanged.
4. Regression tests reproduce both the real starter-deck cross-language collision and a misleading Japanese wrong-release collision, exercising the full refresh/DB write selection, not merely the matching helper.

## Release/verification contract

- Full existing Python, backend, dashboard and restricted PostgreSQL pricing/reference CI must pass.
- Apply the additive DB constraint **only after** confirming in a read-only live query that zero active rows violate it, and after the corresponding application fix is ready for production. Use `Supabase.apply_migration`, not ad hoc DDL.
- Merge/deploy exact-head code and verify Railway terminal SUCCESS/readiness 200 and no paid Trawl lookup.
- Confirm revision-10 receipt reports **1,424 Japanese priced** (not 1,878). Readback source flags, historical immutable audit preserved and global coverage, separately from language-specific exact-sold confidence.
- Verify all 613 physical inventory records, all ownership/asking-price/status and Shopify publication remain unchanged.

## Rollback

Roll back the application by reverting the PR; do **not** remove history or delete any prices. The database constraint intentionally remains so even an older buggy application cannot insert a wrong-language Japanese quote. If the import attempts it, it must fail closed rather than assign the wrong price.

## Broader coverage

The source gap has been reduced only by the actual **1,424** legitimate *regional-guide* candidates. The remaining unpriced catalogue includes other Japanese variants, Naruto, Japanese Dragon Ball, Pokémon and unavailable marketplace sales. This fix improves correctness before increasing coverage further. No source licence, paid product or unauthorised Collectr redistribution was added.
