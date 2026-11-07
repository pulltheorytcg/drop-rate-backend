# Existing journey QA — 12 October 2026

Baseline: `b93a9d700b9b6ba20dbb29be8006ef2b16e89dce` (#611).
This is an independently initiated bug-fix pass, not a new marketplace feature or a launch approval.

## Reproduced and corrected

1. **In-flight account context.** Both hubs could accept an old account's late JSON/user response after a new login. A delayed 401 could refresh the replacement session and replay the old request with its token. Bind request, retry, response-body decoding and profile hydration to the originating login. Logout invalidates it even if the same user signs back in. Valid same-owner token refresh is retained; an old refresh cannot clear a newer in-flight refresh. A synthetic reproduction is not evidence of a production data incident.
2. **Import recovery.** Closing during upload left busy=true and a reopened form disabled. Old commit/resume/search responses could overwrite a newer dialog or release its busy state. Reset local controls on close/reopen, invalidate stale context, retain source/batch version and server idempotency, serialize mutations within the dialog, and close it on session invalidation. A server request already accepted may still finish; resume authoritative history rather than declaring it rolled back or re-uploading as Other.
3. **Channels data consistency.** Channels still selected private cached market/recommendation values and a separate image subquery. Reuse the existing authorized shared reference/media lookups. Keep actual remote listing prices separate. Latest filter response wins. No new pricing algorithm, provider or blanket artwork approval.
4. **Unsupported publishing controls.** Channels could offer eBay sync although its existing execution route rejected consignors or non-card products. Share the existing scope check between execution and display. Do not enable these unsupported journeys. An eBay connection marked READY is not a completed listing/order test.
5. **Recommendation round trip.** Selecting a different raw condition correctly cleared the suggestion, but returning to the original condition left the price empty and warning stale. Restore only untouched automatic suggestions; retain saved/manual prices and require an explicit selling action.

## Tests and evidence boundaries

The original 21-case offline Chromium reproduction produced 16 failures across the account, import-reopen and condition-round-trip cases. These are controlled asynchronous responses using actual hub JavaScript, not real account traffic. The completed suite adds refresh concurrency, channel-filter and import-commit/resume/search races. Final `tests/ui/journey-regressions.py` has no baseline/failure-bypass mode.

Run locally: `BROWSER_ENGINES=chromium CHROMIUM_EXECUTABLE=/usr/bin/chromium python tests/ui/journey-regressions.py`. The per-page Storage adapter and HTTP responses are synthetic because local browser networking is restricted. CI also runs WebKit. No real credentials, orders, labels or collection exports are used.

Extend the existing real-PostgreSQL recommendation suite to compare overview, details, market response and Channels for independent ordinary owners, including shared artwork, exact raw/slab/sealed/guide values, different private asking prices, revoked/foreign/anonymous denial and unchanged stored data after reads. Existing production snapshot/media migrations are applied in that suite; channel-table projections are fixture schema, not a full production database restore. Retain existing full backend/DOM tests, import/collection persistence, shared-media, founder Business roster and shipping-finance/pooled-order database tests.

Production verification is read-only: exact served bundles/entry versions, database readiness, anonymous denial, log slice and bounded stock integrity checks. A small live Shopify variant sample does not prove complete stock reconciliation or cross-channel overselling safety. No normal signed-in production session or real physical phone is available in this session. Test purchase, actual scanner accuracy and real label/dispatch require their separate evidence; passing mocks or database fixtures is not that evidence.

## Preserved and still incomplete

No production migration, owner/account merge, inventory import/backfill, balances, acquisition costs, asking prices, catalogue identities, source mappings, media approvals, Shopify products/theme publication, channel activation, provider limit bypass, new service or n8n workflow. Keep collection-first DRAFT / PERSONAL_COLLECTION. Existing overlapping stock reconciliation and permanent non-selling hold remain separate; unique IDs alone do not prove distinct physical cards. Missing exact artwork/market evidence is not filled by this release. Real Shopify label purchase/print/dispatch and Whatnot/consignor eBay publishing remain unavailable. Do not manufacture these workflows in QA.

Rollback: reviewed application-code revert; no data/history reversal. Release verification belongs on the PR: final checked head, actual CI results, deployment SHA and independent GET-only readback, including any blockers. Temporary source-snapshot/preparation workflow must not survive the final diff.
