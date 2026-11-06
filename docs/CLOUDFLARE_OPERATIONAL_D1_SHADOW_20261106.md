# Operational D1 shadow — precise boundary (6 November 2026)

**In review. No production data has been imported; no Cloudflare operational D1 database was created by this PR.**

## What and why

This is the first concrete, isolated SQLite/D1 **schema** for the transaction-sensitive half of the complete Supabase exit. Catalogue-only D1 work cannot replace founders' ownership, consignor attribution, costs, Shopify orders, refunds, immutable ledger and audit records. The new `database/cloudflare_d1/0001_operational_shadow.sql` intentionally uses `ops_shadow_*` names, with **no active production pointer**. It cannot silently become a live operational database by merging a PR.

## What it connects to

- Original PostgreSQL `tcg.owners`, `owner_memberships`, `inventory_items`, `orders`, `order_items`, `shopify_webhook_events`, `financial_ledger_entries`, `refund_events`, `inventory_reservations`, `payout_requests`, `shopify_order_item_links`, `media_assets`, `audit_events` — **read-only source** until exact source snapshot/restore is implemented and independently approved.
- External new identity provider (pending): `ops_shadow_identity_map` stores legacy UUID/external subject mapping only. Never import old Auth passwords, refresh tokens, OAuth/MFA secrets, access tokens or live sessions.
- R2 (pending): encrypted/restricted private source snapshots and append-only audit/market history; canonical catalogue references separately indexed in existing catalogue D1 staging DBs. `ops_shadow_catalogue_links` uses exact immutable stable reference identifiers, not ambiguous titles.
- FastAPI business logic (pending): signed private Cloudflare Worker access, RBAC/owner checks, deterministic commission, locking/idempotency and Shopify allocation. **D1 has no PostgreSQL RLS**; SQL foreign keys alone do not enforce who is calling.
- Shopify and n8n continue to call FastAPI; no direct browser/Shopify D1 credentials, no ledger computations in n8n.

## Checks built into the schema

- One D1 transaction boundary contains owner, exact physical inventory, order, source-ref-unique webhook inbox, sale item, refund and financial ledger. No cross-D1 financial transfer.
- Negative refund/chargeback ledger entries are permitted and source keys are unique; source acquisitions and unobserved Market Values remain NULL instead of zero.
- Owner, inventory and order-item FKs; sale owner must equal inventory owner, and refunded line must match original owner, item and order.
- Prevent silent update/delete of staged financial ledger and audit events, and reject post-sale change to inventory ownership lineage.
- At most one ACTIVE reservation per inventory item within a staging generation.
- Provider credentials, session tokens and password hashes are **not** in the shadow identity map.
- Original source record JSON plus SHA256 can preserve all source columns for later typed parity verification. A hash length `CHECK` is not proof that real source bytes have been read back.
- `ops_shadow_table_receipts` can only record matching verified source/staged SHA256 and row counts. No active pointer or automatic store price changes.

## Failure points

SQLite lacks PG `FOR UPDATE`, stored procedures, original RLS and triggers; changing a DB URL does not recreate them. D1 batches have per-database transaction semantics but a cross-R2/Worker/Shopify operation needs an idempotent outbox and replay. `INSERT OR IGNORE` blocks identical webhook IDs but a distinct logical business event must have its own additional idempotency key. Upserts must never rewrite ledger, old audit history or original ownership lineage.

Legacy inventory schema includes older `recommended_retail_minor` and other fields. Those source columns must be retained in private source archives for lossless restoration, but they are **not** eligible public Market Values. Non-GB Pound source currencies must be independently reconciled; no hardcoded FX assumptions.

## Tests and remaining gates

`python -m pytest -q tests/test_d1_operational_shadow.py` runs an in-memory SQLite implementation of the proposed D1 schema (not Cloudflare production) and tests:
- two different founder-owned copies in one Shopify order;
- 100 duplicate webhook deliveries, one inbox row and one posting;
- partial refund reversal, negative accounting amount and penny totals;
- optional cost NULL; wrong owner/lineage blocked; single active reservation;
- immutable ledger and audit records; no auth token/password columns;
- absence of production-active pointers.

**Still required before real operational imports:** actual Cloudflare D1 preflight with the scoped Cloudflare token, private R2 operational source export, exact per-table row digests and typed restore, safe Auth replacement, signed FastAPI Worker adapter, multi-owner/consignor owner-scoped API tests, independent rollback, production shadow reconciliation and explicit founder-controlled cutover. The actual D1 schema must be rechecked against all source finance columns, including commissions/fees and settlement parity. No live orders or refunds should route here until all these pass.
