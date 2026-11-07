# Seller inventory repair — 10 October 2026

## Report and cause

The reported iPhone Inventory screen used the old read-only seller renderer. It had no item-opening action, editing, quantity controls or inline Shopify actions. Its image query selected approved media only; reference artwork visible in Search was not available there. The displayed Japanese OP-17 single pack has no media row at all.

The exact reported item is `INV-D715B0E9B3C4451BA9095FA233F8A0E5`. Read-only production inspection found a verified canonical identity and a market value, but no selling price, acquisition cost, registered location or approved listing photo. Those publication prerequisites must remain visible rather than being manufactured during a UI repair.

## Repair

Both grid images and list titles open an accessible item dialog. It shows full identity, physical condition/seal/grade, the user's certificate where applicable, market guide, seller price, selected Inventory ID, Shopify state and readiness blockers. The mobile dialog fills the available screen; titles and actions wrap instead of being clipped. Old inventory responses cannot overwrite a newer search or signed-out account.

The seller can save their own Store Price (minimum £1), approve their selling intent and request Drop Rate review, and run the existing Shopify sync for eligible approved For Sale stock. Review requests move Draft to Inspection; they never perform the existing founder-only identity/intake/media approval. Existing automatic Shopify wake-up and publication checks remain authoritative. Market values are not copied into selling prices.

Quantity controls operate on separately tracked physical copies. Increasing quantity requires confirmation and creates one new Draft/Personal Collection copy with no inherited certificate, approval, cost, sale price or valuation snapshot. A persisted idempotency key and database receipt prevent duplicate retries, including concurrent requests. Graded slabs must use their own certificate intake. Decreasing quantity names the exact selected copy, protects it from allocation, uses the existing Shopify/eBay withdrawal logic, then marks it Withdrawn. It never deletes inventory or history. Sold/reserved copies and stale versions are rejected; partial channel failures remain visible and retryable.

Artwork falls back only through exact human-selected reference identities, verified provider mappings or a verified profile's identity-bound reference image. Conflicting artwork is not guessed. The authenticated thumbnail route rechecks ownership, uses the existing bounded trusted-image fetcher and returns a private response. Reference artwork does not become approved storefront media.

