# Drop Rate — independent legacy TCG D1 staging gate

9 November 2026 · live migration tracker [#1010](https://github.com/pulltheorytcg/drop-rate-backend/issues/1010)

## 1. What is built / why it belongs

Pokémon, One Piece, Dragon Ball and Naruto reference catalogues already occupy the immutable **five-relation original-game R2 publication**. The older private D1 legacy shadow importer blocked even starting until every separate sports, figures and Magic reference had completed D1 staging; this is not a source-integrity or transactional dependency.

This change removes that dependency **in the existing importer**. It does not repin the protected D1 writer to a different source, stage a single row or switch any application route. The independent source-pin update [#1040](https://github.com/pulltheorytcg/drop-rate-backend/pull/1040) has already shipped only the read-only original-games and Magic proof paths. The **write-capable** legacy D1 importer remains pinned to historic legacy generation 122500, total 79,186 rows, with original per-relation SHA checks; it will therefore fail closed if offered current published generation 122674, 79,357 rows. New D1 source pins can only be accepted in a subsequent reviewed, source-verified PR.

## 2. Connections

Current fixed signed R2 export → per-relation original-game immutable manifest/part SHA → independent private `drop-rate-d1-real-legacy-catalogue-shadow` → exact typed/source-JSON/hash prefix readback → isolated verified active generation pointer, never live API search by this change.

The original-games importer no longer calls `_source_active` for unrelated follow-on Magic/sports/figures sources. Its preflight still:
- verifies no same-day Yu-Gi-Oh or follow-on D1 write receipt, where those databases exist (fail closed if receipt metadata unavailable);
- sums all existing D1 database byte sizes and refuses insufficient account-wide storage headroom;
- reserves a database slot for operational ledger and applies its old per-run and per-day 5,000-row bound;
- checks old-source manifest, all R2 parts, stable IDs, typed relation SHA and staged row prefix before any active pointer;
- requires the repository workflow's separately configured exact **commit SHA and run ID** approval variables to enter the private write-capable job; no approval values are supplied here.

## 3. Failure points

Source version mismatch, altered cards, wrong scope, missing Japanese or Unknown-language source slice, corrupt manifest or R2 file, D1 quota, competing same-day D1 writes, wrong SHA/run approval, unknown D1 tables, no account storage headroom, duplicate row identity or partial readback must refuse stage or activation. Do not copy physical ownership/market price into the owner-free catalogue database. The *different* Magic follow-on D1 writer still requires a fully verified current MTGJSON generation; that path is not changed.

The old reason/status `LEGACY_WAITING_FOR_PRECEDING_CATALOGUE` is preserved for backward-compatible reporting when a same-day capacity/receipt gate fails. It no longer means all other games must finish.

## 4. Tests

Real SQLite fake-D1 integration should establish: all five owner-free source relations preserved; original-game D1 can stage and resume if Magic D1 does not exist; YGO or follow-on writes on the same UTC day block before any legacy export or D1 create; wrong SHA rejects even without other catalogue sources; corrupt D1 staged rows refuse continuation; original safe 5k/day and no public cutover remain. Full backend, n8n and dashboard CI required before merge. After merge, production API/n8n deploy readiness is a release checkpoint, **not** evidence of D1 rows imported.

## 5. Rollback and complete migration order

If any source-only audit fails or the D1 headroom check is indeterminate, leave the legacy job disabled and production Supabase/R2 unmodified. Revert this isolated importer preflight change if necessary. A future protected import must repin current manifest and **all five original per-relation SHA256s from independent full original R2 bytes**, use an exact approved GitHub run, verify indexed row SHA and leave earlier generations immutable, then stage source rows without waiting for Magic.

Independent catalogue stage completion is only one exit dependency: hosted external identity/permissions, 150 source relations, atomic D1 owner/Shopify financial write and replay, current Market Values, encrypted cloud backups and real recovery drills, and zero Supabase calls remain separate release conditions. No live financial/identity cutover or source deletion is part of this PR.
