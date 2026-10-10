# Multi-game pricing repair — 10 October 2026

The founder requested the remaining pricing failures be fixed and supplied the Phase 2 Operating Manual. This repairs the existing Cardmarket/catalogue pipeline. Pricing remains deterministic in FastAPI/Postgres; no new Railway service, paid subscription, storefront launch or n8n decision logic is introduced.

## Confirmed causes

- Inventory fallback was hardcoded to Pokémon. The 316 newer One Piece reference guides could appear in search but could not produce a physical-copy estimate.
- One Piece bulk pricing excluded every older Punk Records English checklist. The full set data already included rarity, but the importer discarded it.
- Dragon Ball public Cardmarket game-13 exports had no connected reference-price pass. Masters and Fusion World share that export but need separate release and printing identities.
- Japanese translations, unverified provider mappings, ambiguous parallels, slabs and absent source quotes are separate evidence gaps. They cannot be fixed by assigning an unrelated card's value.

Baseline: 510 inventory copies / 251 valued. Owner/Store Price/status fingerprint `ab62e1122c7e51df7a2288288a3c3005`; valued-amount fingerprint `deb7d73c61d3f2b264a3bd85871004d7`.

## Changes and evidence rules

The existing daily pass reads older One Piece English boosters and Dragon Ball Masters/Fusion World bulk guides. Complete release names, game, collector numbers where Cardmarket publishes them, full card names and uniqueness across both checklists establish a match. A duplicate number, conflicting name, alternate printing or regional expansion cannot be resolved through price/order. Masters' export omits collector numbers: both the official name and collector number must identify one official printing and its full release/name must identify one Cardmarket SKU. Normal and foil prices retain separate fields.

The existing v4 guide calculation now supports those exact cached English references. It still scans all canonical products, including unowned ones. Only identity-confirmed, ungraded Near Mint copies of the matching language can receive an estimate. Ordinary One Piece booster bases require matching published rarity/finish; special printings remain reference context. Intrinsically foil Dragon Ball rarities imported as Normal require review. Existing fresh eBay sold values keep priority.

Cardmarket observations stay PRICE_GUIDE, with zero invented sales, capped confidence, original EUR/date/ECB GBP evidence and the mixed-language/condition limitation. Store Price, owners, status and publication eligibility are not changed. Rarity is preserved from the already-downloaded complete One Piece packs.

The additive `cardmarket_multigame_guard` migration keeps SECURITY INVOKER and fixed search paths. Cached catalogue/intake reads and guarded writes check that a bulk quote still belongs to the current reference identity and cache. Review/rejected mappings from any provider block the fallback. Historical quotes and snapshots are retained.

## Checks and rollout

Read-only source replay found 1,823 One Piece and 1,755 Dragon Ball priced references. The initial physical-copy replay identified 63 pending copies before the additional foil-rarity exclusion; this is diagnostic evidence, not a production coverage claim. The pending stock contains some wrong/insufficient identity fields that remain blocked.

Tests cover actual bulk-export shapes, independent normal/foil prices, regional/printing/name/number collisions, stale/future evidence, invalid FX, changed source identities, review status, owner isolation, unowned guides, retries, unchanged Store Prices and eBay priority. Real PostgreSQL exercises the new joins, migration and cached intake. Current-head CI, applied migration, successful deployment and production read-back remain required before reporting live counts.

Revisions: Punk import 2, reference-price job 4, Cardmarket calculation 3. The existing daily schedule and recovery loop perform the refresh; no provider calls are made by the physical-copy calculation. Rollback reverts the worker changes while retaining the additive helper and all historical evidence.

Primary sources: Cardmarket `products_singles_13.json`, `products_nonsingles_13.json`, `price_guide_13.json` and corresponding game-18 exports under https://downloads.s3.cardmarket.com/productCatalog/; Bandai English Masters/Fusion World/One Piece checklists; exact Punk Records full-pack snapshots already used by the reference importer.
