# Storefront Launch QA

_Last verified: 29 September 2026_

## Scope

This document records the connected-store engineering verification for the unpublished
Shopify theme **Drop Rate — Brand Redesign**. It is a launch gate, not permission to
publish the theme.

The v1 customer path under test is:

`Browse → PDP / grouped copies → exact physical cart line → Shopify checkout → search → Shopify customer account/order history`

Postgres/FastAPI remain the source of truth for physical inventory, ownership and finance.
Shopify remains the storefront, cart, checkout, customer-account and order-history surface.

## Theme state and source-control parity

- Theme: `Drop Rate — Brand Redesign`
- Role: `UNPUBLISHED`
- Shopify processing: false
- Shopify processing failed: false
- Source-controlled theme files checked against Shopify: **14**
- Byte-for-byte mismatches after QA correction: **0**
- Live Horizon theme changed by this QA: **no**

QA found an unfinished Sealed-navigation runtime drift in the unpublished theme.
The only `sealed` collection had zero products, and no game-specific sealed collections
existed. The runtime-only Sealed links and locale key were therefore reverted to the
already-tested GitHub versions. No product or live-theme data was changed.

## Product publication and exact physical-copy contract

Connected Shopify counts:

- ACTIVE products: **95**
- products published to Online Store: **95**
- intentionally unpublished products: **369**
- products associated with the Online Store channel: **96**

A paginated sweep of all **95 published products** verified:

- exactly one Shopify variant per physical listing;
- `drop_rate.inventory_id` present;
- variant SKU equals the physical Inventory ID;
- inventory quantity equals **1**;
- inventory policy is **DENY**;
- variant is available for sale;
- no invariant failures were found.

This preserves the rule that one customer-facing listing represents one tracked physical
copy and cannot oversell quantity.

## Grouped-copy PDP contract

Across the published catalogue:

- products with `copy_handles`: **14**
- sibling references checked: **28**
- broken or unpublished sibling references: **0**
- every grouped product includes its own handle in the group.

The theme resolves sibling options through exact Shopify handles derived from canonical
catalogue grouping. It does not fuzzy-group cards from display text.

## Product media

All **95 / 95** published products have at least one Shopify media item and a featured
media asset. Every featured media asset reported `READY`.

This removes missing-image placeholders as a launch blocker for the currently published
catalogue.

## Browse and collections

Core populated collections remain available for navigation, including:

- Pokémon
- One Piece
- Singles
- Graded Cards
- populated Pokémon and One Piece set collections.

Empty game destinations such as Dragon Ball, Naruto and Riftbound are not promoted by the
custom browse route until they contain products. Empty Sealed navigation is likewise not
exposed.

The source-controlled collection route and Shopify runtime file are byte-for-byte equal
after the QA correction.

### Facet data hygiene

The collection template already has Shopify-native filtering enabled. Before exposing
metafield facets broadly, live product metadata was checked for duplicate display values.
One OP-13 set label had been reintroduced by a later import as `Carrying on His Will`
even though the canonical catalogue label is `Carrying On His Will`. Import
normalisation now maps that known alias at the intake boundary while preserving unknown
set names verbatim. This prevents future Collectr/import batches from recreating the
duplicate-looking Set facet without applying unsafe generic title-casing rules.

## Search v1

Search remains Shopify-native and product-only.

Connected-store checks passed for:

- collector number: `OP16-071`
- card name: `Benevolent King`
- Pokémon card name: `Eiscue ex`
- a deliberately invalid query returned zero results.

The search form uses last-term partial matching and keeps unavailable products after
available matches. No custom search index or AI search service is introduced for v1.

## Cart and checkout contract

The source-controlled cart presentation is in exact parity with the unpublished theme.

Verified contract:

- Drop Rate physical products are detected using `drop_rate.inventory_id`;
- customer-facing quantity editing is locked for physical-copy lines;
- the exact Shopify variant remains attached to the cart line;
- the native Shopify cart route is preserved;
- the theme's cart summary contains the native Shopify `name="checkout"` action.

No custom checkout or customer-payment path is introduced.

## Customer accounts and order history

Shopify configuration is:

- account setting: `OPTIONAL`
- account version: `NEW_CUSTOMER_ACCOUNTS`
- storefront/checkout login links visible: **true**
- login required at checkout: **false**

The header uses Shopify's native `<shopify-account>` component. Guest checkout remains
available. Customer auth is separate from Founder HQ and Seller Hub; the storefront does
not reuse `/owner`, PLATFORM_ADMIN, consignor identity or Supabase browser auth.

## Operations dependency

The 30-minute production operations monitor passed the corrected reconciliation path at
**2026-09-29 02:30 UTC**:

- heartbeat healthy;
- Shopify orders scanned: 2;
- local Drop Rate Shopify orders: 1;
- matched: 1;
- remote-only anomaly: 1;
- local-only: 0;
- both monitor commands exited 0.

The known cancelled #1001 test remains the expected webhook-gap alert. The earlier false
#1002 alerts are resolved.

## Remaining launch gate

Engineering/data-contract QA is complete for the current v1 path.

Before publishing the Brand Redesign theme, perform normal authenticated Shopify preview
QA on at least:

- desktop browse → PDP → grouped copy → cart → checkout handoff;
- mobile browse/search/PDP/cart;
- account button/login handoff;
- empty/no-result search;
- visual density, spacing, truncation and image cropping.

Because the theme is unpublished, this visual gate requires an authenticated Shopify
theme-preview browser session. Do not publish before that preview is approved.

