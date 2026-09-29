# Drop Rate — Storefront + Founder UX Blueprint

_Last updated: 29 September 2026_

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

## 29 September 2026 — storefront browse implementation checkpoint

The first storefront-first implementation slice is now deployed only to Shopify's
**unpublished** `Drop Rate — Brand Redesign` theme
(`gid://shopify/OnlineStoreTheme/202073866587`). The live `Horizon` theme remains
untouched.

Verified Shopify catalogue snapshot at implementation time:
- 464 Shopify products total in the Drop Rate trading-card catalogue
- 95 ACTIVE products currently eligible to appear on the storefront
- 369 DRAFT products remain unpublished
- 202 products are in the Pokémon smart collection
- 262 products are in the One Piece smart collection
- 457 raw-card products and 7 graded-card products exist across the catalogue
- Dragon Ball, Naruto and Riftbound collections currently contain no products

The browse slice now:
- keeps a compact two-column mobile product grid and small-card desktop layout;
- adds collection product counts;
- adds responsive All Cards / Pokémon / One Piece / Singles / Graded navigation;
- exposes game-specific set navigation only where the collection exists and has products;
- hides empty game/category destinations from this browse strip rather than routing customers
  into empty catalogues;
- shows language, condition or grader/grade, and rarity badges using Drop Rate metafields with
  Shopify tag fallbacks;
- shortens operational Shopify product titles for browse cards while retaining card number/set
  context;
- preserves Shopify-native filtering, sorting, infinite scroll, cart and checkout behavior;
- introduces no ownership or pricing decisions into Liquid.

The exact Drop Rate-specific theme files touched by this slice are mirrored under
`storefront/theme/**` in GitHub. This is currently a source-controlled overlay rather
than a full copy of Shopify's base theme.

**Known gap:** sealed inventory is not yet represented consistently in Shopify catalogue
classification, so a Sealed browse lane is intentionally not fabricated in the theme.
The data classification must be made deterministic before that navigation is added.

**Status: IN PROGRESS.** This slice is not publish-ready until desktop/mobile preview QA,
failure-path checks and the remaining Milestone 1 browse requirements are completed.

## 29 September 2026 — grouped-copy PDP implementation checkpoint

The second storefront-first implementation slice is now present on Shopify's
**unpublished** `Drop Rate — Brand Redesign` theme. The live `Horizon` theme remains
untouched.

### Grouping contract

Grouped copies are derived from the canonical Supabase `catalogue_id`, never from fuzzy
title/name matching. A canonical card may therefore have several physical inventory items
with different condition/grade while preserving exact game, set, collector number,
language and variant identity.

The existing commerce model remains unchanged:
- one Shopify product/variant still represents one exact physical Inventory ID;
- Shopify cart/checkout therefore still buys that exact copy;
- ownership attribution continues through `tcg.shopify_inventory_links`;
- no owner/consignor identity or acquisition cost is exposed to Liquid;
- Supabase/FastAPI remains authoritative for identity, ownership and deterministic pricing.

### Shopify copy-group metadata

The backend now supports derived product metafields:
- `drop_rate.catalogue_id`
- `drop_rate.copy_handles` (`list.single_line_text_field`)
- `drop_rate.copy_group_size`
- `drop_rate.copy_group_truncated`

After a physical copy is published through the guarded Shopify path, the backend refreshes
the grouped-copy metadata across every still-published sibling for the same canonical card.
A metadata-refresh failure is logged and reported in the admin response but does not undo a
successfully verified product publication or change the physical sale model.

Shopify Liquid's `all_products` lookup is capped at 20 unique handles per page, so the
metadata helper has the same hard safety limit. For an unusually large group, every PDP
retains its own physical copy and up to 19 siblings and marks the group as truncated.

### PDP behavior

The unpublished product template now:
- shows **“N copies available”** and **“From £X”** for grouped inventory;
- renders a thumbnail, condition or grader/grade, language and exact price per available copy;
- visibly marks the current physical copy;
- links a different copy to that exact Shopify product URL;
- uses Shopify `product.available` so sold/unavailable siblings disappear without theme-side
  ownership logic;
