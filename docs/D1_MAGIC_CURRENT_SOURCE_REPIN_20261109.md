# Magic: The Gathering — repin the isolated D1 reference importer to current MTGJSON R2

9 November 2026 · Migration release-control issue #1010

## What / why
The protected **read-only** Magic source preflight (merged #1040 and checked on main) has already verified current immutable source generation 2, **153,679** MTGJSON printing references, 151,609 released, 98,902,731 bytes and canonical SHA256 `e3bda5f54affe0055ec64d7ffb943cb5cae23df8108e74f29e250f7ec63e662a`. Its follow-on D1 writer was pinned to **153,662** and outdated R2 SHA, so it would fail closed even if the earlier Yu-Gi-Oh queue became complete.

This change repins only the **private, reference-only D1 candidate importer** and exact full source count status to 153,679 Magic cards. Combined fully verified R2-first follow-on totals are now **155,505** records (Magic 153,679 + sports 1,722 + heritage sports 100 + approved figures 4). These counts do not mean D1 data is imported, nor are they inventory copies or market valuations.

## Connections
Signed protected GitHub OIDC → existing exact source-scoped Railway private R2 export → independently bound MTGJSON manifest and all part hashes → isolated `drop-rate-d1-all-followon-catalogue-shadow` with guarded daily resume → full D1 card-key/SHA256 readback and active pointer. Existing `SOURCES` closed registry, no arbitrary providers, and source approvals remain.

## Failure points
The new source SHA/count mismatch, corrupt R2 parts, unapproved language/printing, original source changed after proof, incomplete Yu-Gi-Oh active D1 generation, same UTC day as YGO, D1 disk/account budget, duplicate/card-key drift, or staged row SHA mismatch fails closed. D1 currently requires the YGO source to be complete first and has an 8,000 new-row/day quota; that remains deliberately unchanged in this small reviewed repin.

## Testing and permission gates
The full preflight/isolated SQLite simulation and backend/n8n/dashboard CI must pass. The D1 write-capable GitHub job has separate **exact commit SHA + exact run ID** manual approval variables `DR_D1_FOLLOWON_IMPORT_APPROVED_SHA`/`DR_D1_FOLLOWON_IMPORT_APPROVED_RUN_ID`, which this PR does not configure. Merge alone cannot initiate D1 writes. Tests pin current manifest/count and ensure 155,505 final verified total. Real D1 stage, byte parity and dashboard publication require distinct reviewed receipts.

## Rollback / security
No production API/Shopify or Supabase changes. No ownership, card costs, settlements, market observations/prices, authentication, payouts or non-owner-safe data touches. Revert the D1 source pin if the current source proof is invalidated. Supabase remains live system authority until operational 150-relation parity, finance/identity/consumer switch and verified encrypted cloud restoration complete.
