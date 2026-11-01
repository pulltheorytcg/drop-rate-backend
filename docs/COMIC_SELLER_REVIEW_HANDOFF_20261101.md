# 1 November 2026 — "Resume Fixes Scanning Last" handoff

## Context recovered

- PRs #865–#867 were merged and deployed before this handoff. Scanner recognition, comics routing/artwork and R2 startup/listing blocker improvements landed; phone testing still found incomplete seller preparation, and scanner speed/identification need another separate pass.
- The real physical Deadpool/Batman #1 consignment comic can be added to the collection and marked for sale, but the Seller Portal lacked holding/dispatch, paid-cost, measured-parcel and exact-copy photo controls. The last 1 November review was implementing these and a rejection/resubmission loop.
- Read-only live check: target copy was `INSPECTION`, `FOR_SALE`, with no staff-confirmed identity, cost, verified storage location, active `COMIC_BOOK` shipping profile or physical media. Another copy was a personal-collection draft. No real item was altered or Shopify product published during diagnosis.

## This change

- Owner-scoped comic form records holding/dispatch instructions, real purchase cost and measured parcel sizes as **unverified** preparation evidence.
- Front/back photograph upload uses a signed, short-lived, owner/item/side-bound Shopify staged target. Its physical media record stays rights/approval `PENDING`, never a product publication.
- Founder HQ has a platform-admin-only queue for consignment comic photos. Reviewers can approve a visible, ready exact-copy image or give a written retake reason; sellers can then resubmit.
- Media RLS migration scopes the staff cross-owner review to consignment comics and makes media ownership/identity immutable on update. A failed comic-only queue does not block other media tools.
- Python/API and seller/staff UI regressions cover ownership, ticket tampering, duplicate submissions, review gating, retakes, and no publication. Existing Shopify/comic focused suites also pass locally.

## Remaining release gates

1. Complete GitHub CI. An unrelated existing `tests/test_business_access.py::test_unregistered_admin_is_rejected_before_business_data` hangs in this scratch environment; an isolated run timed out at 30 seconds, whereas focused suites passed.
2. Apply `database/migrations/20261101194856_platform_comic_photo_review.sql` through the approved Supabase migration workflow **after production DB authorization**, and verify founder versus consignor RLS.
3. Merge and confirm exact-commit Railway deployment `SUCCESS`; inspect authenticated phone upload/review and Shopify Files readback. Keep Shopify storefront password-locked.
4. Confirm real seller storage/dispatch, exact printing/condition, actual cost and a measured active `COMIC_BOOK`/`MANGA_BOOK` shipping profile with staff. Only then consider manual Shopify publishing through existing gates.

No migration, production inventory mutation, catalogue price invention, media approval or Shopify publication is implied by this code change.
