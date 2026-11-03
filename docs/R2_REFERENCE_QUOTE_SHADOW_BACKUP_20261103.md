# Drop Rate — verified live-reference-price R2 shadow backup

## Why this is a shadow stage, not a deletion

The free-plan PostgreSQL database has **419,966,099 bytes allocated** against
the catalogue import guard of **400,000,000 bytes** (measured 3 November 2026).
Its two active reference price tables currently hold **59,693 market rows** and
**27,676 catalogue rows**, with approximately **59.3 MB** of in-row JSONB
source quote evidence. Values, quote sources, and active expiry checks remain
in PostgreSQL. Auditing is protected against mutation.

Directly replacing `quotes` with empty arrays is **not valid**: PostgreSQL
check constraints require quote evidence for non-null prices, and several live
read/write paths inspect it. R2 copies do not themselves reclaim PostgreSQL
pages. Clearing evidence without a migrated reader would silently damage price
provenance. Likewise, no authenticated inventory, ownership, or seller data
belongs in a public catalogue object.

This stage produces verified **private**, content-addressed full-table backups
of both `tcg.reference_market_prices` and `tcg.reference_catalogue_prices`.
It does **not** alter rows, schema, application routing, SQL guards, or access
control, and it does not claim a reduction in PostgreSQL size.

## Operation

Run in a trusted backend/Railway environment with the existing connection,
existing maintenance administrator, and private R2 credentials:

```bash
PYTHONPATH=backend python backend/scripts/backup_reference_quote_sources.py
```

This local dry run creates each full-table archive and validates every row by
typed restoration into **rolled-back PostgreSQL temporary tables**. It uploads
nothing. Only run an R2 copy after confirming that dry-run status is
`LOCAL_RESTORE_VERIFIED` for both tables.

To upload verified private copies, configure
`TCG_REFERENCE_QUOTE_R2_BACKUP_ENABLED=true` in that trusted job environment
and run:

```bash
PYTHONPATH=backend python backend/scripts/backup_reference_quote_sources.py --apply
```

With `--apply`, the job uploads content-hashed `.ndjson.gz` objects to the
private `exports` namespace, reads the actual remote bytes back, checks
compressed and uncompressed SHA-256 digests, and type-restores every record
again in PostgreSQL. Only then does it publish and re-download a SHA-256-pinned
JSON manifest for each source. Results show `R2_RESTORE_VERIFIED`, exact source
counts, and **0 reclaimed rows/bytes**. The manifests are historical consistent
snapshots: ongoing refreshes may change the live price rows afterward.

The worker refuses unexpected column drift, duplicate or out-of-order IDs,
invalid JSON, missing admin authorization, excessive line/row/byte counts,
bad R2 receipts, corrupt downloads, and typed restoration mismatches. R2
archives must remain private. Do not expose object keys to public API clients.

## Follow-up gate for actual storage reduction

1. Prove all backup checks and verify the live SQL write/read dependencies for
   `quotes`, including any JSONB predicates.
2. Introduce R2 reference pointers and safe server-side read-through/rollback
   with a bounded, authenticated cache. Keep normalized price values and latest
   provenance in PostgreSQL; verify exact query parity and writer behaviour.
3. Add a reviewed database migration for constraints and shadow dual-writes.
   Confirm each quote matches a pinned, **currently valid** R2 version before
   any SQL payload removal; a historical archive alone is insufficient.
4. Back up current source again, test restoration and rollback in disposable
   Postgres, then request explicit approval for a narrowly scoped cleanup and
   physical space reclamation. Measure `pg_database_size(current_database())`
   afterwards; a normal `DELETE`/`UPDATE` does not guarantee physical shrinkage.

Follow the existing [stage-3 tracking issue](https://github.com/pulltheorytcg/drop-rate-backend/issues/879)
for cutover, receipt, retention, and rollback approval gates.
