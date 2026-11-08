# Shopify physical photo capture-context audit

7 November 2026. Scope: deterministic media eligibility only; no UI, production
records, rights approvals, services or marketplace writes.

The existing shared storefront resolver accepts any nonempty capture context for
graded physical photos. A regression test reproduces acceptance of raw front/back
captures for a PSA-graded item. eBay already rejects these through its independent
GRADED_SLAB requirement. This is a selector defect, not proof of an affected live listing.

Correction: filter graded card/comic physical candidates to GRADED_SLAB before
choosing latest front/back. Preserve all existing rights/approval/readiness gates,
canonical-art rules for ordinary raw cards and sealed capture handling. Filtering
before selection ensures an ineligible newer raw photo cannot hide a valid slab.

Risk: previously accepted mislabeled photos will require proper slab capture.
Tests: wrong front, wrong back, both wrong, valid pair, mixed candidates and existing
media/publication regressions. Rollback: revert code/test commit; no migration.
Production listing audit and provider readback remain outstanding. No live listing
is automatically republished or delisted by this change.

Validation: regression failed before the correction. After correction, 428 focused
Shopify/media/eBay/physical-photo tests passed, including real disposable PostgreSQL
photo eligibility checks. Fifteen media resolver tests passed with both graded
card and comic cases. A broad local run was interrupted after 809 passing tests;
it is not a full-suite pass. Full CI and human review remain required.