The targeted migration adds only an identity-bound reference-image attribute to the already verified Japanese OP-17 single-pack profile. Its official source is [Bandai's Japanese OP-17 product page](https://www.onepiece-cardgame.com/products/boosters/op17/); the inspected `images/others/product_pack.webp` is the Japanese pack, separately linked from the booster box. The migration is idempotent, preserves all existing attributes and changes no physical inventory or media approvals. A later identity change invalidates the display reference.

## Verification gates

Twenty-three executable UI scenarios cover image/detail opening, price validation, approval/sync eligibility, locked inventory, graded exclusions, exact-copy withdrawal, retry keys and account/session cleanup. A refreshed token for the same seller retains a pending inventory response; logout and a changed account discard it. Thirty-five backend scenarios cover owner access, stale versions, physical state restrictions, safe response fields, retry receipts, remote failure and ambiguous/unsafe artwork.

The new PostgreSQL CI gate runs the actual detail/artwork queries and mutations with a restricted role and forced owner RLS. It tests the targeted migration twice, concurrent duplicate additions, cross-owner reads/writes, unchanged foreign stock, price/approval guards and audited withdrawal. Its initial failure was a missing membership-lock permission in the disposable test setup; the fixture now mirrors the verified production column grant. No production permissions were changed.

## Released and verified

- [PR #569](https://github.com/pulltheorytcg/drop-rate-backend/pull/569) merged as `a40b733b7b0ab8d741840bcf5d57d2c965d1545b` after all five jobs passed on exact head `c4ad7a46b978f5afe9ee63c2fa4fc5129b4066b0`. [Backend CI](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/38058891524) passed 5,030 tests, the complete dashboard suite and the n8n image check. [Inventory CI](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/38058891707) passed real PostgreSQL and Chromium fixtures at 430×932 and 1440×1000. Screenshots are retained in its `seller-inventory-layout` artifact.
- Supabase applied the reviewed profile-only migration as `20261010141736_inventory_op17_reference_artwork`. The actual production reference-artwork SQL returns exactly the official Japanese OP-17 single-pack URL. Detail and copy-list SQL were also executed read-only against the reported item.
- Railway deployment `ed11d7e3-3f23-4558-ac56-d9e881a88cb5` reached SUCCESS at **14:18:49 UTC / 15:18:49 London on 10 October 2026**. The unchanged pre-deploy gate passed all 5,030 backend tests and completed. The pre-existing eBay evidence probe still reports provider credit/rate exhaustion; it produces no fabricated value and is unrelated to these controls.
- Live `/health/ready`, `/health/live`, `/owner` and the three changed/new JS/CSS assets return 200 with `Cache-Control: no-store`. Asset bytes match the release. The page loads the detail module before `owner-portal.js?v=owner-v16`. Unauthenticated item detail and reference-image requests return 401.
- Before/after reads show **510 inventory items**, **447 approved media assets**, and identical ownership/Store Price/status/sale-intent fingerprint `8d4c702ab480d0f34873ebc761794d03`. The reported item remains Draft/For Sale at version 3, with £8.66 market value. Its price, intake and approved-photo prerequisites remain visible and mandatory.

The browser test used the actual page/assets with isolated API fixtures and the official image. It verifies image loading, mobile/desktop widths, detail opening, disabled ineligible sync, quantity confirmation and list opening. It is not a fresh signed-in iPhone acceptance test. No real stock was added, withdrawn or published to test the release.

No production stock quantities, selling prices or approval statuses are changed merely to test these controls. No new provider, service, outbox type, external seller activation or Brand Redesign publication is part of this repair.


## 10 October 2026 — Compact inventory presentation (follow-up)

**What:** Keep the Seller Hub Inventory grid and list focused on artwork, verified product name, status, known market value, Store Price/recommended retail and the existing details action. Move Seal/Condition, Language, Type, Game, full physical Inventory ID, grading and certificate metadata into a structured **Item information** section inside the authenticated item-details modal. Show the full ID without truncation. List view likewise has four columns: Product, Status, Market value and Store/recommended price.

**Why:** The original cards expanded to display multiple tiny duplicated metadata rows even at two columns on mobile. The extra rows made inventory difficult to scan and mixed record details with quick-comparison metrics.

**Connections:** The grid/list still render the same server-authorized owner inventory response; item details fetch the existing owner-scoped `GET /api/v1/owner/inventory/{id}`. No new data fields, endpoint, permission, pricing policy, stock command, Shopify integration or n8n workflow is introduced. Image opening, status search/filter, market refresh, approval, sale price changes, Shopify sync and separate physical-copy controls continue to work as before. The Seller Hub visual change does not affect Founder HQ or Shopify storefront.

**Failure points:** Small-screen overflow, long product names/Inventory IDs, missing values, inaccessible detail buttons, list-mode regressions, graded certificate loss, stale or cross-account item requests. These are handled by the existing detail-scoped access checks, touch-sized actions, responsive value columns, wrapping IDs and unchanged session isolation.

**Tests:** JSDOM asserts card/list metadata is absent but status, market/store value and detail actions remain; opening the item displays labelled Game, Language, Seal/Condition, Type, exact Inventory ID and grading details. Existing seller price/approval/sync/quantity/withdrawal tests remain. The Chromium 430px and 1440px browser gate asserts compact-height cards, four-column list, complete details, no horizontal overflow and working edit/quantity entry. Baseline backend, real PostgreSQL owner-isolation and CI remain release requirements.

**Deployment:** Versioned asset URLs ensure the simplified grid and detail styles refresh together. Deploy only through reviewed exact-head CI and Railway pre-deploy gates. The actual signed-in seller-device visual check is separate and must not be claimed from fixtures.

## 10 October 2026 — Same-product quantity and channel readiness

**Issue:** Seller Hub showed two tiles for two identical Japanese One Piece OP17 booster packs, one £8.66-valued and one with value pending. Each is an exact physical inventory record and seller owns two. The store also has **two separate ACTIVE Shopify product/variant records** (one stock each): this is a distinct Shopify publication defect, not repaired by hiding a dashboard tile.

**This Seller Hub release builds:** a deterministic, read-only *display projection* that merges only **approved, for-sale, ungraded, sealed** records when canonical catalogue ID, product/packaging type, language, seal, condition, variant, status and owner-approved Store Price match. Each physical record still exists in Supabase; the owner's total inventory count remains physical-copy count. Show a small `×2` image badge and **one seller card** for these two OP17 items. Details still open the owner-scoped exact physical record, list both Inventory IDs, and permit choosing one copy. Individual sales, Shopify/eBay links, audit, versions, price and ownership remain untouched.

**Partial valuations:** A market value shown for one copy does **not** value all grouped copies. Show `£8.66` with `1/2 copies valued`; never double the market value or silently populate null valuation rows. If an unvalued member has a permitted market refresh action, call the endpoint for that member's own Inventory Code, not the valued representative.

**Cross-channel controls:** A three-column, logo-led, responsive sales-channel row sits in item details below the existing seller-price/approval controls. Use an official eBay design-system logo reference and the Whatnot-owned official Shopify App Store icon. Text remains available for accessibility and failsafe image loading. Shopify uses its existing authenticated versioned exact-inventory sync endpoint. eBay uses the existing endpoint only for **eligible individual cards** on supported owners/accounts and only when the connection/feature flag is ready; the current **consignor-owned SEALED OP17** remains disabled. Server independently blocks unsupported consignor and sealed attempts: the eBay publisher currently has founder-only, physical-photo, condition/cost/location rules, and shared founder eBay OAuth readiness is not a grant of authority to list consignor stock. Do not bypass these rules.

**Whatnot:** Whatnot's Seller API is in restricted developer preview, not accepting new applicants. The recommended UK supported route is its [official Shopify Sales Channel app](https://apps.shopify.com/whatnot), which automatically syncs permitted Shopify products, stock and resulting orders when installed and connected by an authorised store admin. Shopify has **no Whatnot channel installed** as of this audit (four existing channels: Online Store, Shop, POS, Google & YouTube). The Whatnot button is therefore clearly marked `Set up` and opens the actual merchant installation/authorisation flow. It must not claim a live Whatnot listing or call a fake API. The separate Shopify two-product duplication must be solved before using Whatnot to import that pack, or it would import duplicates.

**Failures to avoid:** grouping across languages, pack/box, graded cards, statuses, sell intents or different prices; losing physical ID ownership; attributing unknown values to whole pool; treating an eBay founder-connection flag as consignor authorisation; implying an external channel is connected just because an image loaded; accidentally installing a third-party Shopify sales channel; duplicate Shopify copies on Whatnot; responsive mobile overflow. UI uses compact 3-across cards with touch-sized buttons, disabled status and clear microcopy. Business-side permissions and checkout rules are unchanged.

**Tests:** JSDOM regression on one tile for two exact copies, quantity badge, `1/2 copies valued`, two exact IDs in details, no valuation write, feature-gated eBay disabled, Whatnot setup link, actual logo sources, mismatched condition/status/language/price/card grading non-pooling and API dispatch. Existing real Chromium mobile/desktop visual gates and owner/commerce PostgreSQL gates remain required before merge.

**Known limitation:** this first presentation projection operates on the existing 50-item page; it does not pretend to consolidate physical Shopify products or guarantee single-tile pagination across very large seller accounts. Production-wide grouping requires grouping before SQL pagination, and live **Shopify sealed-pool migration** remains ticket [#576](https://github.com/pulltheorytcg/drop-rate-backend/issues/576), with purchase-webhook in-flight safety and audited physical allocation. Do not archive Shopify duplicates just to match the UI without that migration.

**Trademark:** the marks are used only to identify external platforms in an authenticated operational dashboard; attribution/source does not itself grant trademark permission. Confirm permitted use of eBay marks under eBay's Developer Program before wider public/co-branded promotion. No Shopify theme or marketing changes here.


## 10 October 2026 — Single Shopify action and consistent channel wordmarks

The 3-across seller channel cards previously mixed a fake Shopify glyph, a small eBay image with an opaque background, and a square Whatnot app badge. A published pack simultaneously displayed `Approve for Shopify` and `Sync to Shopify`, which implied that a successfully published item still needed approval.

**New UI:** The product details section is labelled `Selling price` and always retains a proper Save selling price action for editable copies. Approval is shown only for inventory **not yet approved for sale**, and an explicit Sync to Shopify action appears only when the copy is APPROVED, FOR_SALE, publish-enabled **and not PUBLISHED**. Once published, neither approval nor sync is offered; the Shopify channel card shows `Published` and `Already live`. A seller's save-price action continues to use the existing deterministic backend API; this release does not invent an additional Shopify API workflow.

**Verified channel wordmarks:** The recognised transparent Shopify bag+wordmark, eBay four-color wordmark and Whatnot 2025 wordmark use unaltered SVGs with fixed frames, matching clear-space, `object-fit:contain`, no square app badge or white image background. SVG provenance: Wikimedia Commons' Shopify logo 2018, eBay logo, and Whatnot Logo 2025. Source media is used solely to identify the three named third-party channels in the **authenticated seller operations dashboard**, never to imply partnership or as a public marketing claim. Trademark permissions and usage guidance continue to apply. The Channels overview and product detail cards share the same representation.

**eBay readiness:** eBay v1 only supports individual card inventory, with additional founder and verified physical-photo checks. Seller-held sealed OP17 consignment therefore does **not** present a click-to-publish button. Instead the item clearly shows `Sealed packs aren't supported yet` and `Not available yet`, plus a concise explanation. A real eBay button remains only for eligible connected card inventory. The backend's independent owner/product-type restrictions remain unchanged.

**Whatnot:** The `Set up` action opens `https://apps.shopify.com/whatnot`; only an authorised store admin can complete the connection. It does not claim inventory sync or installation. This is separate from the outstanding live Shopify OP17 variant consolidation (#576/#582).

**Acceptance and rollback:** JSDOM verifies published/no duplicate action, draft approval, ready-not-published sync, actual transparent wordmark URLs, blocked eBay affordances and setup link. The isolated Chromium gate checks logo-frame alignment and transparency, no overflow, and the PUBLISHED screenshot at 430px and 1440px. Versioned frontend assets and stricter `upload.wikimedia.org` image-only CSP support correct client refresh. No database, product stock, consignment, financial or Shopify theme changes.

## 10 October 2026 — Per-seller Whatnot connection correction

The original Seller Hub 'Set up' link opened `apps.shopify.com/whatnot`, which attempts to install an app on the **Drop Rate company Shopify store**, not connect the seller's own Whatnot account. This is incorrect for the user's multi-owner marketplace architecture.

Whatnot's official Seller API supports third-party **seller-specific OAuth** with individual `read:inventory`, `write:inventory` and optional order/shipment scopes, but as of this release its developer-preview programme is **not accepting new API applicants**. Without Drop Rate's approved client credentials and explicit per-seller OAuth grants, Seller Hub must never simulate a connection, store a seller's Whatnot password, or invite the seller to connect their account to the company Shopify admin.

The UI therefore displays **Personal seller connection awaiting Whatnot API access**, with **Not available yet** rather than an active 'Set up' button. The backend reports `DEVELOPER_ACCESS_REQUIRED`, `connection_mode=SELLER_OAUTH`, `sync_enabled=false` and `connected=false`. The official brandmark is retained. This is a truthful fix with no external connection requests, new service, secret storage, sales, accounting or Shopify changes. When Whatnot grants credentials, a separate audited multi-owner OAuth adapter will be required: CSRF state tied to account, token encryption at rest, scope review, webhook signature checks, exact owner inventory links, replay/idempotency, and disconnection.

Official sources:
- https://developers.whatnot.com/docs/getting-started/introduction
- https://developers.whatnot.com/docs/getting-started/authentication


## 10 October — Quantity control clarity after signed-in phone recording

**Symptom and root cause:** On the two-pack Japanese OP17 inventory detail page, + and − previously displayed *only* the next confirmation card. The counter itself was hardcoded to the latest `copies.length` readback, so it remained 2 even after a tap. The user perceived a broken control.

**UI repair:** A tap previews the **proposed quantity** with a visible amber unsaved state and live announcement (2→3 on +; 2→1 on −). Only one unit may be pending at a time: tap the opposite arrow or **Cancel change** to undo it, or use the clear confirm action to create/withdraw that exact physical unit. On success/failure, refresh detail and grid from the server; never permanently set a quantity optimistically. Confirming an increase retains the existing idempotency key and makes a separate DRAFT physical Inventory ID with no inherited certificate, published status, listing media or cost. The message explicitly explains that Shopify remains unchanged until that copy is approved and verified synced. The details view highlights counts needing approval; the existing approved/for-sale grouped tile is not silently inflated.

**Backend and ownership:** Existing `POST /api/v1/owner/inventory/{id}/copies` and `/withdraw` remain the only write paths, version/owner checked and audited. Withdraw protects remote channels before deleting eligibility; history is retained, not deleted. Increasing one approved pooled copy is not permission to skip per-copy review or to create a new public Shopify product automatically. No new schema, money rule, n8n workflow, marketplace provider, owner activation or Shopify checkout/theme change.

**Tests:** JSDOM reproduces exactly 2→3/2→1 pending, cancel and opposite-arrow undo, no write until confirm, exact POST/version, durable re-read, new DRAFT status and replay after ambiguous network failure. Chromium validates 1→2/1→0 on mobile and desktop without invoking a live write. Release requires exact-head CI, successful production API deployment and signed-in handset acceptance. A separate pooled-publication change must be reviewed if the desired next step is **auto-increasing the same Shopify listing upon approving extra units**.
