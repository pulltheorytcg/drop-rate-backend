# Private R2 operational-source checkpoint (Stage 1 of Supabase exit)

**6 November 2026 — implementation pending CI and protected Railway run.** The founders approved full Supabase → Cloudflare R2/D1 replacement, but a source backup alone is NOT a D1 cutover.

## What and why

The live D1 operational schema is verified but **empty**. Before any owner/inventory/ledger rows can be replayed, capture a consistent immutable PostgreSQL source snapshot and verify it. `backend/app/cloudflare_exit_source_archive.py` and `backend/scripts/archive_cloudflare_exit_source.py` provide the first narrow, auditable private R2 checkpoint. The module captures **every column**, from **one read-only repeatable-read PostgreSQL transaction**, of these 11 reviewed `tcg` tables:

| Source relation | Exact row count, 6 Nov audit |
|---|---:|
| `owners` | 6 |
| `owner_memberships` | 6 |
| `inventory_items` | 621 |
| `orders` | 3 |
| `order_items` | 3 |
| `financial_ledger_entries` | 13 |
| `refund_events` | 3 |
| `shopify_webhook_events` | 14 |
| `media_assets` | 515 |
| `media_object_mirrors` | 401 |
| `reference_image_mirrors` | 66,222 |

These counts are read-only source receipts, **not** archival proof or D1 row counts. A separate read-only scan flagged **157 of 46,577 audit rows** and **13 of 6,241 market-observation rows** for credential-like text. These are pattern matches, not verified exposed secrets; both JSON-heavy tables are deliberately **excluded** from this first R2 batch pending a more restricted, reviewed export/encryption path. Run them again against the same consistent snapshot. Owners are business ownership records; this is not six founders, and `reference_image_mirrors` metadata is not image bytes.

## Connections

Railway's existing credentialed, single-use **R2 source-backup service** has private R2 configuration and the currently authorised maintenance actor. The new script only uses these existing settings and `app.db.create_pool`. It never calls Shopify, D1, an LLM or any payment provider.

Default CLI mode exports and checks the original typed PostgreSQL composite records locally without R2 writes. Passing `--apply` is accepted **only** if `TCG_FULL_EXIT_PRIVATE_R2_BACKUP_ENABLED=true` is configured in that dedicated Railway service. It uploads 11 private SHA256 content-addressed .ndjson.gz archives, downloads and checks the original bytes and checks **every** row using PostgreSQL `json_populate_recordset` as a read-only type reconstruction. Only after each **included** table passes does it upload/check a private manifest naming every completed and blocked table. If RLS hides some source rows, it excludes that entire table, marks `complete_approved_scope=false` and records `PRIVATE_OPERATIONAL_R2_PARTIAL_SOURCE_VERIFIED` rather than falsely claiming 11/11 completed. Incomplete uploads cannot be called an all-table checkpoint; archives are never deleted/overwritten to hide an error. No source table or trigger is changed.

## Security / failure points

- **No `audit_events` / `market_observations` raw JSON** until sensitive-field review; no `auth` tables, credentials, MFA, login tokens, payment-card details, `ebay_seller_connections`, `stripe_connected_accounts`, `payout_preferences` or arbitrary tables. They need a separate carefully reviewed identity/secrets migration, not a mass export.
- Private R2 only. Never log source row JSON, presigned object URLs, customer names, values, credentials or provider payloads. Print only table counts and SHA256 digests.
- Server-side `require_platform_admin` executes under the existing maintenance actor before reading RLS-protected tables. It does **not** bypass other existing per-table SELECT policies. The 6 Nov Railway dry-run verified the maintenance actor sees only **one of six** `owner_memberships`, so this entire table is blocked, not partially exported. Every query is inside read-only transactions; the source snapshot is repeatable-read. No temporary restore tables or DB write commands.
- Abort on schema/identity changes, missing keys, duplicate IDs, source cursor mismatch, invalid JSON, an oversized source row, a broken gzip archive, failed R2 remote-byte readback, typed reconstruction mismatch or incomplete manifest.
- The 11 selected tables represent **one milestone**, not the full 148-relation Supabase exit. Separate historical price archives/figure/sealed valuations, actual image binary objects, source reference catalogue, app permissions, OAuth, identities, commissions and all remaining operational tables stay outstanding.
- Cloudflare storage usage and data handling must be checked against the user's UK privacy/retention requirements; archives are restricted to existing private bucket controls.

## How to run and test

Offline (no credentials or production database access):

```sh
PYTHONPATH=backend pytest -q tests/test_cloudflare_exit_source_archive.py
```

On trusted Railway only:

```sh
PYTHONPATH=backend python backend/scripts/archive_cloudflare_exit_source.py
```

After successful local typed readback and approved one-off job configuration:

```sh
TCG_FULL_EXIT_PRIVATE_R2_BACKUP_ENABLED=true PYTHONPATH=backend \
 python backend/scripts/archive_cloudflare_exit_source.py --apply
```

The latter must be executed from the **already authenticated Railway maintenance worker**, not from a workstation with copied secrets. Capture the source counts, digest receipt, completed GitHub CI and Railway deployment reference before reporting `PRIVATE_OPERATIONAL_R2_SOURCE_RESTORE_PROVEN`; if the RLS blocker persists, report **partial-source verification only** and do not stage the incomplete owner membership map into D1. Do not claim uploaded R2 source is live D1 data.

## Next action after a verified private checkpoint

Design signed, private, exact row projection from R2 into `drop-rate-d1-operational-shadow-20261106`, with correct founder/member/physical inventory FK dependencies; compare 6 owners, 621 physical copies, 3 orders, 13 ledger rows and all refunds and webhooks against the captured consistent source. Implement remaining access controls and Stripe/Shopify transaction rules before a live switch. Migrate all remaining source tables by reviewed category, then authentication. Rollback remains the unmodified PostgreSQL system.
