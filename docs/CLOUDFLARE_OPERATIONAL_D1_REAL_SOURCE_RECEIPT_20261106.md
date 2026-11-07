# Real ownership and Shopify financial records — Cloudflare D1 private SHADOW receipt

**VERIFIED 6 November 2026 at 19:50–19:51 UTC.** Protected-main [GitHub Actions run 42283108326](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42283108326), exact main commit `db660dce5c65096c96faeb7b098fecf08b6ef989`, returned `PRIVATE_D1_SOURCE_PARITY_VERIFIED_ONLY` and `D1 operational shadow status: success`.

## What was actually done

An existing, protected GitHub production workflow used its already configured **Supabase postgres database credential** (no new bypass-RLS role and no RLS-policy changes) to read one **READ-ONLY, REPEATABLE READ** PostgreSQL snapshot. It then populated an immutable, non-live generation in the previously verified private Cloudflare database `drop-rate-d1-operational-shadow-20261106`.

The D1 importer read every record back, matched each source primary key and original JSON SHA256, inserted **nine exact source-table parity receipts**, and recomputed owner/currency ledger balances in D1 and compared them against the snapshot, in minor currency units. All the gates passed.

| `tcg` source and D1 shadow relation | Real records proven |
|---|---:|
| `owners` / `ops_shadow_owners` | 6 (3 founder, 3 consignor; verified separately in source SQL) |
| `owner_memberships` / `ops_shadow_memberships` | 6 |
| `inventory_items` / `ops_shadow_inventory` | 621 |
| `orders` / `ops_shadow_orders` | 3 |
| `order_items` / `ops_shadow_order_items` | 3 |
| `financial_ledger_entries` / `ops_shadow_ledger` | 13 |
| `refund_events` / `ops_shadow_refunds` | 3 |
| `shopify_webhook_events` / `ops_shadow_webhook_inbox` | 14 |
| `media_assets` / `ops_shadow_media_assets` | 515 |
| **Total original source rows copied into isolated D1** | **1,184** |

Original source manifest SHA256: `b82fe8a43aba41b2835283fd3c588bececcb705f18afb2ffcba5b39d36ad54cc`.

The job also read `media_object_mirrors` source metadata and the source catalogue records referenced by physical inventory to establish FK dependencies, but **did not** count those as migrated R2 image objects or full catalogue parity. D1 catalogue-link hashes are source-record fingerprints, **not** receipts for full externally verified R2 catalogue publications. No MFA secrets, passwords, authentication sessions, payment details or external provider tokens were migrated. No Shopify order was generated or payment executed.

## Source security and validation

- GitHub main-branch only; protected `production` environment; approved repo secrets. The source credential is masked and is used only inside an explicitly read-only transaction. Public GitHub artifacts contain only counts and SHA256, never private rows or DSNs.
- Target Cloudflare account and exact isolated D1 database must match; D1 readback requires the original **32/32** operational schema objects.
- Database checks reject duplicate owner/ledger/source IDs, inconsistent owner-to-inventory/shopify-sale lineage, missing canonical references, invalid refund ancestry, unsigned prices or unexpected source count decreases. Source PostgreSQL RLS was NOT disabled or changed.
- The 1,184 D1 records were staged under `STAGING`, with **no active production generation pointer** and **no API read change**. Supabase remains authoritative. A successful isolated D1 snapshot does not establish near-real-time source sync or a roll-forward final cutover.

## Explicitly NOT DONE

1. Actual physical artwork bytes (including slab-specific photos), source R2 SHA256 readback, 66,222 reference image mirror entries, and image rights proof.
2. Verified current UK **Market Value only** and immutable complete R2 price/observation history, including sealed, figures and the legacy catalogue; no RRP/guide/asking prices promoted into eligible Market Value.
3. Full 148-relation app/private/auth/storage migration, 128 PG functions, 156 custom triggers, 272 RLS policies and the remaining app/financial data.
4. Authentication replacement, signed-in founder/consignor permissions, transactional live Shopify/refund/webhook handling and deltas after the snapshot.
5. Full catalogue D1 quota-controlled staging: Lorcana 3,505 verified; Yu-Gi-Oh 8,000/45,418; other R2 imports gated by prior stage quota/coverage.
6. Supabase retirement, deletion, paid Cloudflare upgrade, settlement execution or production cutover.

**State:** source ownership/inventory/order/ledger/media **D1 shadow parity verified**, not a completed Supabase→Cloudflare full migration. Next release gate: complete separate private R2 source/price/media bytes archival with restore; verify the remainder of operational tables and independent identity; then replay deltas and prove transactional access/security before any live route change.
