# Drop Rate — Live Build Status

_Last updated: 29 September 2026_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification where applicable.

## Current progress

- **Full Drop Rate roadmap:** ~65% overall. The core marketplace/MVP path is further ahead at ~82%; the lower full-roadmap number still includes customer storefront work, AI listings, customer service, SEO, marketing, native mobile and the majority of production n8n workflows. The n8n delivery foundation is now implemented in code but intentionally dormant.
- **Milestone 1 — Inventory / ownership foundation:** ~99% for the internal founder build and ~96% against the final three-founder milestone. RBAC, admin-route hardening, dedicated OWNER onboarding, owner-safe inventory/finance APIs, the restricted owner portal, media/condition workflows and inventory-image delivery are deployed. The genuine second-account cross-owner isolation gate has passed; the remaining release gate is onboarding the genuine third founder and repeating production isolation verification.
- **Internal commerce / founder finance foundation:** ~92%; Stripe Connect sandbox transfer/reversal is proven, payout preferences are live and the scheduled payout-request worker is deployed, while real-money execution remains intentionally locked
- **Milestone 2 — Shopify sale attribution:** ~92% technically complete; first real paid sale and full refund/restock path are production-verified, deterministic settlement reporting exists, seller-facing restricted finance views are deployed, and payout control is automated up to REQUESTED state. Multi-owner/same-card production attribution and live Stripe payout cutover remain.
- **Milestone 3 — Automated market valuation/pricing:** ~80% technically complete; provider ingestion remains intentionally gated until source-by-source production approval/validation
- **Customer storefront / Shopify UX:** base-commerce engineering/data-contract QA and the source-controlled visual pass are complete on the unpublished Brand Redesign theme across global shell, homepage, browse, grouped-copy PDP, exact-copy cart/checkout handoff, search and Shopify-native customer accounts. Brand Redesign remains unpublished and the source-controlled overlay now contains **25 files**, including the native facet files changed during mobile QA, with Shopify/runtime parity verified before merge. The live Horizon theme remains untouched. Overall storefront milestone remains IN PROGRESS for the repeat mobile preview smoke, desktop preview smoke and subsequent publication. See `docs/STOREFRONT_LAUNCH_QA.md`.
- **Native Founder app — iOS + Android:** blueprint added. The app will share the FastAPI/Supabase backend with Founder HQ but be a purpose-built camera-first mobile client, not a webview wrapper. Initial priority is Scan → exact-print recognition → inventory/media/condition → Action Required; later phases add sales, consignments, push notifications and Device Bridge printing/scanner workflows.
- **Seller Hub / mobile seller operations:** now materially deployed rather than merely blueprinted. Restricted-owner onboarding, seller-safe inventory/finance views, continuous mobile scanning, batch value totals, match correction, top-valued cards, weekly movers, payout tracking, Shopify/eBay channel visibility, Collectr post-import enrichment, Action Required exceptions and sealed-product media handling are live. Remaining product work is real-world mobile scan tuning, seller-controlled channel actions, third-founder production verification and broader production data-provider coverage.

## 29 September 2026 — controlled Shopify linked-draft launch reconciliation

**SOURCE-CONTROL PR IN PROGRESS / DISABLED BY DEFAULT —** A one-off, resumable
reconciliation worker has been added for the legacy Collectr-linked Shopify draft backlog.
It operates only on already-linked, non-test Shopify products and never creates replacement
products. Exact import identity, per-set language evidence, deterministic price overrides,
existing condition/graded-photo policy, exact Shopify product/variant/SKU, positive stock,
remote image presence and browse collection membership are all enforced before activation.

The worker regenerates Shopify title/description/SEO/tags/metafields from corrected backend
data, publishes Shopify first, and only then marks the corresponding
`shopify_inventory_links` row `PUBLISHED`. A database failure after remote activation
triggers best-effort compensation back to Shopify `DRAFT`. Existing Shopify imagery is
used only as a remote-presence gate for this controlled legacy reconciliation; no fake
`media_assets` or rights claims are created and the standard ongoing media/publish
pipeline is unchanged. Production execution remains pending dry-run validation.

## 29 September 2026 — Shopify linked-draft readiness audit

**DEPLOYED / VERIFIED / READ-ONLY —** PR #306 is merged and deployed to production. Founder HQ now exposes a separate readiness
summary for Shopify-linked `DRAFT` products. This reuses the existing identity, approval,
cost, language, condition/grade, price, location and media gates so the 369-product draft
backlog can be worked safely without bulk activation. The audit performs **zero Shopify
network calls and zero publication actions**; it does not infer missing language, confirm
identity, alter price/quantity or change remote product status. Dashboard output separates
unsynced inventory from already-linked Shopify drafts and exposes their core/media blocker
counts. Production deployment `abf12ed481f8c7e7f0e16270da312c6f78d71a00` passed **1,904 tests** and Railway's `/health/ready` check returned HTTP 200.

