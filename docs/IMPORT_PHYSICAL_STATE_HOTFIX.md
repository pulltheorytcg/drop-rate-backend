# Seller import physical-state hotfix — 11 October 2026

## Confirmed production failure

The user's post-#603 requests reached the correct deployed `/api/v1/owner/imports/{batch}/commit` endpoint and returned HTTP 422. Supabase's PostgreSQL log reported SQLSTATE 23514: `Graded card inventory cannot also use raw card condition`. The pending ready group has 92 raw copies and three PSA 10 copies; all three slab source rows also contain Near Mint. The physical-state guard rejected the shared writer's combination of raw condition and slab grade, rolling back the whole addition. This is not a cache error or proof that Supabase is down.

The last release's disposable database fixture omitted the real physical-state trigger/CHECK. Passing that fixture was therefore insufficient to prove mixed raw/graded intake. No earlier handover should be read as a passed production seller import.

## Bounded fix

The existing shared `import_inventory.create_draft_copies` writer now projects a complete graded CARD's physical `condition` to NULL. Grade, grading company, certificate, language, ownership and source-copy identity are unchanged. Raw card conditions remain their imported value. Original CSV fields remain in `source_record`, and normalized source records/snapshot keys are not rewritten. This fixes both existing saved previews and future automatic/manual imports without resetting or re-uploading the source file.

This is not a generic ignore-errors path: incomplete grading and non-card conflicts are not silently repaired. The live trigger and CHECK stay intact. No grants, RLS, migrations, existing physical items, prices or finance records change. Recognised items still start Draft and are not published to Shopify.

## Mobile issue

The Import button wraps onto the left of the toolbar on narrow screens, while its wider menu was anchored to the button's right edge. That pushed the menu past the viewport's left edge. The mobile wrapper now spans the available toolbar row and the menu is left-aligned within it. Native dialog max-width/margins and inner scrolling are also made explicit, retaining a visible close control. Desktop anchoring remains unchanged.

## Verification required

- Pure projection tests: retain source identity/grade/certificate; raw, graded and sealed separation; no blanket repair of invalid incomplete states.
- Real PostgreSQL: apply the actual version-controlled physical-state guard and separation CHECK to the disposable test database, reproduce the old writer's failure and rollback, then exercise the fixed writer through authenticated owner HTTP routes with a local ephemeral JWT/JWKS issuer. Synthetic 92 raw + 3 graded copies are saved while 439 unresolved copies remain; original source evidence, replay, confirmation, +1 and owner isolation are checked.
- Chromium and WebKit: actual owner template, stylesheet assets and import script, with only local mocked import history. Check menu bounds, labels, native dialog bounds, close control and inner scrolling at 320–1440px and reduced viewport height.
- The tests remain synthetic and do not constitute a real Supabase sign-in, physical iPhone check or import of the user's collection. Exact-head CI, deployed commit and non-mutating production readback belong in the release-verification comment.

## Rollback and limits

No schema migration is required. Revert only this code/CSS patch; do not roll back #603's partial-progress schema or erase imported stock. Reverting the projection restores the known graded import failure, so prefer a reviewed fix-forward. Existing unrelated issues (full-reference matching, preview remapping and calibrated probabilistic admission) remain open in #599. Do not use this fix to auto-commit the user's pending collection during testing.
