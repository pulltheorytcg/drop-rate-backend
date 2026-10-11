# Immediate Seller Hub collection intake

## Current decision

11 October 2026: the founder explicitly replaced the all-rows-reviewed / final-whole-batch confirmation requirement for Seller Hub. One intentional **Import collection** action adds eligible high-confidence (threshold inclusive at 0.95) matches to individually owned **Draft inventory** immediately. Uncertain rows remain separate and enter inventory when manually confirmed. Unrelated uncertain rows do not block the confident copies.

This is inventory intake, not listing approval. No automatic Shopify publication, fabricated market/acquisition values, owner reassignment, customer activation, carrier purchase or financial posting. `identity_confirmed` remains false; high-value, authenticity, condition, grade and publication gates remain separate.

## Confidence means evidence

The current importer has no calibrated probabilistic model. The first supported automatic admission method is a unique, complete, exact catalogue identity across game/name/set/card number/variant/language (and matching rarity when supplied). It records a deterministic rule confidence of 1.0 and **no calibrated probability**. The interface treats this as an exact match, not a claim that an AI is statistically 100% correct. Partial/fuzzy similarities, a CSV confidence field, or an LLM self-rating are not accepted. Anything without sufficient supported evidence stays for review; adding cosmetic 95/99 scores is forbidden.

An explicit manual choice records the selected catalogue ID, current identity fingerprint and actor. It can supply a missing language from the selected printing or an explicit supported-language choice; it cannot silently turn a card into a sealed product, ignore malformed quantities/costs, publish a listing or write a canonical product. Catalogue changes invalidate a saved identity decision. A previously confirmed mapping can be reused for the same source identity only while the selected catalogue identity remains unchanged. A newly conflicting source language is never silently cleared by that old decision.

## Existing engine and data

`import_inventory.create_draft_copies` is shared by legacy and incremental routes, so physical IDs, ownership, Draft status, source-copy uniqueness and cost handling are not duplicated between engines. The legacy founder import remains preview/review/full commit. Only the owner allowlist exposes `/upload` and incremental confirmation.

The existing batch/candidate tables are retained. A partially processed batch stays internally PREVIEW, with completed physical rows marked COMMITTED and exceptions REVIEW. `automatic_intake` distinguishes it from a legacy preview. `last_auto_apply_version`, row locks, transaction-scoped per-owner advisory locks and existing unique source-copy constraints make repeated submissions safe. RLS stays enabled; only five processing metadata columns become writable. Ownership/fingerprints remain non-writable, and there are no new public grants.

The interface distinguishes **copies in the file**, **copies already added**, and **review rows plus their copy count**. A source count is not a match count, and a copy count is not a percentage. It refreshes inventory after successful upload/confirmation and does not claim an interrupted request made no changes.

## Collectr and other files

Collectr quantities reconcile against the previous completed snapshot. The original source identity is retained separately when a human fills missing facts so a subsequent export does not create a second collection. `collectr_snapshot_key` still distinguishes physical identity, including grade, finish, condition and language. The separate `collectr_source_snapshot_key` is used only for source reconciliation. Unchanged files resume the existing result; +1 adds only one copy; decreases/disappearances require review and do not remove sold/reserved/other stock.

For this bounded implementation, there is **one open incremental import per owner**. A newer file waits until the current exceptions are confirmed or deliberately skipped. This avoids using pending rows as a completed quantity baseline. The same file remains resumable. Ordinary blocked uploads are rejected before creating a stale preview; the locked apply stage also rechecks simultaneous requests. This is a deliberate first-version limitation, not remote account sync. Generic/Holodex CSV/TSV still have exact-file deduplication, not Collectr-style snapshot semantics.

Deployment itself does not apply any pending real preview. Existing users must explicitly choose **Add recognised cards; review the rest** or submit an import. Mapping correction/reset of an existing file remains separate from this change. No automatic transfer between similarly named founder/consignor accounts occurs.

## Verification and release

- Unit policy tests cover the inclusive 0.95 boundary, missing/contradictory fields, no trusted CSV score, unpaired grades, explicit language, bound manual evidence, non-finite costs and physical/source key separation.
- Dedicated disposable PostgreSQL 17 checks call the actual handlers under restricted `tcg_api`: reproduce the original batch and owner-lock failures; apply the migration twice; add recognised rows while another row remains; confirm a missing-language row; re-export, +1, decrease, same-file retry, owner isolation/revocation/ambiguity, concurrent applies, a newly contradictory language and injected late-failure rollback.
- `owner_import_http_acceptance.py` uses actual JWT signatures and JWKS validation, actual FastAPI owner/admin gates and the same disposable PostgreSQL database. It checks missing/invalid/expired/anonymous tokens, forged user metadata, cross-owner access, revoked membership, immediate intake, confirmation and replay. The ephemeral local test issuer is **not a production Supabase sign-in**; no production JWT is fabricated.
- The SQL fixture mirrors relevant live RLS/grants/constraints, not the entire production migration chain. Its event fixture checks completion timing, not actual n8n delivery.
- Ten actual-DOM/JS scenarios use mocked API responses: partial additions, confirmation, skip, existing preview adoption, repeated upload, lost-response recovery, safe text rendering, format rejection and stale completion. They are **not a live browser/production seller session**.
- Exact-head PR CI, production migration/deployment readback and real seller browser acceptance are distinct gates. Record the release results on PR #603. A healthy server or large test count alone does not establish a production end-to-end pass.
- Migration first, then a fresh application deployment, then read back restricted grants and deployed commit. Never run the synthetic fixture against production or auto-commit a real collection to make a test pass.

Before any incremental import has been used, rollback can restore the preceding code and revoke the five newly granted processing permissions. After real partial intake exists, do not blindly revert source-key/partial semantics: preserve the rows, stop affected import writes if needed, and fix forward. No migration or rollback may delete imported holdings or rewrite financial history.
