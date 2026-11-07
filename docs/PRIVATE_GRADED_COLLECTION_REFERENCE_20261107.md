# Private certificate images and value-first Collection — 7 November 2026

## Purpose and interfaces
Founder HQ and Seller Hub share authenticated Collection API: `/api/v1/owner/inventory` and `/api/v1/inventory/{id}/image`, with separate ownership scopes. Preserve exact inventory ID, owner, grade, certificate, language and printing.

## Private image rule
- Prefer an actual APPROVED `FIRST_PARTY_CAPTURE` `GRADED_SLAB` founder/consignor photo when present.
- For authenticated collection *display only*, an APPROVED grading-service front image may appear as a private reference if `source_type=OFFICIAL_PROVIDER`, `rights_tier=INTERNAL_REFERENCE_ONLY`, provider/grader is PSA, ACE, BGS or CGC, the exact inventory ID and owner match, the original source reference and provider asset identifier both contain that item's certificate, and the item/media statuses are approved, active and not revoked.
- UI labels certification imagery explicitly as private reference, not listing media. Never change rights tier, mark it first-party, or bypass Shopify/eBay publication gates. No provider download, scrape or automatic rights approval is added.
- Wrong, missing or incomplete certificate identity, wrong company, unmatched asset, revoked image, inaccessible CDN, unrelated catalogue or another owner's slab cannot be substituted. Images may be unavailable without hiding an owned item.

## Value-first order
Both founder and consignor Collection views now initialise with `sort=value_desc`. Existing backend sorts across all matching owned copies before pagination, with unavailable values last; user-selected sorts remain available. Legacy saved implicit `updated` sorting is migrated. This changes no price calculation: market-only evidence work in pending PR #964 remains a separate review.

## Checks and rollback
Run Python grader/rights/owner/media contract tests, UI Collection and cached preference checks, existing PostgreSQL/RLS fixtures, CI, deployment and signed-in acceptance for both account types. Verify the seven current exact-cert producer images and ensure no foreign/borrowed/raw fallback. Revert this PR to restore prior image filter and default order; no database rollback exists because there is no migration or data write.
