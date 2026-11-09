# Drop Rate — inactive D1 refund and commission mathematics (9 November 2026)

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## 1. What we are building / why

An independent, deterministic **penny-exact refund preparation function** for the Cloudflare D1 financial writer, following the existing PostgreSQL `tcg.calculate_commission_minor` and cumulative commission-reversal policy. It is pure Python, with no API endpoint, D1/Shopify/Supabase access, payment execution or financial mutation.

Current manual PostgreSQL refund flow (`backend/app/refunds.py`) separately sums shipping revenue into the refundable ceiling, but `tcg.apply_commission_ledger()` checks cumulative `REFUND` debits against the *card sale* amount. This creates a possible disagreement when a single refund event covers shipping and card value. **Do not silently infer or change historical refund allocation.** The D1 candidate explicitly separates `card_refund_minor` from `shipping_refund_minor` and refuses unknown mixes.

Code: `backend/app/d1_candidate_refund_math.py`; tests: `tests/test_d1_candidate_refund_math.py`. It reuses the new candidate paid-sale commission rounding function (merged #1026) and keeps founder marketplace commission at zero.

## 2. Connects to

Verified Shopify/eBay refund webhook -> trusted FastAPI source mapping -> exact original `order_item_id`, owner, inventory and currency -> *single future D1 transaction* -> append-only refund debit, optional shipping refund debit, nonnegative **cumulative** commission reversal credit, and optional inventory move to `INSPECTION` only after the full original card sale value is refunded.

The caller must compute **prior totals from the same financial authority inside the atomic transaction** and enforce unique source reference/idempotency keys. Values obtained from user-provided data, stale API reads or an unsigned webhook are not sufficient. A future signed, restricted D1 Worker and audited schema revision are still necessary; this module does not write or authorize refunds.

## 3. Failure/exception policy

- Original commission mismatch with source sale, negative/oversized/noninteger pennies, wrong currency, bogus boolean flags, over-refund of card or shipping, inconsistent previous reversal and repeated return-to-inspection all fail closed.
- Partial card refunds reduce marketplace commission according to `round((original net - cumulative card refunded) * original snapshot rate / 10000)`; the **incremental reversal** is the difference from the already verified historical reversal. Do not repeatedly round each new refund independently.
- Shipping-only refunds must **not** release commission on a card. A stock return requires one SOLD physical unit and a full original card-value refund, and leaves the item in inspection rather than relisting immediately.
- Historical PostgreSQL mixed shipping/refund reconciliation and partial refund source key deduplication remain unverified. Any ambiguous data goes to Action Required; the D1 migration must not auto-pay a consignor.

## 4. Tests / rollout and rollback

No-network Python 3.12 tests cover multiple partial refunds to a full return, split shipping/card refunds, founder and consignor rates, 0.5p rounding, changed original commission, inconsistent historical reversal, exceedances, duplicate-restock attempts and immutable-output assertions. Full backend CI remains mandatory.

This patch does **not** extend the merged #1026 candidate SQL schema with refund-ledger posting or enable a D1 financial write route. That needs a separately reviewed versioned D1 database schema, transaction triggers/guards, exact item-level shipping allocation, replay/rollback, and independently verified live source parity before any production cutover. The source PostgreSQL/Shopify/Railway/Auth services are untouched. Rollback is reverting the pure module and tests, with zero live data or credential changes.

**Supabase retirement remains NO-GO.**
