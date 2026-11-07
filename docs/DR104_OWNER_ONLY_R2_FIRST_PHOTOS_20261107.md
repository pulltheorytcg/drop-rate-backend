# DR104 — Verified owner-only physical photos in the R2-first Seller Hub

**7 November 2026. Scope: first deliverable after the independently verified DR101 private Worker deployment.**

## 1. What is built

When a signed-in owner browses an R2-first game (Yu-Gi-Oh!, Lorcana, MTG or later supported systems), the browse response may provide `owner_inventory_image_path` **only** for one unique physical item already owned by that current owner, with an APPROVED, rights-VERIFIED, ACTIVE, non-revoked, `FIRST_PARTY_CAPTURE` front photograph that has completed its existing photo-processing flow.

The image appears through the already-existing authenticated `/api/v1/owner/inventory/{inventory_id}/image` route. The browser uses its bounded authenticated image queue, not unauthenticated `<img src>` and not a public CDN. It is labeled as a photo of the owner's own physical copy, not as a reusable reference or product image.

**The fallback does not manufacture or download artwork.** If no eligible copy photo exists, the old honest artwork-unavailable state remains. Multiple physical copies do not silently inherit one copy's photo. Graded items require an approved exact-item `GRADED_SLAB` photo.

## 2. Why it belongs

The original R2-first catalogues intentionally omit unlicensed provider artwork, and this should not prevent a founder/consignor from seeing a genuine, separately approved photograph of **their own copy** when browsing their collection.

Live 7-Nov audit: the approved `tcg_private.r2_first_catalogue_publications` contained YGO 45,418, Lorcana 3,505, and MTG 153,662 stored / 151,613 released references. `tcg_private.r2_first_catalogue_links` currently has **zero rows**, and there are **zero** approved `FIRST_PARTY_CAPTURE` media assets. This release cannot, by itself, make any currently missing global catalogue artwork appear. Approved photo uploads and exact ownership links are the real prerequisites.

## 3. Connections and trust boundaries

Published R2 source identity + exact source-manifest SHA → owner-scoped SQL link → one currently owned physical `inventory_items` record → approved owner/item `media_assets` photo → existing authenticated owner image route → Seller Hub grid/detail.

All owner IDs come from the authenticated owner context, not request text. SQL rechecks the source manifest, `i.owner_id`, `m.owner_id`, `FIRST_PARTY_CAPTURE`, `APPROVED`, `VERIFIED`, `ACTIVE`, unrevoked, front image, READY processing and a trusted existing image URL. The image endpoint rechecks owner membership/rights independently. No owner photo is published to a shared R2-first canonical record, Shopify, a public D1 image route or other owners. Price/ownership state remains unchanged.

## 4. Failure points

- No source link, stale source manifest, no owned copy, missing photo or pending approval: **no photo URL**.
- Multiple copies of the same reference: **no arbitrary copy selection**; inspect individual inventory instead.
- Graded slab with generic scan/provider raw image: **not eligible**; requires exact `GRADED_SLAB` owner photo.
- Revoked rights, inactive source, failed processing, missing CDN/public-source URL: **not eligible**.
- Wrong or stale owner session: authenticated image route returns failure; the UI keeps an unavailable state rather than using a foreign photo.
- No new-game provider commercial licence: **does not make unlicensed YGO/Lorcana/MTG art publishable**.

## 5. Tests and verification

- Python tests cover exact published-manifest binding, RLS predicates, one-copy gating, no cross-owner leak, copy-specific capture constraints and no fallback to raw/slab substitutions.
- JavaScript catalogue browse receives the image path only if it matches the exact inventory-photo route pattern; the existing request-image queue fetches it with authentication and safe retry behavior.
- Full backend, dashboard and n8n CI must pass before merging/deploying.
- Runtime acceptance after actual user upload: one genuine first-party raw/photo and one graded slab photo in the correct owner's collection, on desktop and mobile, plus negative tests for another owner and a revoked photo. **Not claimable until such media exists.**

## Remaining #966 release work

1. Obtain/verify appropriate game-specific commercial media permissions or founder-owned first-party captures. YGOPRODeck API usage alone is not carte blanche for commercial Konami art; Lorcast's community API does not grant Disney/Ravensburger storefront rights; MTGJSON MIT dataset doesn't license Wizards artwork.
2. Build/approve exact-print candidate assets, verify raster bytes/format and SHA-256, and keep R2 immutable/private. Use the successfully deployed private Cloudflare Worker for signed staging, not public image delivery.
3. Authorize a separate rights-gated customer-facing resolver, never the private shadow endpoint. Run small 25-print visual pilot per source before scaling.
4. First-party graded slab front/back photographs must be captured for the existing action-required backlog and verified in actual Shopify listings.

This stage is **owner-only photo display plumbing, not a completed all-game artwork rollout**.