- keeps the existing native Shopify Add to Cart / accelerated checkout button attached only
  to the currently selected physical product;
- naturally prioritises a physical slab image when that exact graded product owns the
  approved storefront media.

### Real production-backed proof data

Seven canonical groups currently have multiple published copies (14 active Shopify products
total). Their existing product metafields were backfilled without modifying price, product
status, inventory quantity or ownership. Direct Shopify verification confirmed shared
copy-handle metadata and `availableForSale=true`/quantity 1 for representative One Piece
(`OP16-071`) and Pokémon (`020/108`) pairs.

The exact changed theme files are source-controlled under `storefront/theme/**` and were
verified byte-for-byte against the unpublished theme.

**Status: IN PROGRESS.** GitHub backend/theme contract CI is green. Remaining gates are
browser/mobile visual QA and one add-to-cart/checkout smoke test proving a selected sibling
still resolves to the exact Inventory ID before the grouped PDP slice can be called complete.

## 29 September 2026 — exact-copy cart implementation checkpoint

The third storefront-first slice keeps Shopify's native cart and checkout while making the
one-physical-item model explicit to the customer.

For products carrying a Drop Rate `inventory_id` metafield, the unpublished Brand Redesign
cart now:
- shortens the operational Shopify title to the customer-facing card name;
- shows collector number/set plus condition or grader/grade and language;
- displays **1 physical copy** instead of presenting the item like bulk inventory;
- leaves Shopify's quantity component in the DOM but sets `can_update_quantity=false` for
  tracked physical items;
- keeps the normal Shopify remove action;
- leaves native Shopify cart/checkout submission untouched.

This UI lock is defence in depth rather than the stock authority. Representative live
physical products were independently verified as Shopify `inventoryPolicy=DENY`,
`inventoryQuantity=1` and `availableForSale=true`, so Shopify itself also prevents a
customer purchasing two units of the same physical card.

The cart Liquid reads only customer-safe product metafields. It does not expose owner,
consignor, acquisition-cost, ledger or settlement data. Checkout continues to submit the
exact Shopify variant/SKU already mapped to one `tcg.shopify_inventory_links` row.

**Status: IN PROGRESS.** Remaining gates are CI, mobile/desktop visual QA and a complete
cart→checkout smoke test on the unpublished storefront before this slice can be called
complete.

## 29 September 2026 — Shopify-native search v1 checkpoint

Launch search remains intentionally simple and Shopify-native. No custom search backend,
vector index or AI ranking layer is required for v1.

The unpublished Brand Redesign search form now:
- searches Shopify products only;
- keeps partial matching on the last term;
- places unavailable products after available matches;
- uses the TCG-specific placeholder **Search a card, set or collector number…**;
- explains that customers can search by card name or collector number;
- reuses the same compact Drop Rate result cards, filters and two-column mobile layout
  already used by collection browse.

This works with the existing product-title contract, which contains both canonical card
name and collector number. Connected-store verification confirmed free-text Shopify product
search matches real active inventory for both `OP16-071` and **Benevolent King**, and
also matches **Eiscue ex**.

Search v1 therefore introduces no new source of truth and no synchronisation problem:
Shopify searches the products already published by the guarded catalogue pipeline.

**Status: IN PROGRESS.** Theme behavior is implemented on the unpublished theme. Remaining
gates are CI and browser/mobile visual/result QA before launch.

## 29 September 2026 — Shopify-native customer account / order surface

The final base-commerce surface uses Shopify **New Customer Accounts** rather than a
Drop Rate customer-auth implementation.

Verified store configuration:
- `customerAccounts=OPTIONAL`
- `customerAccountsVersion=NEW_CUSTOMER_ACCOUNTS`
- login links are visible on the storefront and checkout
- login is **not** required at checkout, so guest purchase remains available
- Shopify hosts the customer account/order-history experience at its customer-account URL

