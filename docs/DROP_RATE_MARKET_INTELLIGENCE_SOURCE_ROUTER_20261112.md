# Drop Rate Market Intelligence — owned collection layer (Phase A)
**12 November 2026 · Draft · No production writes**

## Founder decision and scope
Build a Drop Rate-owned, reusable collection system for **card identity, exact artwork, and market evidence**, preserving the existing working adapters and authoritative database. Do **not** restart Cloudflare/D1 migration. Stack stays Railway/FastAPI jobs, Supabase Pro Postgres, GitHub and Shopify, with legacy R2 assets retained until verified replacement. This is NOT a new paid scraper or an unattended signed-in eBay crawler.

Previously built functionality retained:
- eBay official Browse OAuth/client and matching: `backend/app/ebay_official_client.py`, `backend/app/ebay_official_adapter.py` — **ACTIVE asking** only.
- eBay Product Research *human-assisted* sale evidence bridge: draft PR #1076, `backend/app/ebay_signed_in_research.py` — NOT merged or automatic.
- Strict UK sold normalisation and five-comparable pipeline: `ebay_sold_normalization.py`, `ebay_sold_pricing.py`, `live_market_refresh.py` — do not weaken.
- Cardmarket public guide/export adapters and existing exact MTGJSON crosswalk: `cardmarket_public_pilot.py` — guides are NOT independent verified item-level sold comps.
- Existing exact-card and media adapters: TCGdex, Japanese One Piece (Punk Records), YGOPRODeck and Lorcast review pilots, MTGJSON/Scryfall print crosswalk, existing media resolution and manual approval.
- Supabase canonical cards/inventory/owner/price/evidence and Shopify sync remain untouched.

## Phase A implementation (this PR)
- `backend/app/market_intelligence_sources.py`: deterministic, review-only source capability registry, source routes per game and language, exact canonical reference admission rules. Every source is tagged by actual evidence kind and existing code module, not assumed usable simply because the user has a browser session.
- `backend/scripts/market_intelligence_plan.py`: offline operator source-plan command.
- `tests/test_market_intelligence_sources.py`: explicit invariants for source segregation, exact references, grades, photos, provenance and no-write behavior.

Example: a confirmed English Pokémon card routes its identity and artwork to existing TCGdex, active asking to eBay Browse, and separately generates a signed-in Product Research route for manually verified UK sold price evidence. For Japanese One Piece the existing Japanese Punk resolver is eligible; English One Piece has **no automatically approved artwork route yet**. For Naruto and Dragon Ball, unsupported exact-artwork providers are left unknown; no similar-art fallback. Yu-Gi-Oh!, Lorcana and MTG art candidates remain independently gated, not automatically publishable.

## Run
The target file must be a private local JSON object containing exact catalogue reference metadata (not physical ownership secrets). For example:

    {
      "reference_id": "DR-REF-EXAMPLE",
      "game": "Pokemon",
      "name": "Charmander",
      "set_name": "Phantasmal Flames",
      "card_number": "011/094",
      "variant": "Normal",
      "language": "English",
      "condition": "Near Mint"
    }

Command from repo root:

    PYTHONPATH=backend python backend/scripts/market_intelligence_plan.py --target /private/confirmed-printing.json --read-only

The output is a plan and a list of existing module routes, not retrieved values or artwork. It does not require credentials or call outside systems.

## Data quality and policy
1. **Canonical CARD vs physical INVENTORY** remain separate. Candidate providers must submit exact reference ID, game, card name, set, collector number, variant and language. No fuzzy/name-only match is permitted to change existing IDs. Physical condition and exact grade are required for prospective sales; graded photographs belong to physical inventory, not card reference art.
2. **Pricing:** completed sales must have independently verified actual paid amount, sale date, eBay GB item location, GBP, original listing ID, exact condition/grade and full provenance before the existing sold engine may even review them. Active asking prices and Cardmarket guides are context-only; none can automatically set customer-facing Market Value. A manually claimed `sale_verified=true` is NOT enough to publish a value.
3. **Artwork:** verify correct printing, image bytes/hash, source permissions and physical/slab distinction. Existing media approval and owner-only photo rules remain authoritative. No guessed URLs, reused wrong languages, stock art for slabs or AI-generated replacements.
4. **Card info:** existing canonical IDs remain authoritative. A candidate may be reviewed and mapped, never overwrite identity or ownership by AI instruction.
5. **Provenance and operations:** observed source ID, capture time, rights decisions and exact-match proof, append-only observation history, quotas, backoff, source budget gates and idempotency. No cookies, passwords, buyer/seller personal data or new paid services. Do not bypass account or provider limits.

## Next implementation stages — separately reviewed
**B. Controlled source intake**: wire existing approved eBay Browse/TCGdex/catalogue and Cardmarket public file readers to a bounded Railway job and existing Supabase observation/metadata schema. Implement per-source daily budget and failure Action Required queue; no new services unless documented.

**C. Signed-in eBay paid-price evidence**: after browser access is fixed, inspect actual Product Research with the founder, compare a 5–10 sale sample against exact physical-card identity and verify that source-level details can be legally and technically collected unattended. If unavailable, keep the authenticated assisted-review workflow; do not store eBay browser cookies in Railway. No bypass of access controls.

**D. Artwork QA**: connect exact known providers and use existing source-byte/hash/image resolution and human review. The first signed-in pilot must use 1 actual card and 1 graded card to test no slab art substitution.

**E. Market value activation**: compare at least five exact recent paid sales where available; maintain existing strict UK sold-only contract, source timestamp/market history, manual high-value checks and rollback. No live price, Store Price, Shopify, payout or settlement write until receipts and founder approval.

## Failure tests / rollback
- Unknown or missing exact printing, wrong language/set/variant, wrong raw condition or grade, duplicate record key, unverified sale, missing actual paid price and sale date, stale/ambiguous data, invalid provenance.
- Malformed provider response, 429/rate-limit, unavailable login, provider rights not confirmed, image URL dead, image content mismatch, slab photograph missing.
- CI: `PYTHONPATH=backend pytest tests/test_market_intelligence_sources.py -q`, full backend + UI + database contract suite; dry-run source route plan for Pokémon, One Piece, Yu-Gi-Oh!, Lorcana, MTG and unknown-source categories.
- No DB migrations, cron, service configuration, live prices, media or Shopify changes in this PR. Rollback: close/revert the draft PR; legacy collectors are unaffected.

**Current state:** Source routing foundation only; no new automatic scraping or production market values. Source-rights decisions and eBay browser access are still independent blockers.
