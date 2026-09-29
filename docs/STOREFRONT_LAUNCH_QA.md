## Final pre-publication checkpoint — 29 September 2026

The source-controlled Brand Redesign storefront is now synchronized through the active
global theme layer as well as page-level components. The overlay contains **22 files** and
the deployed unpublished theme has been checked for parity across the previously verified
commerce files plus `dr-brand-system.liquid`, `config/settings_data.json`,
`sections/header-group.json`, and `sections/footer-group.json`.

Verified without browser rendering:
- Brand Redesign remains **UNPUBLISHED**; Horizon remains **MAIN** and was not modified.
- Current Drop Rate logo/menu/announcement/footer configuration is preserved.
- Shopify New Customer Accounts are enabled, optional, visible, and guest checkout remains
  allowed.
- Homepage featured products are ACTIVE and configured CTA/set collections are non-empty.
- Sealed remains empty and the count-gated Sealed browse destination remains hidden.
- Set-facet casing has been canonicalized in the source of truth and in Shopify.

Still required before publication:
- install/configure Shopify **Search & Discovery** for native Set / Condition / Language
  filters;
- perform one real desktop and one real mobile password-protected preview covering homepage,
  collection browse/filter/sort shell, grouped-copy PDP, exact-copy cart, Shopify checkout
  entry, search/no-result state and customer-account handoff.

Do not publish the theme until those two gates are complete.

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

## Active global theme settings and footer

Brand Redesign's Shopify-managed `config/settings_data.json`, `header-group.json` and
`footer-group.json` are now source-controlled as part of the storefront overlay. Only
active colour values are changed: the current palette uses navy/ink/blue/cool-grey/white,
the announcement bar uses current navy, and footer/email surfaces use cool grey/white with
the current border/text colours.

The uploaded `drop-rate-brand-logo.png`, logo sizing, `main-menu`, announcement copy,
footer copy, social/policy blocks, section IDs and layout settings are preserved. Preset
definitions are not used as a backdoor to alter the live Horizon theme.

## Active global brand layer

The unpublished theme's `layout/theme.liquid` renders both
`drop-rate-global-styles` and `dr-brand-system`. The latter previously loaded after the
component stylesheet and still contained legacy yellow/teal buttons plus flat overrides for
product cards, filters and PDP components.

`dr-brand-system` is now source-controlled and intentionally limited to broad theme
primitives: current Drop Rate colour tokens, focus/header treatment, gallery media,
product-card purchase controls and footer basics. Component-specific browse/PDP/cart/search
styles remain owned by `drop-rate-global-styles` so the later-loaded brand layer cannot
silently flatten them.

## Homepage visual alignment and source control

The four custom homepage sections used by `templates/index.json` are now mirrored under
`storefront/theme/sections/**` instead of existing only inside the Shopify theme.

The visual-only alignment removes the older yellow/teal accent treatment and uses the same
current Drop Rate system as Seller Hub and the rest of the storefront: deep navy, blue/cyan,
cool grey and white. Native behavior is deliberately preserved:
- the discovery search remains a Shopify GET to `routes.search_url` with product-only,
  last-term partial matching;
- hero products remain theme-editor product settings;
- game and set cards still link to their configured Shopify collections;
- the editorial spotlight remains driven by its configured Shopify product and URL;
- no merchandising, pricing, inventory, ownership or checkout logic moves into Liquid.

## Collection visual alignment

The collection/browse surface is being aligned to the current Drop Rate product UI rather
than the older cream/beige storefront treatment.

The source-controlled theme now uses the Seller Hub visual language for this slice:
- deep navy collection hero with cyan/blue accents;
- cool grey page surfaces and white product/filter cards;
- navy/blue active navigation states;
- compact two-line TCG card titles and muted set/collector metadata;
- the Sealed browse destination is wired but remains hidden while the smart collection is
  empty, preserving the no-dead-destinations rule.

This is an unpublished-theme change only. It does not change product data, ownership,
pricing, inventory quantity or publication state.

## PDP and grouped-copy visual alignment

The source-controlled PDP presentation now uses the same Drop Rate product UI language as
Seller Hub and the collection browse surface:

- navy/ink typography with blue/cyan accents;
- white/cool-grey fact and grouped-copy surfaces instead of the older cream treatment;
- a clearer selected-copy state for grouped physical copies;
- a blue primary add-to-cart action consistent with the current brand system;
- compact mobile facts/copy selection without changing exact-copy identity.

The existing grouped-copy contract is unchanged: copy choices still resolve through exact
Shopify handles derived from canonical catalogue grouping, and the native Shopify buy/
checkout blocks remain in place.

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

## Search visual alignment

Shopify-native search now uses the same current Drop Rate visual system as browse/PDP:
a white elevated search field on the cool-grey surface, blue focus/icon states and a
compact no-results treatment. Query semantics remain unchanged: search is still product-only,
last-term partial matching is preserved, and unavailable products remain ordered last.

## Cart visual alignment

The exact-copy cart presentation now follows the same current Drop Rate visual language as
browse and PDP:

- exact physical-copy metadata uses compact blue/cyan badges;
- the one-copy quantity lock is explicit and visually separated from normal quantity UI;
- cart titles and prices use the current ink/navy emphasis;
- the native Shopify checkout CTA is styled blue without replacing the checkout form/action.

The cart contract itself is unchanged: physical lines are still detected by
`drop_rate.inventory_id`, quantity editing remains disabled for those lines, remove remains
available, and Shopify's native cart/checkout path remains authoritative.

## Customer accounts and order history

Shopify configuration is:

- account setting: `OPTIONAL`
- account version: `NEW_CUSTOMER_ACCOUNTS`
- storefront/checkout login links visible: **true**
- login required at checkout: **false**

The header uses Shopify's native `<shopify-account>` component. Guest checkout remains
available. Customer auth is separate from Founder HQ and Seller Hub; the storefront does
not reuse `/owner`, PLATFORM_ADMIN, consignor identity or Supabase browser auth.

## Customer account/header visual alignment

The native Shopify customer-account and cart header actions now use the same current
Drop Rate visual tokens as browse, PDP, cart and search. The `<shopify-account>`
component remains Shopify-native and uses a white surface, ink text and blue accent;
the signed-in fallback/avatar treatment uses the blue/cyan brand gradient.

No custom customer authentication, owner/seller authentication reuse or checkout login
requirement is introduced. Guest checkout and the existing separate cart action remain
unchanged.

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