The unpublished Brand Redesign header already uses Shopify's native
`<shopify-account>` component whenever customer accounts are enabled. This account
surface is intentionally isolated from Founder HQ and Seller Hub:
- no `/owner` route is referenced;
- no Drop Rate/Supabase customer password flow is created;
- no owner, consignor or PLATFORM_ADMIN identity is exposed;
- no custom order-history API is introduced;
- cart and checkout remain separate Shopify-native actions.

The exact account-header snippet is mirrored under
`storefront/theme/snippets/header-actions.liquid` and contract tests enforce that
customer auth cannot drift into Drop Rate's internal owner/admin authentication boundary.

This surface requires no Shopify runtime mutation because the required customer-account
configuration and theme integration were already active. No customer was created and no
real order/account data was accessed during verification.

**Status: IMPLEMENTED / QA PENDING.** The base account/order-history architecture is
complete for v1; visual/browser QA remains part of the unpublished-theme launch review.

## 29 September 2026 — launch QA evidence

A live-data launch QA pass was run against Shopify Admin and Supabase after the browse,
grouped-PDP, cart, search and account slices were merged.

### Verified customer catalogue invariants
- 95 ACTIVE products = 95 Online Store published/visible products.
- Every visible physical card has exactly one Shopify variant.
- Variant SKU equals the Drop Rate Inventory ID.
- Inventory quantity is exactly 1 and overselling is denied.
- All visible products are available for sale at the time of the check.
- Supabase has exactly 95 matching `PUBLISHED` inventory links; all are FOR_SALE,
  APPROVED, unsold, unreserved and positively priced.
- No invalid published inventory rows were found.

### Verified browse/search invariants
- Every route displayed by the current browse navigation has at least one active/visible
  product; intentionally unsupported Sealed routes remain hidden because sealed Shopify
  classification is not yet deterministic.
- Exact active/visible counts include Trading Cards 95, Singles 93, One Piece 87,
  Pokémon 8 and Graded 2.
- Shopify-native search successfully resolves known cards by name and collector number,
  including `Benevolent King of the Waves`, `OP16-071` and Pokémon `020/108`.
- A guaranteed no-result query returns zero products.
- Search runtime files match the GitHub storefront overlay exactly.

### Verified grouped-copy invariants
- 14 live products participate in 7 canonical grouped-copy sets.
- Every `copy_handles` entry resolves to another currently live Shopify product.
- Every sibling carries the same canonical `catalogue_id`.
- Every group includes the current physical product itself.

This evidence is structural/live-data QA, not browser visual QA. The unpublished Brand
Redesign theme remains the only storefront work target until explicit publication review.

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

## CRO + adaptive storefront experimentation

The Drop Rate storefront should be designed from the beginning so important UI surfaces can be experimented on safely without manually forking the theme.

Experimentable surfaces should include:

- homepage hero/message hierarchy
- game-navigation presentation
- collection-card density
- product-card information hierarchy
- CTA text and placement
- raw vs graded reassurance content
- related-card recommendations
- search-result presentation
- filter defaults
- merchandising module order
- Sell/Consign calls to action
- mobile navigation
- trust and delivery messaging

Theme components should expose stable variant slots/IDs so experiments can switch between prevalidated treatments instead of injecting arbitrary AI-generated DOM.

### Conversion analytics

Use Shopify Web Pixels/customer events plus Drop Rate custom events to measure the funnel.

At minimum track:

- page viewed
- collection viewed
- search performed
- search result clicked
- zero-result search
- product viewed
- recommendation viewed/clicked
- add to cart
- cart viewed
- checkout started
- checkout progression
- purchase
- Sell/Consign CTA
- Scan to Find usage
- filter/sort usage

Final order/revenue truth still comes from Shopify orders + Drop Rate order ingestion, not client-side pixels alone.

### AI-controlled variants

AI may generate variants for approved low-risk fields and components, but the storefront should render only validated variant schemas.

Examples:

- headline + subheadline
- CTA label
- reassurance copy
- section order
- recommendation strategy
- collection sort policy
- product-card metadata order
- selected image order
- internal-link module

