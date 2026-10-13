# Japanese Fusion World regional Cardmarket reference recovery — 13 October 2026

## Verified scope and motivation

Existing verified regional coverage: Japanese Fusion World **0/3,227** cards. User requires credible shared GBP market context independent of ownership. This reuses existing first-party Cardmarket game-13 exports and the same deterministic daily reference importer without a paid provider or arbitrary AI prices.

## Exact-match admission rules

A source candidate must have both independent official Bandai English and Japanese original FB booster checklists, each in their specific 583NNN / 584NNN source set, with the same full printed set code (FBNN), same collector number (FBNN-NNN), exactly one base-print provider ID with no suffix and no conflicting published rarity. The original English release title is used only to identify a separately labelled Non-English/Japanese/Asia Region Legal Cardmarket booster expansion. Marketplace products must have the same full printed number, the same English catalogue title, and exactly one possible product in that non-English expansion. Any duplicates, alternate arts, promo/reprint/graded identities, product-category conflicts or missing GBP quote remain unpriced. English market quotes are never copied.

## Real read-only source replay

Run: https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/38405860367

Against 1,403 Japanese plus 1,403 English public official base references and Cardmarket's actual game-13 source files:

- **557** unique non-English regional product matches, strictly FB01–FB05.
- **383** positive public guide quotations: FB01 86, FB02 92, FB03 90, FB04 69, FB05 46.
- The other 174 matched identities have no usable positive quote, and every other Japanese printing remains unpriced.
- All recovered marketplace product IDs are distinct and outside the English expansion; no physical price/Shopify writes occurred in the replay.

This is a regional market guide, **not a verified Japanese-language sold price**, raw-card condition, slab valuation or recommended retail price. Quotes carry reference_language=Japanese, valuation_role=MIXED_NON_ENGLISH_REFERENCE, physical_language_confirmed=false, physical_valuation_eligible=false, condition_specific=false, and original marketplace region/product/FX/printing provenance.

## Integration and safety

Existing FastAPI price importer, reference_market_prices cache/history and ECB FX are reused, with global owner-independent reference reads. Japanese candidates are explicitly dispatched to the Japanese region matcher. No fallback to English by card number. New additive validated PostgreSQL CHECK constraint on Japanese Fusion market reference quotes requires correct language, source tier, unique double-checklist match basis, region provenance, and non-publishable physical flags. This protects against recurrence of the One Piece 454-row English inheritance incident.

An existing reference-job revision increase from 10 to 11 triggers the regular bounded ingestion after deployment. It never changes Store Price, ownership, customer settlements, Shopify publication, reference catalogue identity, or immutable market history. No new n8n or Railway service, provider, payment or subscription is created.

## Failure and release gates

Source ambiguity or outage retains unavailable status/previous historical observations, never guesses. Regression tests include wrong language, code, publisher, region, pricing category, duplicate products, alternate printing, currency conversion, 1,000 seeded collision cases and a full worker dispatch test. Actual disposable PostgreSQL CI must reject invalid Japanese evidence and show valid GBP guides identically regardless of owner. Merge only on green; apply validated additive migration before deploying the worker, then confirm Railway and the true production row-count lift by SQL. If the source is stale or missing, 383 replay matches are **not** treated as a deployment success.

Still outstanding: unpriced Japanese Fusion beyond this cohort, Japanese One Piece alternatives, Naruto, other English/JP missing sources, graded-card comps and Trawl eBay sold quota; the algorithm cannot manufacture trustworthy prices without permitted evidence.
