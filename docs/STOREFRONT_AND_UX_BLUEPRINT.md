# Drop Rate — Storefront + Founder UX Blueprint

_Last updated: 28 September 2026_

## Purpose

This document defines the product, UI/UX and automation blueprint for:

1. the customer-facing Shopify storefront, and
2. the internal Founder HQ / seller operations experience.

The storefront must feel like a premium TCG marketplace rather than a generic Shopify catalogue.
Founder HQ must feel like a high-speed TCG operating system rather than a generic admin panel.

Drop Rate should learn from strong patterns in the market without copying another product's interface or brand.

## External UX benchmarks

### RandCards — customer storefront benchmark

Useful patterns to learn from:
- collection-led shopping rather than a flat catalogue
- obvious separation between singles, graded cards and sealed products
- prominent live stock / condition language
- direct "add to cart" behaviour from collection grids
- set-based discovery
- "latest singles", "under £10", graded/slab and sealed merchandising
- strong presentation of graded inventory as centrepiece stock
- simple, confidence-building copy around condition and delivery
- large catalogue handling with compact product grids

Drop Rate should exceed this by adding:
- multi-game first-class support from day one
- exact-print recognition and "scan to find"
- richer TCG-native filters
- grouped display of multiple physical copies without losing Inventory-ID ownership
- real market-value context
- dynamic new-stock, movers, liquidity and scarcity collections
- integrated consignment/sell flow
- graded slab photos tied to the exact physical inventory item
- more modern mobile UX and faster search

### TCG Automate — operations / Founder HQ benchmark

Useful patterns to learn from:
- fast scan-to-identification workflow
- batch creation and batch editing
- suggested matches / quick corrections
- lightning-fast card search
- reusable pricing rules
- cross-listing and coordinated inventory
- duplicate-listing detection
- scheduled repricing
- scanner/device integration
- high-throughput seller workflows

Drop Rate should exceed this by adding:
- exact physical-printing recognition rather than card-number-only matching
- first-class owner / consignor attribution
- deterministic settlement accounting
- full auditability
- exact inventory-item media and slab handling
- pricing based on normalized multi-source evidence
- consumer-facing recognition features
- tightly integrated Shopify storefront intelligence
- Action Required queues instead of hidden failures
- modular device bridge for scanners, printers and label workflows

## Core product principle

The backend and storefront are separate concerns:

- Supabase/Postgres = source of truth
- FastAPI = deterministic business rules
- Shopify = storefront, cart, checkout, customer/order surface
- n8n = orchestration only
- AI = copy, interpretation, support and creative assistance
- AI must never silently alter ownership, exact identity, pricing rules, settlement or publication gates

The customer should experience a simple store even though the backend tracks exact physical copies.

## Current customer-storefront maturity

Current storefront experience is approximately 10–15% of the desired Drop Rate experience.

The backend Shopify integration is significantly further ahead:
- product planning
- Inventory ID / SKU mapping
- price sync
- media readiness
- shipping profiles
- product completeness checks
- Shopify read-back verification
- order webhooks
- refund/cancellation handling
- ownership attribution
- deterministic settlement support

The missing layer is the customer-facing theme, discovery, merchandising and storefront automation.

## Storefront architecture

Initial approach:
- Shopify Online Store 2.0
- custom Drop Rate theme
- theme source controlled in GitHub
- development theme → automated checks → desktop/mobile visual QA → production theme
- avoid headless/Hydrogen until Shopify Liquid genuinely becomes a constraint

Do not edit production theme ad hoc.

Theme releases should be versioned and reversible.

## Storefront information architecture

Primary navigation:
- Pokémon
- One Piece
- Dragon Ball
- Naruto
- New Drops
- Graded
- Grails
- Sell Your Cards

Game pages should support:
- Sets
- Singles
- Graded
- Promos
- New Releases
- Under £5 / Under £10
- Highest Value
- Latest Stock
- Trending / Movers when data is strong enough

## Homepage blueprint

The homepage should be database-driven rather than manually rebuilt every week.

Recommended hierarchy:

1. brand / value proposition
2. dominant predictive search
3. Shop by Game
4. Just Dropped
5. Grails
6. Trending Now
7. Graded
8. Set Spotlight / Shop by Set
9. Price Movers
10. Fresh Japanese Stock
11. Sell / Consign CTA
12. Trust / condition / shipping / authenticity messaging

The homepage should stay clean and premium. Anime/gaming energy should appear through typography, motion, framing and iconography rather than clutter.

## Search blueprint

Search is a first-class product feature.

A customer must be able to search naturally by:
- card name
- card number
- set name
- set code
- rarity
- variant
- language
- condition
- grader
- grade

