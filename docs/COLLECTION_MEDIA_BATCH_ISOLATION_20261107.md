# Collection media batch isolation

## Confirmed defect and repair

`add_shared_inventory_media` calculated `certificate` while traversing SQL-selected media, then reused that final boolean while rendering every item. A valid private grader reference followed by an unrelated first-party slab photo lost its image; reversing the same two rows restored it. The opposite stale-true value could also defeat the Python raw-photo rejection if an ineligible raw first-party asset reached that layer (SQL already excludes that case).

Reuse one item-and-asset-specific predicate in both selection and rendering. The existing SQL/RLS remains responsible for exact inventory, owner, certificate, approval, active rights, revocation, language and variant eligibility. This patch does not broaden it. Actual first-party slab photographs retain priority. Explicitly permitted private raw references retain their existing reference-only status and labels; they are never labelled actual slab photos or granted marketplace rights. No new resolver, schema, service, frontend code or styling.

## Evidence

Before the repair, the mixed-page regression failed for PSA, ACE, BGS and CGC when the unrelated physical photo was last; the reverse ordering passed. After the repair all eight cases pass. Four negative cases show that another item's valid reference cannot approve a raw first-party photo, wrong grader, pending approval or marketplace-only reference.

126 targeted tests passed across graded Collection mapping, shared media policies, remote-image security and R2 image delivery. These are simulated records/network/storage; not authenticated physical-device or production image acceptance. Existing CI runs real disposable PostgreSQL/RLS and browser parity for this resolver path, plus backend/dashboard checks. CI is pending at authoring.

## Live scope and coverage

No production records, publication pointers, rights approvals or image bytes changed. Fresh Market Values restored: zero. Aggregate artwork coverage before/after is not established by this regression; do not count this fix as new licensed artwork or claim that all missing images were repaired. The exact regression changes one approved private image from null to its own recorded URL; the actual slab remains unchanged.

Existing PRs #991, #992, #994 and #996 remain independent. #992's Shopify graded-photo guard is not duplicated. New-game publisher rights, source-missing artwork, actual front/back slab capture and fresh permitted sold evidence remain independent requirements.

## Release and rollback

Review and green CI precede any merge/deployment. After approved release, verify the same authorised mixed Collection page on desktop and a physical iPhone, with first-party slab priority, reference labels and unchanged marketplace readiness. Live access/device acceptance is still required. Revert this isolated resolver change via the reviewed release process if needed; no data rollback or deletion is involved.

## Next implementation actions

1. Reconcile Collection response and authenticated image-route eligibility/precedence; prove exact same asset bytes with wrong-owner, revoked-rights and broken-R2 tests, retaining explicit private-reference scope.
2. Repair physical-photo upload/association and readiness where a verified defect is reproduced, preserving #992 and owner-specific slab front/back requirements.
3. Close remaining Market Value read-contract gaps across inventory, catalogue and D1: exact profile, approved evidence/generation and read-time expiry, with guides/asks remaining null.
4. Complete current immutable pricing export reconciliation and permitted sold-adapter recovery, respecting 429 backoff, entitlement and the 400 MB guard; prioritise exact owned-stock demand.
5. Complete bounded artwork/valuation R2-to-D1 generation publication and existing exception/retry orchestration, only for rights-cleared images and eligible evidence; require byte/hash readback, rollback and physical-device acceptance before cutover.