The post-deploy inventory baseline is **369 linked Shopify drafts**. After reconciling the already-verified Seel 021/094 English image from Shopify `READY` back into the media registry and approving its previously recorded founder physical review, **1 draft is now core-ready and media-ready** while remaining unpublished. Current linked-draft blockers are: 368 approval status, 368 identity confirmation, 367 card language, 5 graded slab verification and 2 store price. Storefront publication remains gated on refreshed mobile QA followed by desktop QA.

## 29 September 2026 — storefront mobile launch-QA polish

**RUNTIME DEPLOYED / SOURCE CONTROL MERGED / RE-PREVIEW REQUIRED —** review of the real mobile preview recordings found several presentation issues that did not invalidate the base-commerce path but should be fixed before publication. The unpublished `Drop Rate — Brand Redesign` theme now:
- reserves a fixed two-line title footprint on product cards and anchors browse-card purchase actions so long titles do not break grid symmetry;
- removes accelerated checkout from collection/home browse cards while retaining the native PDP/cart/checkout path;
- turns the three-card homepage display into an interactive/automatic spotlight rotation; the active card's product name, price and link move with the front card, tapping a rear card promotes it, manual interaction pauses auto-rotation, and reduced-motion preference disables automatic movement;
- keeps desktop vertical facets expanded but starts mobile drawer facets collapsed unless that facet already has an active value; mobile facet spacing is tightened without replacing Shopify-native Search & Discovery filtering;
- labels grouped physical listings as `Copy 1`, `Copy 2`, etc. while preserving condition/language/grader/grade/price and exact-copy selection behavior.

The runtime edits are confined to the unpublished theme. No live Horizon, product price, inventory quantity, ownership, cart identity or checkout mutation is included. Three native Horizon files that are now intentionally changed by Drop Rate (`blocks/filters.liquid`, `snippets/list-filter.liquid`, `snippets/price-filter.liquid`) are added to the overlay so this behavior is source-controlled rather than existing only in Shopify.

**Language facet finding:** Shopify has one correctly tagged English product, `Seel · EN · 021/094 · Phantasmal Flames`, but it is DRAFT. The current customer-visible ACTIVE catalogue is Japanese, so Shopify correctly exposes Japanese but not English as a live Language value. Filter values remain inventory-driven; do not hard-code empty English/Korean/Chinese values merely to make them appear. English should appear automatically when an ACTIVE collection product carrying `drop_rate.language=English` exists.

**Next gate:** repeat the mobile preview through homepage → collection → filters/sorting → PDP/grouped copies → exact-copy cart → checkout entry → search/no-result → customer account. If that pass is clean, continue immediately with desktop QA. **Do not publish yet.**

## 29 September 2026 — storefront final machine-verifiable gate

**Machine-verifiable storefront gate: COMPLETE / TWO EXTERNAL GATES REMAIN —** the
unpublished `Drop Rate — Brand Redesign` theme is now fully aligned across the active
global brand layer, Shopify current settings/header/footer, homepage, collection/browse,
grouped-copy PDP, exact-copy cart, search and native customer-account chrome. The
source-controlled overlay now contains **22 files**, and the newly added settings/header/
footer files were deployed only after their pre-write Shopify checksums matched the values
captured before CI. Post-write read-back confirms those files match GitHub byte-for-byte;
the previously deployed 19 files had already been independently parity-verified.

Shopify runtime/config checks also pass:
- `Drop Rate — Brand Redesign` remains **UNPUBLISHED**.
- `Horizon` remains **MAIN** and its last update remains
  **24 September 2026 17:17:28 UTC**.
- customer accounts use **NEW_CUSTOMER_ACCOUNTS**; login links are visible, accounts are
  optional and login is not required at checkout, so guest checkout remains available;
- the homepage's four configured feature products are ACTIVE and its Trading Cards,
  Pokémon, One Piece, Graded Cards and four set destinations all resolve with products;
- the `Sealed` collection remains exactly **0 products**, so its count-gated browse link
  stays hidden;
- the old yellow/teal/cream palette is no longer present in the active source-controlled
  brand/component layer. Preset-only Horizon values are not treated as active Brand
  Redesign styling.

