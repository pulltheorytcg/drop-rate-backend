# Cloudflare D1 operational shadow — verified live *schema-only* receipt

**6 November 2026, 18:30:56–18:30:57 UTC.** Evidence: [GitHub Actions run 42271327650](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42271327650), job `128076449631`, exact main merge commit `c6222b4420949196b847f2b40a75bf8b8789ae67`.

## VERIFIED (Cloudflare via protected GitHub main-only workflow)

- The targeted private D1 database **`drop-rate-d1-operational-shadow-20261106` was created** in the configured approved account.
- Source DDL: [0001_operational_shadow.sql](../database/cloudflare_d1/0001_operational_shadow.sql), SHA256 `bbae6a1b909069fd50e2f038abfa4659a1bc46ec86d557b443d75949f0cef9f9`.
- Remote Cloudflare `sqlite_master` object-name readback: **32 expected, 32 present** (tables/indexes/triggers) and correct source name/guard. Workflow published `drop-rate-d1-operational-schema-only: success`. `new_database_created=true`.
- Workflow receipt explicitly reported `customer_data_imported=false`, `market_value_writes=0`, `postgres_writes=0`, `production_finance_cutover=false`, `production_reads_switched=false`. These refer to THIS schema job; they do not imply the existing system has no data.
- The schema is isolated and has no live production active pointer, no customer/card copy data, no authenticated API route, no orders/refunds/settlements operating against it.

## VERIFIED (Supabase read-only source counters, 18:29:21 UTC)

Query type: exact aggregate `COUNT(*)` for named source relations, **not inferred `reltuples` estimates**. Source project `ozrxenrdladkooixutmm`:

| Source | Count |
|---|---:|
| `tcg.inventory_items` | 621 |
| `tcg.owners` | 6 |
| `tcg.media_assets` | 515 |
| `tcg.media_object_mirrors` | 401 |
| `tcg.reference_image_mirrors` | 66,222 |
| Reference mirrors with object key and SHA256 | 66,218 |
| Reference mirrors with `status='VERIFIED'` | 66,218 |
| `tcg.reference_market_history` rows still present | 0 |
| `tcg.reference_history_r2_archives` registry entries | 92 |
| Total `reference_history_r2_archives.row_count` | 117,148 |
| `tcg.reference_market_prices` | 59,693 |
| `tcg.reference_catalogue_prices` | 27,676 |
| `tcg.market_observations` | 6,241 |
| `tcg.financial_ledger_entries` | 13 |
| `tcg.orders` | 3 |
| `tcg.order_items` | 3 |

**Interpretation:** The archive and mirror counts are **registry assertions**, not proof that every source R2 object was freshly downloaded and verified in this session. Price table counts include guides and historical sources; they are not sold-grade market-value coverage. There are six owner records; do NOT infer that six founders exist. Historical archived rows and per-table observation rows are distinct concepts and must not be summed into one value-coverage metric.

## Still not done — next gated release

1. Private, lossless exact-source snapshots of all 148 registered Supabase relations to the correct encrypted/restricted destinations, with PK/FK and row-hash parity. Preserve credentials/auth secrets in replacement identity/secret handling, **not** indiscriminate R2 exports.
2. Import actual operational owner/621 physical-item/3 order/13 ledger source data into the isolated D1 shadow **only after** a consistent source snapshot, exact owner isolation, zero-duplicate webhook and financial penny checks. Do not let synthetic unit tests stand in for real source migration.
3. Copy/reverify uploaded inventory media, external artwork rights, and current price/observation evidence into R2/D1, then reimplement deterministic valuation and API reads; no asking/guide/RRP in Market Value.
4. Complete catalogue D1 quota-safe scheduled import: Yu-Gi-Oh 8,000/45,418 on 6 Nov, then 155,488 other R2-first rows, then 79,186 typed legacy source rows. These are not all physical items or unique cards.
5. Replacement authentication and row-level authorisation in FastAPI, single-D1 transactional owner/order/refund/settlement behaviour, signed-in desktop/mobile and Shopify purchase verification, full rollback before any production switch or Supabase retirement.

**State:** operational D1 private empty schema **Live verified**. Full customer/business migration and Supabase retirement **NOT completed**. No source deletion or spend approved by this receipt.
