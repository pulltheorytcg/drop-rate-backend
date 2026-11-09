# Drop Rate — inactive D1 shipping, shipping-refund and payment-fee ledger

9 November 2026 | source-of-truth exit tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## 1. What and why

The verified *live* PostgreSQL source currently has **3 SALE_REVENUE (+249p), 3 REFUND (−249p), 3 SHIPPING_REVENUE (+1,497p), 3 SHIPPING_REFUND (−1,497p), 1 PAYMENT_FEE (−36p)**, all PENDING. All 13 entries have non-null exact order and item identifiers and one recorded owner per entry; no owner/customer IDs were exposed in the aggregate audit. Source financial history must not be rounded, merged into card price or lost. The merged inactive card-refund D1 kernel (#1029) covers only the card sale/refund component, so a D1 finance cutover would still lose shipping and processing fee evidence.

This patch extends the **UNUSED, DISPOSABLE candidate** schema with append-only owner-linked SHIPPING_REVENUE, SHIPPING_REFUND and PAYMENT_FEE entries, each requiring an independently authenticated, exact source event and original item ID. It does not automatically allocate order-level shipping, estimate processor fees, guess proof of customer payment or reconcile a live payout.

## 2. Connections

- `database/cloudflare_d1/candidate/0001_atomic_sale.sql` (inactive test-only candidate definition) extends allowable ledger signs/types and pending outbox types without touching existing `ops_shadow_*` D1, Supabase or Shopify.
- `database/cloudflare_d1/candidate/0003_shipping_payment.sql` defines source-keyed exact per-order-item shipping allocations, separate cumulative shipping refund events, payment fee events and trigger-owned pending ledger + corresponding outbox events.
- `backend/app/d1_candidate_shipping_ledger.py` prepares parameterized SQLite statements for verified source event input only, with strict canonical UUID, GBP-penny, source, timestamp, digest and kind. It has no HTTP endpoint, Cloudflare token, owner lookup or checkout request. **Only a later signed private FastAPI/Worker bridge may execute these statements.**
- `tests/test_d1_candidate_shipping_ledger.py` uses disposable real SQLite and synthetic owners/Inventory IDs to reconstruct the **observed live ledger's aggregate entry counts and exact penny totals** without copying customer data, plus multi-owner and duplicate-source attacks.

The correct future chain is Shopify/eBay verified source → canonical order item, allocation, owner and signed proof in FastAPI → one private D1 transaction → append-only per-owner ledger/outbox → accounting reconciliation → verified manual settlement. A valid D1 snapshot must match the original PostgreSQL transaction/owner/source mapping **per row** and exact penny totals, not only aggregate counts.

## 3. Failure and audit behaviour

- One original shipping allocation per physical order item. An existing allocation cannot silently be edited; duplicate source identities fail closed. If a split is missing or ambiguous, require staff review, not guessed division by items or prices.
- Each shipping refund must match the original owner, order and provider and cumulatively remain within its original positive shipping allocation. Historical shipping credit/refund ledger totals must agree with source events before any additional refund. **Shipping refunds never affect card commission or physical stock status.**
- Payment processor fees are owner-linked debits sourced from a verified provider event; the gate rejects unmatched order/owner, wrong source and excessive fee against card net plus verified shipping amount. Fees are not estimated or automatically charged to customers.
- Each original event is immutable, with a UNIQUE source reference and checksum replay comparison. Trigger failure (including a late outbox unique collision) rolls back event, ledger and outbox together. All ledger entries remain `PENDING`; no automatic payout or movement of funds.
- Source refunds can occur in either order (card return first or shipping refund first) as long as each event has exact provenance.
- No global warehouse owner override, direct browser database token, non-GBP settlement, silent reapproval, sale-status manipulation or n8n business logic is permitted.

## 4. Testing and no-go

Offline test cases include the actual **13-entry / −36p net** source-shaped ledger with only synthetic identities; mixed founder/consignor owners, partial shipping refunds to £4.99, over-refunds, absent allocations, wrong-owner and wrong-order source, duplicate source with changed body/amount, tampered previous ledger, invalid fees, late outbox failure, immutable history, bound SQL input/invalid money. Existing card commission and refund tests must remain green.

Before using it for *real* D1 money: implement and deploy a **signed restricted Worker** with one validated D1 `batch()` transaction and a safe staging-only credential; complete independent real Source→D1 byte/typed ledger parity after Cloudflare capacity upgrade; implement business-approved per-owner shipping and processor fee source mapping, source write freeze/replay, verified external auth/founder roster, payout holds, refunds/cancellations, backup/rollback and zero remaining active Supabase consumers. No dual financial writers.

Rollback now is reverting the unused candidate files. **Nothing here changes production D1, Supabase, Shopify, Railway variables, actual payments or consignor balances. Supabase exit remains NO-GO.**