Current publication gates:
1. **Shopify Search & Discovery is installed and configured** with the approved native
   filter order: Set, Price, Rarity, Variant, Availability, Condition, Language, Grading
   Company and Grade. Facet values remain inventory-driven.
2. **Visual smoke is in progress through user-supplied preview recordings.** The first
   mobile recording pass verified the base commerce path and exposed presentation issues
   that were fixed in PR #303. A refreshed mobile pass is now required, followed by the
   desktop pass, before publication.

Do **not** publish Brand Redesign or reopen deferred recognition/seller/market-data/
automation scope until the refreshed mobile and desktop storefront gates are intentionally cleared.**

## 29 September 2026 — active global theme settings + footer

**Storefront global shell settings: DEPLOYED / BROWSER QA PENDING —** QA found that, after the active
`dr-brand-system` fix, Brand Redesign's Shopify-managed current palette/footer JSON still
contained legacy teal/cream values. `config/settings_data.json`, `header-group.json` and
`footer-group.json` are now source-controlled and only active colour values are aligned to
the current Drop Rate navy/ink/blue/cool-grey/white system. The existing
`drop-rate-brand-logo.png`, logo sizes, `main-menu`, announcement/footer copy, block IDs
and layout settings are unchanged. No live Horizon, product, price, inventory, ownership,
cart or checkout mutation is included. Completion requires CI, deployment of the exact
three files to the unpublished Brand Redesign theme and source/runtime parity.**

## 29 September 2026 — active global brand layer

**Storefront global brand CSS: DEPLOYED / BROWSER QA PENDING —** QA found the live unpublished theme renders
`dr-brand-system` after `drop-rate-global-styles`. That active runtime snippet still
contained legacy yellow/teal purchase actions and late overrides that flattened the newer
product-card, facet and PDP presentation. The snippet is now source-controlled and narrowed
to current Drop Rate global primitives (navy/ink/blue/cyan/cool-grey/white), gallery media,
product-card purchase controls, focus/header and footer basics. Component-specific
browse/PDP/cart/search styling remains owned by `drop-rate-global-styles`. No product,
price, inventory, ownership, checkout behavior or live Horizon theme change is included.
Completion requires CI, deployment to the unpublished Brand Redesign theme and full
source/runtime parity.**

## 29 September 2026 — homepage visual alignment

**Storefront homepage design/source control: DEPLOYED / BROWSER QA PENDING —** the four custom Brand Redesign
homepage sections are now mirrored in GitHub and aligned to the same current Drop Rate
navy/blue/cyan/cool-grey/white visual system as browse, PDP, cart, search and account.
The older yellow/teal hero/set accents are removed. Native Shopify behavior is preserved:
discovery search remains a product-only GET to `routes.search_url`, product and collection
choices remain theme-editor settings, and no pricing, inventory, ownership, merchandising
decision or checkout rule is moved into Liquid. The live Horizon theme remains untouched.
Completion requires CI, deployment to the unpublished Brand Redesign theme, source/runtime
parity and desktop/mobile preview QA.**

## 29 September 2026 — customer account/header visual alignment

**Storefront account/header presentation: DEPLOYED / BROWSER QA PENDING —** Shopify's native customer account
surface and cart header actions now use the current Drop Rate white/ink/blue/cyan visual
tokens. The `<shopify-account>` component remains the customer auth/order-history surface;
Founder HQ/Seller Hub auth remains separate, guest checkout stays available, and no custom
login or checkout path is introduced. No customer record, product, price, inventory,
ownership, order or live Horizon theme change is included. Completion requires CI,
deployment to the unpublished Brand Redesign theme, source/runtime parity and preview QA
of signed-out/signed-in account handoff on desktop/mobile.**

## 29 September 2026 — search visual alignment

**Storefront search presentation: DEPLOYED / BROWSER QA PENDING —** Shopify-native product search now uses
the current Drop Rate white/cool-grey/blue visual system while preserving the already-tested
v1 search contract: product-only results, last-term partial matching and unavailable
products last. The search field, focus state, help text and no-results state were restyled;
no custom search backend, AI index, query semantics, product data or live Horizon theme
change is introduced. Completion requires CI, deployment to the unpublished Brand Redesign
theme, source/runtime parity and desktop/mobile search/no-result preview QA.**

## 29 September 2026 — cart visual alignment

