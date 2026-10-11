# Import review search correction — 11 October 2026

Related #598 / #599; this fixes the reported compound-search bug, not the complete import-recovery workflow.

## Cause and fix

Find match prefills `card_number + set_name` (or name + set for unnumbered products). The old API attempted the complete phrase separately inside name, card_number, set_name or game. It therefore returned no candidates even when the correct number and set existed in separate columns.

Search now requires every literal normalized term across public canonical identity fields, retaining product-type filtering, exact-only result preference, deterministic ordering and the 16-result cap. Punctuation and separators are handled without treating user input as SQL wildcard syntax. ALL query terms remain required: a wrong explicit set is not silently discarded. Results are suggestions, not automatic canonical identity approval. Existing owner authentication, manual choice, review/commit and no-publication boundaries are unchanged.

## Counts are not equivalent

Copies in source = physical quantity represented by the CSV. New Draft copies = quantity currently READY for explicit commit after reconciliation. Rows needing review is a ROW count, not a physical-copy count. A PREVIEW contains no committed inventory; 534 source copies never meant 534 approved matches. Missing language must not silently become English.

## Verification boundaries

Unit tests cover literal tokenization and verified-user DB context. A real PostgreSQL test using a synthetic temporary table runs in the EXISTING seller-inventory CI service. It exercises the same SQL with only its table relation replaced, including compound inputs, language and product filters, wrong-set rejection, Unicode/punctuation and replay. This is real SQL but not a production seller browser/session. Live read-only regression results and exact-head CI/deployment go in the PR release comment.

Remaining: #599 preview revision/default correction and production import write-grant/locking repair; full reference-library search with controlled canonical materialisation is a separate bounded change. Selecting an existing catalogue card does not resolve a missing language field today. No live preview, ownership, stock, canonical data or financial rows are modified by this search fix. No migration, provider, app, durable service or paid dependency is added.

Rollback: revert the search helper and API change. No data rollback is required.
