# Exact physical-item image repair — 12 November 2026

Founder architecture: Supabase Pro is authoritative; Railway/FastAPI runs business logic and jobs, GitHub releases, Shopify storefront/listings. Cloudflare migration is cancelled. Existing R2 assets/read paths/backups are preserved until any required verified Supabase copies exist.

## Correct slab and sealed images

Collection list/detail responses previously allowed a staff-reviewed graded copy to show raw canonical artwork or a certificate provider's raw-card photograph, while the authenticated image proxy already required a slab. This produced inconsistent pictures between direct URLs and proxy/reload paths.

Use the existing owner/certificate-bound selector with **GRADED_SLAB** capture context for every graded copy, including incomplete grading fields. Select eligible candidates before ranking so a newer raw upload cannot hide a valid slab. Retain approved owner-uploaded slab photos and exact certificate-bound private slab references, their existing rights tiers and publisher/source restrictions. No approval or listing permission is manufactured. A missing slab remains **Slab photo required**, with no raw substitute. Private grader photos remain excluded from first-party marketplace publication.

For sealed physical photos require SEALED_PRODUCT capture context; canonical sealed images remain exact CANONICAL_PRODUCT records. Existing owner IDs, certificate binding, approvals, language/variant checks, revocation, RLS and first-party approval workflows stay in force. No asset deletion, Store Price, ownership or settlement changes.

## Actual source checks

- English Normal Trunks, Thwarting the Dark Empire BT13-131: original recorded Bandai PNG returned 200, **260×363**, SHA256 `b03fe4954057923fcdfb16e79e23d017eb4f8743c4f7c17d44bbb1ff6676fc64`. Visual review of those bytes confirms the name and BT13-131. It is below the 350px-per-side audit threshold; upscaling is not a resolution repair. An exact authorised higher-resolution image or first-party photograph remains needed. The recorded Shopify file probe returned 404; do not claim higher-resolution recovery.
- Japanese Holofoil Latias ex (Mirror Holo) 312/742: recorded image URL returns 404. Exact TCGdex MC-312 metadata returns 200 and confirms Japanese name/collector number and MC set (742 official/774 total), but **image is null**. No substitute URL or similar Latias art is inferred.
- Swinub 106/100 PSA 10: fresh metadata now includes approved private PSA slab references and Shopify URLs for the approved copy, alongside the old raw canonical asset. Those records are not proof of successful rendering, image identity or first-party sale-photo rights. Verify the exact slab visually; do not promote or copy private grader photography to public Supabase/Shopify assets without permission. Another unapproved physical copy has only raw canonical metadata and cannot borrow the first copy's slab.

The original ten owner-scoped Action Required items are retained for exact review; the earlier 90/100 byte successes remain visually unverified. This code repair does not mark the ten resolved or claim a new photo exists.

## Tests, release and rollback

Python selector regressions cover first-party precedence, wrong grader/owner/copy flags, revoked/pending media, raw-vs-slab, incomplete grading, raw masking a slab, sealed context and no raw fallback. Browser/jsdom tests reject stale raw/canonical API flags, preserve slab sizing and explicit missing-photo state. Existing PostgreSQL media/RLS and full CI remain release gates. UI components, styling and navigation unchanged; cache versions refreshed for the changed image logic.

Rollback reverts selector/rendering logic and redeploys. All original assets, metadata and approval history remain intact. No R2/D1 migration, provider spend or source-policy relaxation is part of this repair.
