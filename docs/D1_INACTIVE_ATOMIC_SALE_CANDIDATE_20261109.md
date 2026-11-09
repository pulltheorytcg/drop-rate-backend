# Drop Rate — isolated D1 atomic paid-sale candidate (9 November 2026)

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What we are building and why

A **disabled, standalone Cloudflare D1/SQLite transaction kernel** for the first production-write milestone: one Shopify/eBay paid order containing multiple separately owned physical cards. It records immutable source webhook identity, the order, exact per-item owner/cost/commission snapshots, the SOLD transition, an owner ledger entry and one pending integration outbox event. This is the deterministic part of the operational cutover currently handled by PostgreSQL triggers and asyncpg transactions. It is deliberately not registered as a FastAPI endpoint, cannot contact Cloudflare, and is not deployed or applied to the existing private D1 shadow.

Code:
- `database/cloudflare_d1/candidate/0001_atomic_sale.sql` — fresh disposable/standalone candidate schema, not a migration against `ops_shadow_*`.
- `backend/app/d1_candidate_sale.py` — deterministic checked, bound-statement plan; no token, database client, HTTP method or money transfer.
- `tests/test_d1_candidate_sale.py` — local transactional SQLite integration/competition rehearsal with zero external credentials.

## Connections and intended cutover boundary

Verified Shopify/eBay webhook -> FastAPI signature verification / idempotency authentication -> authenticated owner/inventory lookup -> **one** Cloudflare Worker D1 binding `db.batch([...])` transaction -> one source event + sale and immutable pending per-owner ledger -> signed, controlled outbox delivery to n8n. Cloudflare's current Workers D1 Database API states that `batch` executes statements sequentially in one transaction and rolls back the whole sequence if a statement fails. Do not implement this candidate through separate per-statement REST calls or implicit auto-commit (which could produce a partial multi-owner sale). See https://developers.cloudflare.com/d1/worker-api/d1-database/.

The schema carries the same physical Inventory ID and owner ID model as the original PostgreSQL system. One item can be SOLD exactly once; a second competing order for its ID fails atomically. Every insert must match the current inventory owner, approved sale intent, expected inventory version, acquisition cost snapshot, and commission rate. Founder rate is fixed at **0%**, consignor rate is configurable, rounded to pennies using the original PostgreSQL positive numeric rounding rule. The after-insert trigger advances stock to SOLD and writes the original SALE_REVENUE plus mandatory COMMISSION debit; there is no code path that can insert an item without its ledger. All credited money is **PENDING**, and orders remain `RECONCILIATION_REQUIRED` until marketplace payment fee, shipping, fulfilment and refunds can be independently reconciled.

Replays with a duplicate webhook/external order must not generate another ledger entry. A **same** signed event + SHA256/order mapping may be acknowledged as idempotent *only after* a read-only inbox comparison; the same webhook ID with any different body, shop, source or order is a conflict requiring human review. The transaction itself always rejects duplicate writes; it cannot auto-acknowledge a conflict.

## Failure points / security

- **Live approval is forbidden** until D1 private binding authentication, replacement OIDC identity, founder/consignor role checks, separate development and production databases, and explicit rollback are tested. The candidate has no public routes and no deploy configuration. Do not expose a D1 token in browser code.
- Concurrent order submissions for the same physical Inventory ID, wrong owner, stale version, moved inventory, unauthorised cost or commission change, duplicate event/order, missing/out-of-stock item, wrong currency and a failed later order item **all roll back every statement**. The database guards are independent of potentially stale FastAPI inventory reads.
- No direct writes to the append-only ledger or historical order lines, nor unreviewed transfers of card ownership. No direct payout, automatic settlement or customer card/payment storage.
- No receipt here proves historical Supabase owner/ledger parity. The existing 148-relation complete source register, Auth replacement, refund/return reversals, shipping and payment fees, sale cancellation and payout settlement are **not** implemented by this candidate. The old `ops_shadow_*` staged data has no production pointer and cannot be promoted by this code.
- Cloudflare D1 is SQLite and has no PostgreSQL RLS. Before actual cutover, the Worker must reject every non-FastAPI signed request and FastAPI must verify the exact authenticated actor/owner membership. An owner may not pass arbitrary owner_id in an untrusted request.

## Test and go/no-go contract

Local SQL-backed tests must pass for:
1. One mixed founder/consignor Shopify order with different stock owners, zero founder commission, 10% consignor commission and integer-penny rounding.
2. Source webhook replay vs changed payload, duplicate order, stale inventory version, wrong owner/cost/commission and wrong sale intent.
3. Failure of a second line rolling back first line, source inbox, ledger, inventory SOLD update and outbox.
4. Two competing writers for the same physical ID: **one** order, **one** ledger, SOLD version increments exactly once.
5. Immutable ledger, protected sale lineage, blocked unaudited ownership transfer, parameter binding/invalid input.
6. Explicit no D1/Shopify/Supabase traffic, no payouts and no finance writer route in production.

**Next implementation stages:** add deterministic separate card vs shipping refunds and commission reversals; supported order-level payment/fulfilment fee allocation; owner/payout ledger with conservative funded-state gating; signed isolated Worker bridge + production parity evidence; full Auth/role replacement; freeze/replay/cutover rehearsal with exhaustive shadow/ledger SHA and rollback. After that, and only with explicit owner approval, switch the *single* financial authority from PostgreSQL to D1. No dual writers.

## Rollback

The feature is inactive: deleting/reverting the candidate files removes the entire experiment without changing any live service or data. Never drop or reset production D1/Supabase tables to roll back. If later used in a private disposable test D1 database, discard only that isolated test database with a separately documented test-data cleanup; real source, existing D1 shadow, Shopify orders and owner balances remain untouched.

**Current status:** code/test design candidate only, NOT approved for deployment, NOT a completed D1 financial writer, **Supabase exit remains NO-GO**.
