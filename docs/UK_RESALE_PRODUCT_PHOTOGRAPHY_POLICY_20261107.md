# UK resale product photography — current Drop Rate policy

This policy supersedes statements that require separate publisher approval for every photograph of genuine physical inventory. It does not grant a blanket licence to copy third-party images or repurpose listing photos as general catalogue or promotional material.

## Distinguish purpose and source

[CDPA 1988 section 63](https://www.legislation.gov.uk/ukpga/1988/48/section/63) provides a specific exception for copying artistic works to advertise their sale. Assess its applicability to the actual work, photograph and use; do not reject a genuine-item sale photo merely because the depicted artwork, characters or branding are copyrighted. This is not a universal rights clearance for every collectible or use. In particular, copying another photographer's image involves a separate copyright interest; advertising the depicted product does not automatically advertise the sale of that photograph.

| Source and intended use | Existing approval path |
|---|---|
| Drop Rate/founder/consignor photograph advertising the exact genuine physical item | Record photographer/source authority and inventory association, then existing authorised internal media approval. No mandatory separate publisher licence where the use is otherwise lawful. |
| Supplier, official catalogue or marketplace image | Record actual permitted use/terms and exact identity. Use only within those terms and the destination's policy. Availability of a URL or permission to resell does not establish permission to copy it. |
| Grader/certificate image marked INTERNAL_REFERENCE_ONLY | Retain permitted private reference display; never substitute it for first-party sale photos. |
| General catalogue browsing or broader promotion | Assess separately. Inventory-specific sale-photo approval and section 63 are not automatic permission for these uses. |

## Existing evidence and approval controls

The existing media registry stores `inventory_id`, `owner_id`, `source_type`, `source_reference`, `source_provider`, `created_by_user_id`, `rights_basis`, optional `permission_evidence_url`, `approved_by_user_id`, `approved_at`, rights timestamps and revocation state. Use source_reference/rights_basis to record the photographer or authorised contributor and permission to advertise the specified item. Do not invent these facts or backfill consent automatically.

The existing founder-authorised approval endpoint already accepts an Inventory ID-bound FIRST_PARTY_CAPTURE with a recorded rights basis without requiring a separate publisher permission URL. Preserve that path; no new legal-review queue or per-photo publisher approval step is introduced. Existing owner authorisation, internal identity/quality approval and optimistic-version audit checks remain. Internal approval is not itself a legal opinion or permission to ignore platform rules.

## Implementation in this PR

The shared listing resolver previously preferred canonical artwork over an approved physical photograph for ordinary raw cards. It now selects an eligible first-party physical photo first, retaining mandatory sides/contexts for high-risk, graded and sealed products. Exact, authorised catalogue artwork remains a fallback where existing item policy permits. No physical-photo requirement is relaxed, and no approval/source status is automatically changed.

When supplied physical media is blocked, existing blocker output now distinguishes unverified photographer/source permission, reference-only media, internal approval, revoked/inactive sources, non-image media, Shopify processing and sealed capture context. Catalogue identity/language/variant diagnostics remain. No generic copyright veto or new frontend layout is added.

An inventory-specific photo remains inventory-specific. This change does not populate general catalogue thumbnails, broaden social/marketing reuse, modify marketplace integrations or bypass PR #992's separate graded capture guard. Cloudflare R2 infrastructure and the Supabase 400 MB safeguard are unchanged.

## Verification and release

76 targeted tests passed: shared resolver, universal channel policy, sealed media, Shopify readiness and graded Collection mapping. Coverage includes first-party photos without publisher URLs across cards/comics/books/figures/LEGO/sealed products, exact catalogue fallback, internal-reference exclusion, specific blocked reasons and inability to promote a physical photo into reusable catalogue media.

Full suite/CI and review remain release gates. No production asset approval, image upload, listing update, deployment or deletion was performed. No live coverage increase is claimed. Rollback is reverting the isolated resolver priority/diagnostics change through the normal reviewed release process.

Full local suite exposed the old API priority expectation, now updated and passing. Two unrelated n8n temporary-directory cleanup test modules fail on this Mac and also reproduce on the unchanged baseline worktree; 32 optional PGlite tests were skipped because that runtime is absent. These failures are not waived: Linux CI must pass before release.
