# Verified private operational-source R2 checkpoint — 6 November 2026

**Status: LIVE VERIFIED PARTIAL SOURCE BACKUP; NOT A FULL SUPABASE EXIT.**

## Actual production evidence

- One-shot, non-public Railway worker: `r2-quote-backup-once-20261103`.
- Verified deployment: `36a888c4-a5f5-4b23-8d1a-8a8e35317c5e`, started at **20:15 UTC**, proof emitted **20:16:26 UTC**.
- Source code pinned to reviewed commit `a1f175cd667ba458734c6e44e4a67223d97fe8e1`; launch `python -u -B backend/scripts/archive_cloudflare_exit_source.py --apply`.
- Worker reported `PRIVATE_OPERATIONAL_R2_PARTIAL_SOURCE_VERIFIED`, `r2_uploaded=true`, `verified_relations=10`, `expected_relations=11`, `complete_approved_scope=false`, `postgres_writes=0`.
- Private immutable R2 manifest: **SHA256** `419698b6856f3cdef5ca57558e44397e919878f425c8957abfe7b1898416c3d4`; **9,258 bytes**. Worker verified remote object bytes and typed reconstruction before reporting this status. These are private R2 objects, not public image URLs.
- Worker confirmed `auth_sessions_exported=false`, `customer_data_imported_to_d1=false` (this worker does not perform D1 imports), `operational_cutover_authorized=false`.

## Ten full tables copied and read back

| PostgreSQL `tcg` relation | Source-exact rows |
|---|---:|
| `owners` | 6 |
| `inventory_items` | 621 |
| `orders` | 3 |
| `order_items` | 3 |
| `financial_ledger_entries` | 13 |
| `refund_events` | 3 |
| `shopify_webhook_events` | 14 |
| `media_assets` | 515 |
| `media_object_mirrors` | 401 |
| `reference_image_mirrors` | 66,222 |
| **Total source-exact backed-up records** | **67,801** |

The reference-image mirror table is metadata and **does not** verify that 66,222 underlying media image bytes are present, correctly licensed or suitable for grade/slab display.

## One table explicitly blocked

The existing Railway `tcg_api` maintenance account sees only **1/6** `tcg.owner_memberships` due to an existing founder-scoped RLS policy. The worker **excluded the entire table**, recorded `blocked_relations=[{"table":"owner_memberships","visible_rows":1,"minimum_source_rows":6,"reason":"RLS_FULL_TABLE_VISIBILITY_NOT_PROVEN"}]`, and marked the R2 manifest *partial*.

Separately, the protected PostgreSQL `postgres` read-only repeatable-read snapshot successfully staged **all six** membership records and the other **1,178** reviewed business records into isolated operational D1, with exact ID/hash and owner/currency ledger parity (GitHub [run 42283108326](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42283108326)); see [D1 source receipt](CLOUDFLARE_OPERATIONAL_D1_REAL_SOURCE_RECEIPT_20261106.md). That D1 success does **not** make this R2 checkpoint 11/11. The two verified snapshots were taken at separate times, so they do not certify a single cutover-consistent joint checkpoint.

## What this does NOT authorise

- **No live API/Shopify read/write cutover**, no settlement execution, no Supabase deletion/retirement, no owner permission relaxation or RLS bypass in the live app.
- No claim that the rest of 148 Supabase relations, sensitive audit/market-observation JSON, `auth` credentials, media binary objects or full catalogue/pricing history have been migrated.
- No conversion of asking, retail/guide estimates or unverified evidence into the public **Market Value**.
- No authorisation to publish this private manifest, source rows, customer PII, R2 object keys or credentials.

**Next acceptance gates:** fully restricted membership archive under independently reviewed authorised access; completeness and byte rights/readback of private media; immutable, sensitive-data-reviewed price and audit archives; remaining source relations; replacement identity/access-control tests; delta replay; Shopify idempotency; all-owner penny reconciliation; and rehearsed rollback before live cutover.