Examples:
- OP11-118
- Charizard 4/102
- Nami Round 1
- PSA 10 Luffy
- Japanese OP15

Ranking should favour:
1. exact collector/card number
2. exact normalized card name
3. exact set / set code
4. exact printing / promo family
5. fuzzy name matches

Initial implementation may use Shopify metafields and Search & Discovery.
Longer term, build a Drop Rate search service over canonical Postgres data and expose only safe public fields.

## Collection / product-grid blueprint

Desktop:
- compact, image-led 5–6 card grid where screen width allows

Mobile:
- purpose-built 2-column grid
- no desktop layout simply shrunk down

Card tile should surface:
- image
- name
- card number
- rarity
- language
- condition or grade
- price
- stock/copy indicator when useful

Avoid excessive metadata.

Graded cards should show the actual slab photo, not cropped canonical artwork.

## Duplicate physical-copy UX

Internally:
- every physical item remains a unique Inventory ID
- owner attribution never changes

Storefront:
- avoid flooding collections with visually identical products

Target grouped presentation:
- canonical card shell
- "from £x"
- number of available copies
- English / Japanese / Graded options
- customer chooses an exact copy or condition/grade

The sale must still resolve to one exact Inventory ID.

Do not weaken the inventory model to achieve grouped storefront UX.

## Product page blueprint

Raw-card PDP:
- large front image
- zoom
- optional physical back photo
- name
- card number
- set
- rarity
- language
- variant
- condition
- price
- stock/copy options
- shipping/dispatch confidence
- related cards / same set
- concise factual description

Graded PDP:
- actual slab FRONT
- actual slab BACK
- grading company
- grade
- certificate number
- exact printing
- language
- high-resolution zoom
- grader verification link where legally/technically permitted

Do not fabricate slab imagery.

## Market-value UX

Future PDP may show:
- Drop Rate Price
- Market estimate
- freshness timestamp
- simple explanation/source confidence

Do not present market value as guaranteed resale value.

Detailed charts should be deferred until data quality is strong and the UI remains understandable.

## Filters

TCG-native filters should include where applicable:
- set
- card number
- rarity
- colour
- card type
- language
- variant / finish
- condition
- graded / ungraded
- grader
- grade
- price
- in stock
- promo / event / stamped

Each game's filter vocabulary should be data-driven rather than globally hard-coded.

## Autonomous merchandising

Collections should be generated from backend facts wherever possible.

Examples:
- New This Week
- Just Dropped
- Under £5
- Under £10
- PSA 10
- ACE 10
- One Piece Grails
- Fresh Japanese Stock
- Low Stock
- Biggest Movers
- Trending
- Most Viewed
- Recently Restocked

No founder should need to manually drag hundreds of products into collections.

## Autonomous Shopify management

Target automation capabilities:
- create product
- update product
- sync price
- sync quantity
- upload/replace media
- update description
- update SEO
- update tags/metafields
- assign collections
- publish approved stock
- archive sold stock
- restore approved returned stock
- detect Shopify drift
- repair safe drift
- retry transient failures
- escalate unsafe failures to Action Required

Actions that remain deterministic/human-gated:
- ownership changes
- acquisition-cost changes
- exact identity overrides
- high-value uncertain recognition
- suspected counterfeit
- pricing-rule overrides
- settlement adjustments
- money movement
- rights/media disputes

## Listing-content automation

AI may generate:
- title refinement
- product description
- SEO title
- meta description
- image alt text
- safe tags
- structured copy

Input comes from verified backend fields.

AI must not invent or change:
- game
- card number
- set
- printing
- language
- condition
- grade
- owner
- price
- stock

Generated copy must pass deterministic validation before Shopify write.

## Recognition-powered customer features

Planned differentiators:

### Scan to Find
Customer photographs a card → recognition → exact match → current Drop Rate stock.

### Scan to Sell / Consign
Customer photographs cards → provisional identification → submission basket → consignment workflow.

### Collection matching
Future option to compare a user's collection/wishlist against live inventory.

These features reuse the same recognition engine without exposing private seller/owner data.

## Founder HQ UI/UX blueprint

Founder HQ should combine:
- Drop Rate's anime/gaming brand language
- TCG Automate-style high-throughput operational clarity
- strong desktop density
- first-class mobile workflows

Primary principles:
- Action Required first
- exceptions, not routine work
- dense inventory where useful
- fast search
- batch actions
- keyboard-friendly desktop flow
- camera-first mobile scan flow
- clear evidence/confidence
- no hidden automation state
- no ambiguous owner state
- every external sync visibly shows status/error/retry state

Key operational surfaces:
- command-centre Dashboard
- Inventory
- Scan / Recognition
- Batch Intake
- Media & Condition
- Pricing / Market Evidence
- Shopify / Marketplace Sync
- Sales
- Settlements
- Payouts
- Consignments
- Action Required
- Analytics
- Settings / Devices

