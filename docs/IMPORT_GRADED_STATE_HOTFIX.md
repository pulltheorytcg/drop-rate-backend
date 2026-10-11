# Seller Hub import: graded-state and mobile hotfix

## Incident and scope

11 October 2026: the user reported that the deployed incremental import still showed zero saved copies after refreshing. Live PostgreSQL logs at 15:53–15:54 UTC report SQLSTATE 23514: `Graded card inventory cannot also use raw card condition`. The existing source preview contains three ready graded rows with both a grading pair and raw condition. Those rows abort the transaction, including otherwise valid ready copies. The earlier permission fix did not resolve this separate physical-state violation. The previous disposable importer fixture lacked the production condition-state trigger; passing that fixture did not establish production compatibility.

A second reported issue is a clipped mobile Import menu. Its right edge was anchored to a narrow, left-positioned trigger after toolbar wrapping, placing the menu's left edge outside the viewport. Native dialog sizing also needed explicit mobile limits and a scrolling body that adapts to header height.

## Narrow changes

- `import_inventory.inventory_condition_for_copy` is an insertion projection used by the existing shared writer. A CARD with a complete grading pair is stored with raw condition NULL. Its actual grader, grade, certificate and language remain unchanged. Raw-card condition remains unchanged; incomplete/non-card contradictions are not silently made valid.
- Keep original raw and normalized candidate records, source hashes, Collectr source-identity keys and replay receipts. Do not rewrite stored previews or remove their raw condition merely to make the database accept them. This avoids changing the re-export baseline. New uploads, older resumed previews and manual confirmed graded rows all use the same projection.
- The existing production database guard, RLS, grants, transaction locks and unique-copy constraints remain unchanged. No migration or permissive exception handler is added. Failed transactions still roll back safely.
- Mobile menu takes the available toolbar row and opens from its left edge within the containing width. Full-screen mobile dialog explicitly clears native margins/max-width, allows its body to scroll independently, keeps close reachable, and uses 16px form fields. Desktop menu remains right-aligned.

## Verification

`tests/owner_import_grade_regression.py` reads the guard definition from committed migrations, rather than reproducing only permissive inventory columns. It uses synthetic data with 483 rows / 534 source copies: 95 immediately eligible copies (including three graded rows carrying raw conditions) and 439 unresolved copies. It first reproduces the old failure by substituting only the old condition projection, asserts complete rollback, then exercises the fixed actual handlers as restricted tcg_api. It checks raw receipts, graded/manual saves, replay, ownership isolation and a graded quantity increase. It also confirms the original bad direct insert still fails.

`tests/ui/owner-import-mobile-layout.py` uses actual Seller Hub HTML/CSS/import JavaScript in Chromium and WebKit, with session/history mocked and all external requests blocked. It reproduces the old left-edge clipping at 393px and checks bounds, hit-testing, dialog bottom reachability and no mutation at 320–1440px. This is not physical iPhone Safari or a real seller login.

The new regression workflow runs both checks with read-only repository permissions. After merge, a separate read-only smoke verifies deployed CSS bytes, readiness and rejection of unauthenticated import reads. Exact commit, CI, deployment and source-record invariants belong in the PR release-verification comment. Do not claim those gates passed from this document alone.

## Release and recovery

Normal existing Railway main-branch deployment; no new service or paid dependency. No automatic processing of the customer's pending real collection. No Shopify, order, label, balance, ownership or seller-activation operation. The owner retries the preserved preview through the normal authenticated application; the >=95% policy and current exact-match admission scope remain unchanged. Full-reference matching and mapping reset remain separate work under #599.

No destructive rollback or migration is needed. Preserve all partially imported data; revert CSS independently if needed. After successful graded imports, avoid restoring the broken insertion projection—fix forward without removing receipts or stock.
