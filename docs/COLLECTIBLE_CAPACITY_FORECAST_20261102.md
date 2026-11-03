# Expanded catalogue — read-only PostgreSQL capacity forecast

**Checkpoint: 2 November 2026. This is planning, not import approval.**

The expanded collectible schema and historical-migration reconciliation have
already been applied. New reference imports remain off, the draft branch is
not deployed to Railway, and the public R2/Shopify gates stay off. No data was
pruned, migrated out of the authoritative PostgreSQL database, or altered to
prepare this forecast.

## Live database reference-card baseline

Read-only Supabase queries on project `ozrxenrdladkooixutmm` returned:

| Metric | Observed value |
| --- | ---: |
| Database size (`pg_database_size`) | 419,220,627 bytes |
| `tcg.reference_cards` actual rows | 69,697 |
| `tcg.reference_cards` total heap, TOAST and indexes | 77,152,256 bytes |
| Observed aggregate footprint per reference card, rounded up | 1,107 bytes |
| Existing automated bulk-import stop | 400,000,000 bytes |
| Free database quota for this project | 500,000,000 bytes |

The current database already exceeds the 400 MB import stop by **19,220,627
bytes**. The nominal Free-plan headroom is **80,779,373 bytes** before
additional tables, indexes, audit history, maintenance overhead or WAL. A
database size reading is different from Cloudflare R2 object storage usage.

The newly created `reference_figure_products` and
`reference_card_product_details` tables have zero imported records. There is
**no empirical per-row footprint** for figures or sports-specific attributes;
do not extrapolate card-only bytes to those families.

## Advisory estimator

`backend/scripts/forecast_collectible_capacity.py` reads live metrics in a
read-only transaction using an already configured `TCG_DATABASE_URL`, or
accepts three operator-supplied snapshot values for offline review. It never
inserts records, archives anything, publishes objects or alters any runtime
flag. No secrets are printed.

The estimate uses the observed complete `reference_cards` relation size
(including that table's existing indexes and TOAST), rounds up the historical
bytes per card and adds a **50% planning cushion** for proposed canonical card
references. This is an informed projection, not a guaranteed bound or a
generic cost per physical inventory item.

Example with the 2 November snapshot and 1,179 Foundations printings:

```sh
PYTHONPATH=backend python backend/scripts/forecast_collectible_capacity.py \
  --cards 1179 \
  --database-bytes 419220627 \
  --reference-rows 69697 \
  --reference-table-bytes 77152256
```

This returns **1,305,153 bytes** as a historical-card-only baseline,
**1,957,730 bytes** with the cushion, and
`BLOCKED_BY_CURRENT_IMPORT_GUARD`. The result is deliberately
`authorizes_import: false` even if the projected size would be below the
guard. The offline input is explicitly labelled stale until rechecked.

For a controlled backend runtime, omit the three snapshot flags to take a
fresh live read-only reading. Because this estimator does not count new set
rows, pricing evidence, source-specific attributes, ledger/audit growth or
different payload distributions, it can only inform a more complete capacity
decision. Actual imports must independently pass the existing 400 MB live
guard, licensing, source identity, RLS and owner/Shopify separation checks.

## Release decision at this checkpoint

1. **Keep new SQL imports paused.** Do not bypass the 400 MB guard to fill
   missing categories on the Free project. Keep preview-only source windows
   and quarantine/replay evidence in CI.
2. **R2 for permissioned immutable bulk source metadata and imagery only.**
   The verified private Magic Foundations bundle is 771 source cards / 1,179
   distinct print-and-finish references over eight signed-hash parts. Its
   local archive dry-run returned `DRY_RUN_VERIFIED`; this is **not** an R2
   upload and provides no indexed live API search by itself.
3. **PostgreSQL stays authoritative** for indexed canonical identities,
   physical inventory, ownership, pricing, settlement and audit data. R2
   cannot replace relational constraints or deterministic settlement logic.
4. **Review actual rights, anticipated source-row counts and business value**
   before any SQL expansion. A Pro **database** disk upgrade could support
   indexed growth, but is a separate commercial decision and was not made.
5. **Do not deploy this draft branch or enable public feeds** simply because
   the additive schema and read-only capacity report pass tests.

## Tests and failure behaviour

`tests/test_collectible_capacity_forecast.py` covers the live over-guard
snapshot, projections with a 50% cushion, negative/boolean/incomplete inputs,
insufficient observed row counts, impossible table-vs-database sizes, partial
offline snapshots, and the fact that the planner **never authorizes** import.
The CI expanded-collectibles staging workflow runs these alongside the
existing database-capacity guard tests. If reference metrics are unavailable
or inconsistent, the forecast fails closed; no writes are attempted.
