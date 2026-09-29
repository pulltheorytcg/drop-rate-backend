# Drop Rate — Shopify Search & Discovery Filter Policy

_Last updated: 29 September 2026_

This file records the approved storefront-filter configuration for Shopify Search & Discovery.

## Approved filter order

1. Set — `drop_rate.set_name`
2. Price — Shopify native price filter
3. Rarity — `drop_rate.rarity`
4. Variant — `drop_rate.variant`
5. Availability — Shopify native availability filter
6. Condition — `drop_rate.condition`
7. Language — `drop_rate.language`
8. Grading Company — `drop_rate.grading_company`
9. Grade — `drop_rate.grade`

## Intentionally omitted

- Game — omitted from the default filter stack because game is already a primary browse/navigation dimension (for example Pokémon or One Piece collections). Repeating Game inside game-specific collections adds unnecessary friction.
- Owner, Inventory ID, acquisition cost, internal status, source IDs and any settlement/finance fields — never customer-facing filters.

## Current catalogue rationale

Current Shopify catalogue check:
- 95 ACTIVE products
- Set: 16 distinct values
- Rarity: 9 distinct values
- Variant: 3 distinct values
- Language: Japanese on all 95 products
- Condition: Near Mint on 93 of 95
- Grading Company: PSA on 2 products
- Grade: 10 on 2 products

The order therefore prioritises high-value discovery dimensions and pushes low-variance facets lower in the panel.

## Implementation rule

Use Shopify-native storefront filtering through Search & Discovery. Do not replace this with custom tag filtering or a bespoke backend facet engine.

The relevant `drop_rate` metafield definitions already have Storefront `PUBLIC_READ` access and the Brand Redesign collection template already renders Shopify-native filters.

Search & Discovery app installation and the approved filter order are now confirmed in Shopify Admin.

Filter values remain inventory-driven. As of this QA pass, the customer-visible ACTIVE catalogue exposes Japanese because the active cards are Japanese; the English Seel product is correctly tagged `Language:English` but remains DRAFT, so Shopify does not expose English as a live facet value yet. Do not hard-code empty language values into the theme. English, Korean, Chinese and other languages should appear when ACTIVE collection inventory carrying those normalized metafield values exists.
