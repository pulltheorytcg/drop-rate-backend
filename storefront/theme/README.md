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
