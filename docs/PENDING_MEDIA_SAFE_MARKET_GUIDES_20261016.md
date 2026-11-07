# Read-only market reference display when source artwork review is pending

## Scope and evidence — 16 October 2026

An authenticated Seller Hub import contains **104 owned copies**. A live read-only production audit found **60 distinct provider catalogue mappings marked REVIEW, each with `DETERMINISTIC_EXACT`, confidence 1.0000 and `metadata.media_approval_status=PENDING`** (56 JP Punk Records One Piece + 4 JP TCGdex Pokémon), applying to 64 physical copies. The source-card price cache already includes legitimate regional guide observations for at least 14 owned OP14 card numbers. Existing `PRODUCTS_SQL` incorrectly treats a pending *photo* approval as if all price source references are invalid. The physical pricing resolver's existing global veto for REVIEW mappings is retained unchanged.

### What

Allow the **separate read-only `catalogue_reference` guide** where:
1. The canonical is a Japanese raw card and the provider mapping is a `CARD_PRINTING`, with `match_status=REVIEW`, exact verification basis, confidence 1, a specific `media_asset_id` and `media_approval_status=PENDING`.
2. Canonical variant, language and exact provider source printing fields agree, and a real same-language source card & set exists. For Punk One Piece the provider ID must equal the original printed number; for TCGdex the full provider printing ID and card/set/name must match.
3. There is no OTHER unresolved mapping. Any REJECTED mapping, market source REVIEW, different edition/language, incomplete metadata or invalid reference blocks all fallback.
4. `reference_candidates` still requires unique exact source counterparts and rejects ambiguous printed numbers; `catalogue_guide` still requires the unique actual quote identity, full currency/EUR-to-GBP checksum, correct original source, ≤7-day recency, exact physical language/printing and proper edition. Japanese Cardmarket mixed non-English data is explicitly a **Regional guide**, *not* a Japanese sold valuation; `physical_valuation_eligible=false`, `recommended_retail_minor=None`.

This is a catalogue/search and inventory *comparison* only. It is NOT an editable `market_value_minor`, financial portfolio value, asking price or listing authorisation. The main `REFERENCE_VALUES_SQL` still excludes REVIEW mappings from every current physical valuation and automated recommendation.

### Why and boundaries

When the only block is media rights, a valid, explicitly non-physical price guide should be available for informational comparison. We do **not** approve media, images, counterfeit checks or ownership; a 100%-confidence recognition result still cannot override identity/variant review by itself. A separate action-required queue and administrator review remain mandatory. No new paid feed, scraping, mass price refresh or older history purge. The existing ≥400MB Supabase bulk refresh guard is untouched.

The four TCGdex Pokémon review mappings have a canonical name/set discrepancy in the live indexed source and **remain blocked** by the stronger exact-set guard until independent evidence establishes exact identity. Do not weaken this to obtain superficially higher coverage.

### Failure points and tests

- Old, unpriced, guessed FX, wrong currency, suspicious low-confidence, rejected or crossed-region source remains unavailable.
- Partial blocked mapping cannot be bypassed by another approved source record.
- Unpriced parallel variants do not inherit base printed-number guide values.
- No physical market/recommended money, Shopify, owner, payout or media writes.
- Unit scenario of actual OP14 Japanese Bepo guide, invalid year/edition/FX/link, and unchanged catalogue/portfolio fields.
- Real disposable PostgreSQL provider mapping schema, restricted-RLS fixtures and shared founder/seller media/browser CI.
- Exact production readback compares display-only reference price coverage and confirms owner/store-price fingerprint before/after.

### Current expected results

A verified source-ref display improvement for a bounded subset of JP OP14 is likely, but **not** 64/64 new current physical valuations. There are 24 JP OP16 `The Time of Battle` cards with no current JP same-number source catalogue entry, and some price-feed references carry `physical_valuation_eligible=false`. Those cannot be priced by force. Fresh approved source matching or explicit source-provider coverage is needed independently.
