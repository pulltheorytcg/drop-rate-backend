# Drop Rate Shopify theme overlay

This directory version-controls the Drop Rate-specific storefront files that are applied to the Shopify development theme.

Current Shopify target:
- Theme: `Drop Rate — Brand Redesign`
- Role: `UNPUBLISHED`
- Shopify theme GID: `gid://shopify/OnlineStoreTheme/202073866587`

The live `Horizon` theme is not modified by these files.

This is currently an overlay rather than a full copy of Shopify's base theme. Files are added here as Drop Rate-specific storefront work changes them. Shopify remains the runtime for theme preview/testing; this repository is the review/rollback history.

Do not publish the development theme without explicit launch review. Product identity, ownership and deterministic pricing remain sourced from Drop Rate/Supabase/FastAPI rather than theme logic.

## 11 October 2026 — Fresh finds CTA alignment

The homepage product-list section renders `.resource-list--grid`, not the `.product-list` selector used by the older alignment rules. `blocks/dr-card-title.liquid` now reserves the existing two-line title allowance and lets the copy area expand within equal-height cards, aligning the following price/purchase rows. Both purchase controls remain available. A hidden quantity component's empty wrapper no longer reserves a flex row; the main product-page quantity control is untouched.

No product records, prices, ownership, stock, payment integration, database settings or live theme publication are changed. Only this Liquid block requires a Shopify overlay upload. Before upload, compare its target checksum with the source used for the patch; do not overwrite concurrent changes. Rollback is the previous block from Git, not a theme switch.

`python tests/ui/storefront_card_layout.py` reproduces the original stagger, then checks 20 isolated Chromium fixtures (320–1920px, short/long titles, wrapped/missing metadata, missing subtitle, multi-copy wrapper, preserved payment/disabled states and unaffected PDP quantity). The browser uses fixture markup with verified base layout rules and the real edited block stylesheet, with network requests blocked. This is NOT an authenticated Shopify preview, real wallet, cart or checkout test. Local checks passed; exact-head CI and Shopify file readback must be recorded in the PR release-verification comment. No database tests are claimed or required for this CSS-only change.


## 16 October 2026 — Real comics/manga discovery, no fictional inventory

The verified connected store is Drop Rate (GBP). Two new **smart collections** were created through the connected Shopify admin with exact handles **comics** and **manga**, IDs `684163105115` and `684163137883`. These are currently genuinely EMPTY, because no comics/manga physical copies have yet been added to Supabase. Collection rules are intentionally specific:
- Comics: product `TAG` exactly `Drop Rate:Comics`
- Manga: product `TAG` exactly `Drop Rate:Manga`

This avoids tagging a Pokémon/One Piece card as a book because an unrelated description happens to mention manga. The future backend book Shopify publisher must attach these exact tags **only after the physical copy and artwork/identity are approved and the existing selling/ownership requirements pass**. The current `shopify_pipeline.py` still intentionally supports only `CARD`, `SEALED` and `COLLECTION`; **creating these browse collections does not activate book product publishing**. No fake products were created, zero stock appears until separately approved.

The versioned **unpublished** `Drop Rate — Brand Redesign` theme overlay now includes Comics and Manga links on collection navigation and discovery tiles on the home template. This code must be applied to the correct unpublished Shopify theme and re-read/QAed before calling theme preview live. Do not publish or modify the live Horizon theme as a side effect; Shopify theme editor may re-generate `templates/index.json`, so diff against latest remote revision before any write. The existing book Seller Hub intake/owner ownership is unchanged.
