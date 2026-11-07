# R2 physical offload — Stage 2A: reference-library count cutover

This stage is **an opt-in read-path reduction, not PostgreSQL reclamation**.
It builds on the separately merged, lossless reference-source backup command.
No reference-card row, index, foreign key, price, image-rights receipt, owner
record, finance record or audit record is deleted or moved out of SQL.

## Exact scope

- `GET /api/v1/reference-library/sets` still reads the bounded matching
  `tcg.reference_sets` page, release state and current refresh timestamps from
  authenticated PostgreSQL. Its correlated `count(*)` over
  `tcg.reference_cards` is replaced by the already verified, immutable R2
  catalogue's exact provider/system/language/set index.
- `GET /api/v1/reference-library/coverage` uses the R2 catalogue to count
  sets, card printings and future-release printings. It still reads the
  authenticated `reference_sets` groups and current `max(refreshed_at)` from
  PostgreSQL, plus the live `reference_sync_runs` receipts. An R2/SQL group
  mismatch falls back to the original full-source query.
- `GET /api/v1/reference-library/cards`, exact recognition candidates,
  importers, materialization, evidence, market prices and all writes stay
  PostgreSQL-backed. The 31-module reference-card SQL dependency is **not**
  retired by this stage.

Both new paths require `TCG_R2_REFERENCE_LIBRARY_READ_ENABLED=true` **and**
the existing `TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED=true`.
The new flag is **off by default**. Cold, missing, incomplete or invalidated
R2 generations use the previous SQL query without changing the response.
After reading live metadata, a second R2 generation check rejects concurrent
reference-source changes. The underlying RLS-authenticated connection and
same source-card visibility policy remain mandatory.

## Verification and activation gates

1. Run the new unit tests, normal backend CI, and native PostgreSQL 17.6
   comparison under both test users. Exact sets pages, pagination, live
   timestamps, empty sets, future release counts and R2 generation drift must
   compare equal with the original SQL.
2. Confirm the existing live catalogue R2 publication is complete and current;
   only then enable the *separate* reference-library flag, preferably after
   request-level parity sampling. Roll back by unsetting the flag — no
   migration or data restoration is needed for this **read-only** feature.
3. Verify production backup upload and complete typed restore separately.
   The connected Railway inspection tools do not provide arbitrary container
   command execution. An authorized operator may use the Railway CLI's
   documented **SSH command** facility (not `railway run`, which runs locally)
   from their already authenticated workstation; do not copy production
   credentials into local shells or tickets.

   ```sh
   railway ssh -p 9329767b-b092-495c-bf18-75cf69c28536 \
     -e 6f00816c-b630-4d0b-bcc1-26ac71fa712d \
     -s 6aa92310-153f-4fc9-9e22-dc338282605b -- \
     env PYTHONPATH=backend python backend/scripts/backup_reference_card_source.py
   ```

   This **dry run** exports and temp-restores every row without an R2 write.
   If it reports `LOCAL_RESTORE_VERIFIED`, the same operator can explicitly
   opt in to the private R2 upload/readback/restore (still no SQL deletion):

   ```sh
   railway ssh -p 9329767b-b092-495c-bf18-75cf69c28536 \
     -e 6f00816c-b630-4d0b-bcc1-26ac71fa712d \
     -s 6aa92310-153f-4fc9-9e22-dc338282605b -- \
     env PYTHONPATH=backend TCG_REFERENCE_SOURCE_R2_BACKUP_ENABLED=true \
     python backend/scripts/backup_reference_card_source.py --apply
   ```

   Success must explicitly report `R2_RESTORE_VERIFIED`,
   `restoration_verified: true`, a full source-row count and storage receipts.
   If the container's working directory is not the repository root, determine
   its real path first rather than changing the command to an unverified path.

4. **Do not retire `tcg.reference_cards`** until the remaining SQL/PLpgSQL
   readers, writers, FK relationships and invalidation triggers have been
   replaced, current full-source backup parity is re-established under lock,
   and separately reviewed rollback and precise table retirement are approved.
   The 400 MB import pause and Supabase free-tier limit are unchanged.

Official Railway CLI reference: https://docs.railway.com/cli/ssh