**Storefront exact-copy cart presentation: DEPLOYED / BROWSER QA PENDING —** the cart now aligns to the
current Drop Rate navy/blue/cyan visual system while preserving Shopify-native commerce.
Customer-safe copy metadata uses compact blue/cyan states, the one-physical-copy lock is
more explicit, and the native checkout CTA is styled in the current blue brand action.
The physical Inventory ID contract, fixed quantity behavior, remove action, exact Shopify
variant and native cart/checkout flow are unchanged. No product, price, inventory quantity,
ownership, order or live Horizon theme change is included. Completion requires CI,
deployment to the unpublished Brand Redesign theme, source/runtime parity and
desktop/mobile cart→checkout preview smoke.**

## 29 September 2026 — PDP visual alignment

**Storefront PDP/grouped copies: DEPLOYED / BROWSER QA PENDING —** the next storefront-first presentation
slice aligns the product page to the current Drop Rate navy/blue/cyan system. The card
heading, deterministic facts panel, one-copy purchase note, grouped-copy selector and
primary add-to-cart action now use white/cool-grey surfaces with explicit blue selected-copy
states instead of the older cream/yellow treatment. Exact sibling handles, current-copy
selection, Shopify variant identity, native buy buttons and accelerated checkout structure
are unchanged. No product, price, inventory quantity, ownership, order or live Horizon
theme change is included. Completion requires CI, deployment to the unpublished Brand
Redesign theme, byte-for-byte source/runtime parity and desktop/mobile preview QA.**

## 29 September 2026 — collection visual alignment

**Storefront collection design: DEPLOYED / BROWSER QA PENDING —** the first visible theme pass after the
storefront engineering gate is now source-controlled. The collection hero, browse chips,
product-card chrome and Shopify-native filter surfaces are aligned to the current Drop Rate
Seller Hub palette: deep navy, blue/cyan accents, cool grey background and white cards,
replacing the older cream/beige treatment on this surface. The browse route also wires the
existing `Sealed` smart collection behind a product-count gate, so it remains invisible
until real sealed inventory is publishable. No live Horizon theme, product status, price,
inventory quantity, ownership or checkout behavior is changed. Completion requires CI,
deployment to the unpublished `Drop Rate — Brand Redesign` theme, source/runtime parity,
and desktop/mobile preview QA.**

## 29 September 2026 — storefront set-facet canonicalization

**Storefront facet data hygiene: COMPLETE —** Shopify collection filtering is already
enabled in the unpublished Brand Redesign template, and all 95 ACTIVE products carry the
core `drop_rate` metafields needed for customer filters. QA found one duplicate-looking
Set value: `Carrying on His Will` versus the canonical `Carrying On His Will`.
The historical one-off migration for this label had already run before a later Collectr
import recreated the provider casing. The import boundary is therefore being hardened with
a narrow known-alias canonicalization rule rather than generic title-casing. Unknown set
labels remain unchanged. This work changes display metadata only; it does not change
catalogue IDs, card numbers, variants, languages, ownership, prices, inventory quantities
or publication state. Completion requires CI, production deployment, a one-row source-of-
truth backfill, Shopify metafield resync and verification that the live Set facet value is
no longer duplicated.**

## 29 September 2026 — sealed Shopify product contract

**Sealed Shopify representation: COMPLETE / PUBLICATION STILL FAIL-CLOSED —** PR #284
ports the sealed-storefront contract onto current `main` without losing the newer media
hardening. `SEALED`/`COLLECTION` inventory now plans as Shopify product type
`Sealed TCG Product`, tag `Sealed Product`, required collections `Sealed` + game,
sealed-specific customer/SEO copy, and shipping key `SEALED_PRODUCT`; it no longer
inherits raw-card tags or the raw-card `Trading Cards` collection requirement. The existing
Shopify `Sealed` smart collection is present and deterministically keys on
`Sealed Product`.

GitHub **Backend checks** passed for PR #284, including the regression proving sealed
publication completeness fails closed when the real sealed shipping profile is absent.
Railway production deployment `a585b073-cba1-4760-b1e2-962f3bf5de16` completed
**SUCCESS** from merge commit `c6f97a53ac3b13a660c5c5d9f8a95f4dd5697210`; the
production pre-deploy suite reported **1,883 passed**, and `/health/ready` returned
**200 OK**.

Post-deploy production read-back confirms only `RAW_CARD` and `GRADED_CARD` shipping
profiles exist. There is still no `SEALED_PRODUCT` profile, so no package weight,
dimensions or carrier assumptions were guessed. Both current sealed One Piece inventory
items remain **DRAFT / FOR_SALE**, identity-unconfirmed and without a Shopify inventory
link/product GID. No schema, inventory, ownership, price, media, Shopify product or live
theme mutation occurred. Sealed publication remains blocked until the normal
identity/seal/media gates and a verified sealed shipping profile are complete.**

## 29 September 2026 — sealed capture-context queue hardening
