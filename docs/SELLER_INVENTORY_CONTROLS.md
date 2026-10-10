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
