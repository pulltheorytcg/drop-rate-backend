# Google Shopping / Merchant Center Readiness

_Status: Phase 2 pre-launch audit, 30 September 2026._

## Decision

Use Shopify's native **Google & YouTube** sales channel / Merchant Center integration after Brand Redesign is public.

Do **not** build a custom n8n product-feed pipeline.

n8n's eventual role is Merchant Center diagnostics → Drop Rate Action Required, not feed generation.

## Current Shopify state

Live Shopify audit:

- 470 ACTIVE products
- 470 products with featured media
- 470 products with positive inventory
- 470 products with positive price
- 470 products with `drop_rate.language`
- 462 products with `drop_rate.condition = Near Mint`
- 8 graded products with grader + grade metafields
- 0 products with variant barcode / GTIN
- current product type: `Trading Card`
- vendors:
  - One Piece: 245
  - Pokémon: 200
  - Dragon Ball: 25
- Google & YouTube app/channel is **not currently installed**
- Brand Redesign remains unpublished; do not activate a Google feed against Horizon.

## Google condition mapping

Google Merchant Center condition values are:
- `new`
- `used`
- `refurbished`

Drop Rate mapping:

### Raw singles

Use **`used`**.

Even a Near Mint trading card is not "new in original unopened packaging" in Google's sense.

### Graded slabs

Use **`used`** by default.

A PSA/ACE/CGC/TAG/BGS slab may be pristine and professionally encapsulated, but the underlying card is not an unopened new retail product. Do not map grade 10 to Google `new`.

### Factory-sealed products

Use **`new`** only when the physical product is genuinely factory sealed/unopened.

Examples:
- sealed ETB;
- sealed booster box/display;
- sealed booster pack;
- sealed collection box/tin.

If seal condition is damaged/ambiguous or the product is opened, do not force `new`.

## Product identifiers

Google's `identifier_exists` flag must reflect whether the exact product has manufacturer-assigned identifiers.

### Raw and graded singles

Most individual trading-card singles do not have a product-level GTIN/UPC assigned to that exact physical card.

For a single with no valid GTIN and no valid manufacturer MPN + brand combination, submit:

- `identifier_exists = false`
- leave GTIN blank
- do not invent an MPN

The current 470 active Shopify products all have blank barcodes, which is consistent with this singles catalogue.

Do not assume every future single lacks identifiers; apply the rule from canonical/provider evidence.

### Sealed products

Do **not** default sealed products to `identifier_exists = false`.

ETBs, booster boxes, packs, tins and collections commonly have manufacturer UPC/EAN/GTIN identifiers. The sealed canonical catalogue should store those exact identifiers and publish them when verified.

Never make up a barcode or reuse a similar product's identifier.

## Brand

Use a truthful customer-facing franchise/manufacturer brand mapping.

The current Shopify vendor values are franchise/game labels:
- Pokémon
- One Piece
- Dragon Ball

Before Google activation, verify how the Shopify Google channel maps Vendor → Google `brand` for trading cards and sealed products. Do not silently change current Shopify vendor semantics merely to satisfy a feed.

## Google product category

Google automatically categorizes products and allows an optional Google Product Category override.

For card singles, the relevant taxonomy is expected to be the collectible/trading-card branch rather than a generic retail category. Confirm the current numeric category from Google's live taxonomy during Merchant Center setup rather than hardcoding an unverified third-party ID.

For sealed game products, evaluate whether Google's current taxonomy classifies the exact SKU under Card Games versus Collectible Trading Cards; do not assume singles and sealed boxes share the same optimal category.

## Native setup gate

Do not install/activate the feed until:
1. Brand Redesign is MAIN/public;
2. real Brand Redesign purchase test passes;
3. checkout/order attribution is verified;
4. Google mapping rules above are implemented/confirmed.

Then:
1. install Shopify Google & YouTube;
2. create/link Merchant Center;
3. configure UK target;
4. start **free listings only**;
5. inspect Merchant Center diagnostics before enabling any paid campaign;
6. paid Shopping spend requires explicit founder sign-off.

## n8n later

After the native feed is stable, add a small version-controlled workflow:

`Merchant Center diagnostics → FastAPI → Action Required`

It should alert on:
- disapprovals;
- missing identifiers where Google expects one;
- price mismatch;
- availability mismatch;
- image issues;
- policy/account warnings.

n8n must not rewrite product identity, price, ownership or feed truth independently.


## Store-level Shopify policy/contact status

Live verification on 30 September 2026:

- public contact email exists;
- published Contact page exists;
- published Contact Information page exists;
- footer links to contact information;
- published Refund & Returns page exists;
- published Terms of Service page exists;
- Shopify native policy objects currently include Privacy Policy only;
- no installed Shopify app currently has the `write_legal_policies` scope.

Therefore:

### Contact information
**READY.** The store already contains customer-visible contact information and this can be truthfully confirmed in the Google & YouTube setup checklist.

### Refund policy
**MANUAL SHOPIFY ADMIN STEP REQUIRED.** Copy the already-approved Refund & Returns policy into:

`Shopify Admin → Settings → Policies → Refund policy`

Do not rewrite or generate a different policy merely for Google.

### Terms of service
**MANUAL SHOPIFY ADMIN STEP REQUIRED.** Copy the already-approved Terms of Service page into:

`Shopify Admin → Settings → Policies → Terms of service`

Again, reuse the approved existing policy text.

### Store live/public
**INTENTIONALLY BLOCKED BY PHASE 2 LAUNCH GATE.** Brand Redesign must not be made MAIN merely to satisfy Google. Complete mobile/desktop smoke and the controlled Brand Redesign purchase first.

Once the native policy fields are saved and Brand Redesign is public, re-run the Google & YouTube setup checklist before product sync.