Do not give AI unrestricted theme-code write access for autonomous experiments.

### Performance guardrail

A treatment that improves conversion while materially damaging page speed, accessibility, mobile usability or error rate is not a valid winner.

Performance metrics are part of the experiment guardrail set.

### SEO experimentation

SEO and CRO must share learning but use different assignment rules.

SEO changes stay crawlable and consistent to users/crawlers. Do not use user-agent cloaking.

Prefer template/cohort experiments across comparable:

- game collection pages
- set collection pages
- graded category pages
- evergreen buying/selling guides
- other genuinely useful inventory-backed landing pages

The AI may autonomously promote proven low-risk SEO treatments only after deterministic validation and a configured evidence threshold.

Detailed orchestration and authority model: `docs/N8N_AUTOMATION_FOUNDATION.md`.

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

## Native Founder App — iOS + Android

Founder HQ must also become a first-class native mobile product.

Reference category inspiration includes Collectr, Pulse TCG and HoloDex-style mobile collection/market experiences, while Drop Rate remains focused on operational seller workflows, exact physical inventory and marketplace automation.

### Architecture

- shared FastAPI/Supabase backend with Founder HQ web
- native/cross-platform mobile client; preferred implementation path is React Native + Expo unless a later technical spike proves Flutter/native Swift/Kotlin materially better
- no separate mobile source of truth
- no business logic duplicated in the app
- APIs must remain versioned, mobile-safe and permission-aware
- offline-tolerant capture queue where useful, but mutations sync through authenticated backend APIs
- push notifications for Action Required, sales, sync failures, consignor events and payout/settlement events

### Mobile app principles

- not a webview wrapper
- camera-first
- thumb-friendly one-handed operation
- fast enough for stock intake on a shop floor/table
- every scan should lead naturally into identity → exact printing → inventory → condition/media → price → listing
- mobile should expose only the controls useful in the field; dense financial/admin work can remain richer on desktop

### Core mobile surfaces

1. Home / command centre
2. Scan
3. Inventory
4. Card detail / exact Inventory ID
5. Batch intake
6. Media & condition
7. Pricing / market evidence
8. Shopify / marketplace sync status
9. Sales
10. Consignments
11. Action Required
12. Notifications
13. Account / devices

### Camera + recognition

- instant rear-camera launch from Scan
- live framing guidance
- burst/auto-capture when stable
- exact-print candidate results
- runner-ups
- confidence/evidence explanation
- one-tap correction
- barcode/QR support where useful
- slab-aware capture for graded cards
- retain capture metadata for the controlled learning loop

### Inventory workflows

- add physical card
- assign owner
- cost / condition / grade / language / location
- scan existing item
- move storage location
- capture front/back media
- approve exact printing
- price review
- publish / unpublish status
- mark exception / counterfeit concern

### Device Bridge

Future mobile/device integration should support:
- label printers
- receipt/thermal printers where useful
- camera/scanner accessories
- Bluetooth/network device discovery
- print job queue/status
- QR/barcode label generation

### Mobile notifications

Push notifications should be event-driven and actionable:
- card sold
- high-value scan needs review
- Shopify sync failed
- eBay sync failed
- price moved materially
- consignment received/approved/sold
- settlement ready
- payout requested/failed
- device/printer offline when a queued job exists

### Mobile security

- Supabase auth / OAuth reuse
- short-lived access tokens
- device/session revocation
- biometric unlock where supported
- role/owner permissions enforced server-side
- no sensitive settlement or ownership rules trusted to the client

### Mobile release sequence

1. API contract hardening for native clients
2. app shell + auth
3. Scan / recognition
4. Inventory search/detail
5. Add inventory
6. Media/condition capture
7. Action Required
8. Sales + notifications
9. Consignment workflows
10. Devices / printing
11. offline resilience
12. App Store / Play Store release pipeline

The web Founder HQ and the native app should share design tokens, terminology and permissions, but each interface should be purpose-built for its device.

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
