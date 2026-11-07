# Shared inventory image delivery — 11 October 2026

## Confirmed mismatch

The current founder grid uses `/api/v1/inventory/{inventory_id}/image` for provider-hosted images, with a limited CDN fast path. Seller Hub tried the remote media URL in an `<img>` and fell back only through the separate reference-library resolver. Approved `media_assets` records were absent from that fallback. The common image endpoint also restricted **all** assets to the current `owner_id`, incorrectly applying uploader ownership to reusable canonical artwork. The live registry RLS already shares CANONICAL_CARD; the later CANONICAL_PRODUCT scope had not been included in that shared read policy.

A read-only production query found approved canonical records for almost all of the inspected seller copies, predominantly official One Piece image URLs, so re-uploading the user's photos or copying media rows between accounts is not the remedy. The observation does not prove every provider URL is healthy or every catalogue record has approved artwork.

## Bounded change

- Seller Hub uses the existing founder image endpoint for provider-hosted artwork, with trusted Shopify/TCGdex direct paths and the existing owner reference endpoint as a secondary fallback. Requests load near the viewport; credentials are sent only to the same-origin owned-item API. Failures remain explicit and bounded; stale session responses are not rendered.
- The shared endpoint first verifies the physical Inventory ID belongs to the signed-in owner. Inventory photos require that same owner and exact Inventory ID. Approved canonical art uses catalogue ID plus exact language/variant, independently of the account which registered the asset. Pending owner media is still only that owner's preview; rejected/dead/revoked sources are excluded. No different slab's picture is represented as the seller's physical copy.
- An additive SELECT-only media policy permits active members to read already-approved, rights-verified CANONICAL_PRODUCT references. No write policy, owner membership, inventory record, media approval, financial record or Shopify state changes. A display request never approves listing media or starts an import.
- Existing bounded HTTPS/raster/redirect/size checks remain; relevant already-supported CardTrader/DBS/Naruto source hosts are usable through the same server transport. Nonstandard ports are refused. No public arbitrary-URL proxy is added.

## Test/verification categories

Real PostgreSQL tests run the actual media registry, rights-governance and product-scope migrations under `tcg_api`, reproduce the old catalogue-owner filter and product-read failures, then verify separate owners see the same approved art while foreign physical photos and writes stay denied. Signed local JWT/JWKS requests exercise the real image API; provider bytes are mocked. Before/after data snapshots prove image reads do not copy stock/media or modify records.

Chromium/WebKit tests execute the actual seller image loader with local response fixtures: blocked provider, missing list metadata, failed CDN, reference fallback, one session refresh, denied requests, invalid image MIME, account switch and no token leakage. Existing seller controls/browser and backend suites remain in CI. These are not real Supabase logins or physical-phone acceptance.

Exact-head CI, applied migration, independent deployment/asset readback and live provider probe results must be recorded in the PR release comment. Server health alone is not image delivery proof. A real production seller browser/session is not manufactured for testing.

## Rollback and scope limits

Application rollback restores prior files. The additive policy can be removed by a reviewed `DROP POLICY shared_canonical_product_images ON tcg.media_assets` migration; never disable RLS or alter old ownership policies. No row rollback is needed because no live rows are changed.

Missing or incorrectly identified artwork remains a separate catalogue issue; do not substitute another language/variant or generate exact-card art. This patch does not reconcile the user's overlapping inventory, merge accounts, publish images/products, finish imports, or complete the Business Area migration.