## Founder HQ improvements to build

1. Recognition workstation with exact-print evidence, runner-ups and quick correction.
2. Batch scan/edit workflow inspired by the speed of TCG Automate, but with stronger ownership and exact-print controls.
3. Device Bridge UI for scanner/printer selection, health and job status.
4. Print labels directly from approved inventory.
5. Compact 5–7-card desktop inventory grid option for visual browsing plus dense table view.
6. Mobile scan/intake that is not a shrunken desktop UI.
7. One universal Action Required queue.
8. Batch pricing review with evidence.
9. Marketplace sync health and retry centre.
10. Owner/consignor settlement drill-down.
11. Live operational metrics without decorative dashboards that do not drive action.

## Major identified risks / corrections

### Exact-print identity
Same card number may have base, parallel, promo, stamped, event and regional versions.

Correction:
- keep CARD and PRINTING identity separate
- never substitute base art for an exact-print claim
- maintain promotion/printing families
- verified fingerprints only

### Reference-media quality
A plausible image can still be wrong, as demonstrated by OP01-017 Nico Robin FILM RED vs 1st Anniversary.

Correction:
- card-by-card exact-print verification
- provenance
- language checks
- trust state
- no fingerprint training from unverified references

### Graded inventory
Canonical artwork is not enough for the item being sold.

Correction:
- actual slab front/back at INVENTORY_ITEM scope
- certificate number
- slab photo primary
- canonical artwork remains reference/recognition evidence only

### Duplicate storefront clutter
Multiple physical copies may overwhelm collection pages.

Correction:
- preserve exact physical Inventory IDs internally
- group visually at storefront layer where safe
- choose exact copy deterministically at purchase

### Search quality
Generic Shopify search may not be enough for TCG-specific behaviour.

Correction:
- rich metafields immediately
- design for dedicated Drop Rate search service later

### Pricing trust
Provisional/weak market evidence can create incorrect customer prices.

Correction:
- source quality + recency + liquidity rules
- UK/EU anchors
- robust statistics
- deterministic price gates

### Marketplace drift
Shopify/eBay state may diverge from Postgres.

Correction:
- Postgres remains truth
- read-back verification
- periodic reconciliation
- safe auto-repair
- Action Required for unsafe mismatches

### Multi-owner risk
Wrong Inventory ID selection can pay the wrong person.

Correction:
- no ownership inference from Shopify title/product
- exact SKU/Inventory linkage
- multi-owner/same-card production tests
- immutable sale snapshots

### AI overreach
AI-generated actions can silently corrupt deterministic data.

Correction:
- AI content only within strict schemas
- deterministic validation
- no direct authority over ownership, settlements, identity or final price

### Performance
5,000–50,000+ inventory requires careful UI and image delivery.

Correction:
- pagination / virtualisation
- image thumbnails/CDN
- compact grids
- indexed search
- async background orchestration
- avoid loading full media payloads unnecessarily

## Storefront visual direction

Target:
premium trading platform × anime/gaming culture × modern collectible marketplace.

Use the established Drop Rate language:
- deep navy / near-black
- turquoise
- gold
- orange/red energy accents
- compass/card/ribbon iconography
- restrained anime/manga-inspired motion

Customer storefront should be cleaner than Founder HQ.

Cards and slabs are the visual hero.

Avoid:
- generic Shopify theme appearance
- overly childish anime styling
- excessive gradients/glows
- unnecessary carousels
- animation that slows shopping
- giant product cards that reduce browsing density

## Build order for storefront

1. Storefront architecture and data contract
2. Storefront design system
3. GitHub-managed Shopify OS 2.0 theme
4. Homepage
5. navigation / mega-menu
6. predictive TCG search
7. collection pages
8. filters
9. product-card component
10. raw-card PDP
11. graded-card PDP
12. cart
13. Sell / Consign landing flow
14. data-driven collections
15. AI listing-content pipeline
16. automated Shopify drift manager
17. recommendations / personalization
18. Scan to Find
19. Scan to Sell / Consign
20. conversion/performance optimisation

Each phase must include:
- desktop QA
- mobile QA
- accessibility
- performance
- structured-data/SEO checks
- Shopify read-back/integration checks
- failure-state testing

## Current release priority

Do not let storefront cosmetics distract from the current correctness gates.

Near-term priorities remain:
1. exact recognition/media corpus
2. Dragon Ball reference coverage
3. graded slab capture
4. multi-owner isolation test
5. multi-owner sale attribution test
6. trusted market-data automation

Once these are stable, storefront implementation becomes a major visible build phase.
