# DR105 — Official-first image selection for ordinary raw Shopify cards

**Date:** 7 November 2026. **Status:** release candidate, behind normal PR CI.

## 1. What is being built

When a scan creates a physical inventory item, the original scan photo remains attached to that exact Inventory ID as copy-specific capture evidence. For an ordinary raw card that does **not** require mandatory first-party product photography, Shopify listing selection should **prefer a matching, approved, rights-verified and Shopify-READY official/canonical card image**, even if a physical scan has also been approved.

This changes the order in `backend/app/media_resolver.py`, not the scan upload, canonical card identity, media database, object storage, or Shopify API. It does not force an upstream image to become approved, nor delete or replace a scanner photo. When no eligible official image exists, an already-approved first-party scan remains the fallback for an ordinary low-risk raw card.

For graded slabs, high-value raw, sealed and comics that require exact-item photo evidence, the previous mandatory physical-image rules and appropriate front/back requirements remain unchanged. A grader's cert lookup can inform the precise slab record but must not cause a raw-card thumbnail to be used as the slab image.

## 2. Why it belongs

The latest requested workflow is **scan once → retain the scan per physical item → use official card artwork as the storefront primary image**. Previous implementation prioritised an approved scanner photo ahead of valid canonical art for every raw card, so stores with both could display a photograph rather than the official image.

## 3. Architecture

Scanner `scanner-flow.js` → existing idempotent owner inventory intake / owner photo upload → `tcg.media_assets` exact copy evidence. Separately approved canonical media is linked by immutable `catalogue_id`, matching product language/variant and `STOREFRONT_ALLOWED` rights. Deterministic FastAPI resolver selects the appropriate existing Shopify MediaImage file IDs. No n8n business-rule copy or automatic cross-owner physical-photo reuse.

**eBay is deliberately unchanged:** the live UK listing contract requires a reviewed physical FRONT and BACK for used-card listings. Whether eBay accepts catalogue stock images for a specific item condition/category is a distinct policy check; an upload acceptance alone is not an image licence. No watermark or SAMPLE image removal is introduced.

**Grader certificates are deliberately unchanged:** PSA may return exact-cert front/back photo locators, BGS/ACE/CGC may require supported/manual lookup. Cert lookup and image copyright/usage rights are separate from automatic Shopify republication.

## 4. Failure points and tests

- Wrong set/card identity: canonical `catalogue_id` mismatch → never selected.
- Wrong language or artwork variant: refuse the canonical image; if this is an ordinary low-risk raw copy, use only its own reviewed first-party scan as fallback.
- Missing/revoked approval or Shopify unready media: cannot become official primary.
- High-value and graded: mandatory actual-copy photo capture still wins; never publish raw canonical artwork as a slab image.
- No image available: return the established Action Required blocker rather than fabricate artwork.
- Duplicate idempotent scan save and retries: untouched by this image ordering PR.

Tests: `tests/test_media_resolver.py`, existing `tests/ui/scan-photos.cjs`, full backend/dashboard/n8n CI and existing PostgreSQL RLS/image safety integration. After merge and Railway rollout, verify a signed-in item with both approved official and scan photos and inspect its Shopify readiness/media selection; no product mutation occurs in the test.

## 5. Remaining jobs

- Verify actual scan photo stored on a real user item, with duplicate upload and account-switch testing.
- Review official-image source usage permissions for new games, stage licensed/appropriate exact-print assets through private R2 and verify byte readback.
- Link approved canonical media for Yu-Gi-Oh!, Lorcana, Magic and Riftbound where legal source access exists.
- Add safe, source-specific grader cert image preview and then channel publication only when permitted; preserve original slab photos.
- Perform 25-image source-by-source visual acceptance, storefront/mobile and eBay API checks. Do not assert success from an image URL or synthetic test alone.

