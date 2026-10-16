# Seller Hub 104-item video and live valuation audit — 16 October 2026

## What was reviewed

Founder-recorded 125-second, 512×1112 iPhone video of the *live* `drop-rate-api-live-production.up.railway.app` Seller Hub: Home → One Piece search → card detail → Naruto search/sealed → Inventory. It shows the homepage **104** physical inventory, **£0.03** active market value, **£1.00** recommended retail, **102 drafts / 2 approved**, £0.00 sold, and a small note for **£20.00 in saved asking prices (2 copies)**. The founder asked why his 104 cards appear unpriced and to review other issues too.

Read-only production audit (Supabase project `ozrxenrdladkooixutmm`) found:

| Real fact | Production evidence |
| --- | --- |
| Owner-scoped inventory | **104 physical copies: 101 cards and 3 sealed products** |
| Pipeline | **102 DRAFT**, **2 APPROVED**, no sold |
| Seller-entered Store Prices | **2 sealed products × £10** = **£20.00**, no Store Price saved on 101 cards |
| Current catalogue-basis market evidence | **1/104 eligible**: English Dragon Ball `BT18-105` Borgos at **£0.03**, clearly an **EU Cardmarket guide** (not a UK sold price) |
| Calculated retail recommendation | **£1.00** for that one £0.03 guide case, reflecting the deterministic £1 minimum—not a price for all 104 copies |
| Other cached evidence | **OP17 pack £8.66 (8 Oct)**, **PSA Eevee £97.50 (9 Oct)**: stale relative to current seven-day age rule and excluded from active totals |
| Language/source distribution | 90 One Piece Japanese inventory items (including sealed), 3 One Piece with absent catalogue language, 1 English One Piece, 8 Japanese Pokémon, 2 English Dragon Ball |
| Blocked mappings | **64 physical copies** linked to `provider_catalogue_mappings.match_status='REVIEW'` (**58 JP One Piece, 6 JP Pokémon**), many `verification_basis='DETERMINISTIC_EXACT'` but `media_approval_status='PENDING'`. The shared valuation resolver appropriately refuses silently promoting an unresolved mapping; review/collateral media identity status must be assessed separately |
| Missing catalogue coverage | **24 Japanese One Piece The Time of Battle cards** lack an indexed same-language printed-number entry; no authorised quote may be invented |
| Source-only, not owned-copy prices | Fourteen Japanese OP14 same-number entries possess positive Cardmarket cached evidence, but `MIXED_NON_ENGLISH_REFERENCE` expressly lacks physical language/condition confirmation, with mappings under REVIEW. Price on the raw card is not permitted to come from same number alone |
| Database | ≈405.5 MB; 50,378 unarchived price-history rows; >400MB Free capacity preflight defers bulk imports; archival remains a separate verified procedure |

## Defect fixed in this release

The Home KPI labelled **Recommended retail** prominently showed **£1.00**, while *actual saved owner asking prices* (£20.00 across 2 copies) were buried in the footnote. That invited the mistaken impression of a £1 Store Value across 104 holdings.

- Change the KPI headline to **Saved Store Prices** and display ONLY `recorded_asking_value_minor` from the existing authenticated `recommended_totals(reference_portfolio(connection,[owner_id]))` output. If none are recorded, show **Not set** instead of £0; when 2/104 are saved, show **£20.00** with the explicit incomplete `2 of 104 copies` coverage. This is an owner's private asking-price sum, *not* UK sales, purchase cost, Shopify approval or a 104-copy valuation.
- Display the separate deterministic automatic `£1.00` recommendation for 1/104 only in a **clearly labelled secondary note** with original guide/coverage context. Do **not** copy auto suggestions into `store_price_minor`, claim them as saved prices, or publish cards.
- The market-value KPI now says **Known market value · partial** when any copies lack eligible market values. A £0.03 source reference is never implied to be the entire collection's worth. It retains the exact priced/unpriced counts, and the EU guide-estimate count. Zero eligible active prices shows **Unavailable**, not a false £0 portfolio.
- The count remains **104**, but its subtitle states the source-of-truth breakdown **101 cards · 3 sealed products**. This corrects the original misleading "104 physical cards" wording. Server counts use an already owner-scoped join with `tcg.catalogue_products`, never other owners or global catalogue counts.
- Owner session, original physical inventory, refunds/payouts, market price history, current quote cache, pricing method, age cutoff and Store Price cells are completely unchanged. UI has no new provider/API requests or DB writes.

## Other issues visible in the recording (not misrepresented as fixed)

1. **Catalogue browsing versus sellable inventory:** Search shows source-library One Piece OP17 rows with `Qty: 0` and per-card **£0.02–£0.11** regional market guides, even when most *owned* items are different Japanese sets or parallel printings. A guide in Search does not equal a condition-, grade- and language-specific owned-copy valuation. Some result rows have no valid quotes.
2. **Publisher SAMPLE watermarks:** Many official One Piece source card images contain a visible `SAMPLE` watermark. This is genuine publisher *reference* art, not the seller's approved physical listing photograph. Do not remove source watermarks or use them as photography for expensive product listings.
3. **Slow/broken artwork:** Search/inventory grids initially show image-loading skeletons and occasional "Image unavailable"; genuine provider assets are absent or fetch poorly. Asset batch/network diagnostics and exact permitted source repair are separate from this KPI release.
4. **Naruto sealed:** Exactly four verified Kayou product references now appear, correctly displaying "Packaging photo pending" and no invented price. Product photo rights/real market quotes remain outstanding; the user sees catalogue completeness limitations, not a total Naruto sealed feed.
5. **Card details:** A source-card detail shows **Dorry** with a **£0.04 regional mixed-language Cardmarket guide** and explicitly `physical_valuation_eligible=false`. The condition selector and explicit exact-printing confirmation are correct; the user cannot convert guide into an owned price without verifying the physical basis.
6. **Top valued cards / movers:** The Home `Top valued cards` reflects only current evidence (thus Borgos £0.03); an older £97.50 Eevee snapshot cannot be ranked as current until new real evidence arrives. "Weekly top movers: Building price history" requires sufficient comparable up-to-date observations; cannot be repaired by guessing price history.
7. **104 data records versus visible cards:** Display-group logic may aggregate identical physical copies into one tile and show an ×N quantity badge, while the Home counts all 104 original physical items. This is correct accounting, not duplicate or missing inventory.
8. **Draft status:** 102 copies are DRAFT and have no saved selling price, so they are not automatically listed or assigned an asking price. Intake review and owner pricing remain explicit actions. The two approved packs have saved £10 prices.

## Data and safety acceptance

- Verify live **104=101 cards+3 sealed**, status breakdown, and **two £10 Store Prices** before/after. Query only with authorised owner context.
- New JSDOM tests cover owner headline `£20` instead of `£1`; truthful `1/104` partial market and no false £0; a fully-priced account; unknown breakdown fallback; no API mutations or cross-owner price mixing.
- Existing 6,000+ backend tests, real PostgreSQL seller isolation, Chromium and WebKit mobile inventory tests, Railway deployed exact head SHA and write-aware `/health/ready` must pass.
- **No** automatic approval of 64 source mappings, no cross-locale or mixed-region price promotion, no SKU merging, no historical-data deletion or unverified backup. Capacity work remains [#651](https://github.com/pulltheorytcg/drop-rate-backend/issues/651); genuine price coverage [#653](https://github.com/pulltheorytcg/drop-rate-backend/issues/653); source-art coverage [#657](https://github.com/pulltheorytcg/drop-rate-backend/issues/657).
