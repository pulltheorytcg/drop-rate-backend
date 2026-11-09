# Drop Rate — D1 candidate atomic card-refund ledger / physical resale-cycle integrity

**9 November 2026** | Tracker [#1010](https://github.com/pulltheorytcg/drop-rate-backend/issues/1010)

## What was built, and why

The existing inactive D1 candidate from PR #1026 modeled **one single immutable physical card sale**; the standalone pure refund arithmetic in PR #1028 modeled **cumulative proportional commission reversals**, but did not actually post a D1 ledger event. This patch joins both concepts **inside real SQLite transactions**, preserving original sales and refunds. It does not establish live D1 financial authority.

The original candidate schema had a global `UNIQUE(inventory_id)` constraint on order items. That would permanently forbid resale of a physical Inventory ID after a verified full refund and manual reinspection. We remove that permanent uniqueness **only within this unused candidate schema**, retaining the version-CAS `APPROVED→SOLD` trigger as the exclusive sell-once-per-current-cycle rule. `candidate_inventory.current_sale_item_id` identifies the current sale: a refund from a past sale cycle may not restock an item that was sold again.

## Components and connections

- `database/cloudflare_d1/candidate/0001_atomic_sale.sql` (unused, updated candidate definition): keep sale-history physical ID references, add current-sale identifier, allow `REFUND` and `COMMISSION_REVERSAL` to append-only pending ledger, and allow distinct `REFUND_POSTED` outbox events for multiple partial refunds of one order. Source webhook/paid-order idempotency is unchanged.
- `database/cloudflare_d1/candidate/0002_atomic_card_refunds.sql`: separate source-keyed **card-amount-only** event table and SQLite triggers. BEFORE INSERT validates source provider, exact order/line/inventory/owner lineage, card balance, historical refund debits and original retained commission. AFTER INSERT creates negative `REFUND` and, where positive, cumulative `COMMISSION_REVERSAL` ledger entries, optional exact CURRENT-sale `SOLD→INSPECTION` stock transition, and unique pending outbox event. If any late stage fails, the entire database transaction rolls back. Refund events, sale history and ledger entries cannot be updated or deleted. No automatic relisting or payout.
- `backend/app/d1_candidate_refund_ledger.py`: pure bounded SQL planner that accepts an already signed/verified source event, normalizes UTC timestamps and validates exact UUIDs, GBP pennies, zero-copy SHA and return flag. It cannot guess a card/shipping split; `card_amount_minor` is mandatory positive. A source-key conflict is never treated as safe replay until original event ID, source, owner/lineage, amount, return flag and original payload SHA all match on readback.
- `tests/test_d1_candidate_refund_ledger.py`: local/offline real SQLite/FK trigger tests, cryptographic source assumptions explicit, no calls to live Cloudflare/PostgreSQL/Shopify.

### Critical accounting and stock rules

The shipping-revenue allocation is **not** covered. In the current PostgreSQL system refunds can contain shipping, while the original commission trigger checks card net sale only. This candidate deliberately refuses to post shipping refunds or issue Store Price adjustments until per-owner shipping allocations and settlement semantics are implemented and reconciled. No guessing based on checkout totals, seller offers, retail guide values or current Market Value.

Commission is calculated from the **original snapshotted sale rate** and *remaining card amount*, not re-rounded per refund; `COMMISSION_REVERSAL` is a positive owner credit, `REFUND` is a negative owner debit. Every ledger row remains `PENDING`; fulfillment/payment fees must still be reconciled before settlement.

A full card refund can move the **current** SOLD physical copy into `INSPECTION` only when the full original card amount has been returned, the item still belongs to its original owner, and the item has not moved to a newer sale cycle. A new sale can only occur after a **separately audited/manual reapproval**, which is not implemented in this patch. Old sale/refund history is retained permanently.

### Tests and safeguards

Tests cover mixed founder/consignor original sale, three partial card refunds whose commission reversal totals exact original fee, 0.5p rounding, founder 0% commission, full return to inspection, historical resale after simulated review, seller cross-owner attribution rejection, duplicate or changed refund source-key replay, card over-refund, no return on a partial refund, immutable ledger/refunds, prior ledger tampering rejection, deliberately failed final outbox insertion rolling the whole refund and stock change back, bogus source/UUID/amount and the explicit prohibition on inferred shipping refunds.

**No production deployment of D1 schema or writer**: files are under inactive `candidate/` and a pure Python helper unused by any FastAPI route. The existing `ops_shadow_*` source snapshot and protected D1 catalogue jobs are unaffected.

### Future acceptance and rollback

Before *any* live finance write cutover:
1. Supply a supported verified external identity provider and exact three-founder roster; all owner DB queries must use the **server-resolved** identity, not token claims.
2. Build a signed private Cloudflare Worker / one authoritative D1 binding that accepts only fixed bounded posting operations, executes one `db.batch()` transaction, authenticates the FastAPI caller, blocks direct freeform SQL, and atomically handles source replay/concurrency.
3. Add permitted payment fees, order-level shipping allocations/refunds, cancellations, payout hold/reconciliation, multiple item shipments and reserve/release life cycle with persistent idempotency.
4. Verify exact current Supabase/PostgreSQL source + D1 typed-money/owner lineage, history, 148-relation coverage and RLS-equivalent role boundaries, run restore/replay/rollback drills and freeze/stop the original financial writer before any D1 switch. Never enable two authoritative sources.
5. Review D1 costs/capacity and signed production cutover separately.

Rollback now is reverting these unused candidate files. No existing database, D1 generation, Shopify product, auth session, owner, refund, price, payment or settlement is changed. **Supabase exit remains NO-GO.**
