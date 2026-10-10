# Seller Hub → Sales → To ship: owner-scoped dispatch review, v1

**Status:** first safe, read-only phase. This is **not** a carrier label or Shopify fulfillment release.

## What and why

Add the minimal **To ship** section inside the existing Seller Hub Sales view, rather than a second application or new primary navigation item. A future paid, allocated Shopify order now has a place to appear for its physical owner. Each line is an **exact tracked Inventory ID**, not a guessed quantity, variant or seller summary. The same guarded API can serve a founder's own inventory through Founder HQ in a later release.

The existing `/api/v1/owner/finance/sales` remains the immutable accounting history. To ship is intentionally separate: refunded/cancelled orders must not be treated as open dispatch work merely because they sold previously.

## Connections

- `/api/v1/fulfilment/to-ship`: `GET`, authenticated Supabase bearer token.
- `tcg.current_user_id()` scoped transaction, `current_access_context()` for active, unique founder/consignor membership.
- `tcg.orders` + `tcg.order_items` → exact `tcg.inventory_items` → `tcg.catalogue_products` → `tcg.shopify_order_item_links`.
- The `owner_id` from server-verified membership is used in **all** physical inventory and Shopify line queries. Founder authority does not expose another owner's physical stock.
- Only orders with `source='SHOPIFY'` and status `PAID` or `PARTIALLY_REFUNDED` appear. Partially refunded orders are explicitly blocked for review; `CANCELLED` and `REFUNDED` are excluded.
- The Seller Hub standalone `owner-fulfillment.js` listens for authenticated `hub-ready` and Sales view changes, ignores stale responses after navigation/logout, uses `textContent`, and never renders protected buyer details.
- The customer-facing website and Shopify paid-order webhook business logic are unchanged.

## What is deliberately impossible in v1

- **No buyer address, email, phone, or Shopify customer profile** appears in the response. Even a matching `storage_location_id` does not prove physical custody or a safe return address.
- **No carrier-rate claim, Royal Mail/Shippo login, PDF, label payment, tracking write or Shopify fulfillment mutation** is available. No fake printable label.
- Every unshipped candidate is shown as **Requires review**, including a clean `PAID` item, until true physical custodian, sender address and remote FulfillmentOrder line/remaining quantity are verified.
- If the order is partially refunded, physical inventory state is inconsistent, or the exact Shopify owner/order/line/variant link is missing, the queue returns explicit blockers, never greenlights dispatch.
- No Postgres migration, new Railway service, background n8n workflow, customer order mutation, SKU/stock edit, payouts or fee ledger changes.
- The three currently recorded Shopify orders were two `CANCELLED` and one `REFUNDED` at preflight. Thus production should show **zero dispatch candidates** until an actual paid order exists. Do not manufacture a real Shopify order merely to populate the UI.

## Risks and tests

1. **Owner isolation:** consumer-facing `GET` resolves exactly one active owner; SQL filters by `oi.owner_id`, `i.owner_id` and `sol.owner_id`. Tests inject a foreign owner ID and buyer PII into a fake database row and prove neither is returned.
2. **Refund/race:** all partial refunds blocked, fully cancelled/refunded excluded, physical status mismatch and missing/wrong Shopify order links blocked. No irreversible action available.
3. **Reliability:** paginated owner-scoped query (max 50), unauthenticated request rejected by existing bearer dependency and membership guard, UI handles empty/error/loading, ignores stale account/session changes.
4. **No false success:** capabilities advertise `carrier_label_purchase=false`, `dispatch_confirmation=false`, `shopify_tracking_sync=false`, `buyer_address_access=false`; UI has no inert buy/ship buttons.
5. **Visual/UI:** add separate responsive CSS with existing navy/white styling; no lime/acid-green redesign; works on a mobile-width Sales view.

Run existing backend tests, dashboard suite and pinned n8n build on exact PR head. Test database role/RLS isolation separately before adding any buyer address access. Signed-in Seller Hub mobile acceptance and actual paid Shopify dispatch are **not proven** by mock-data tests.

## Phase 2: ship a real parcel (not active)

Once explicit custody and Royal Mail account/payer policy is verified:

1. Record `fulfilment_party` (actual verified physical custodian, not automatically `owner_id`), ship-from address and permissions in restricted tables; no plaintext sensitive buyer address logs.
2. Backend reads `orders/paid` and checks live Shopify `FulfillmentOrder` ownership/remaining quantity and refund/cancel state on every dispatch attempt, including split Shopify line allocations across owners.
3. Obtain actual packed-weight/dimension/declared-value/insurance quotes from a permitted provider. On explicit seller approval, idempotently purchase a **carrier-issued** label, journal charge/transaction once and store the PDF privately with expiring access.
4. Seller presses **Confirm dispatched** after handover or verified carrier acceptance; only then FastAPI calls Shopify `fulfillmentCreate` for the exact eligible FulfillmentOrderLineItem quantities and re-reads tracking. A timeout creates UNKNOWN reconciliation, never a second blind write.
5. Post **actual** `SHIPPING_COST` and one allocated Shopify `SHIPPING_REVENUE` in PostgreSQL. No duplicate deductions or verified settlement with missing label charges. Handle refund-after-label and high-value insurance exceptions.
6. Test one approved low-value, real paid order on the **target Shopify store** with buyer notification and reversal policy; test owner A/B split variants, seller role isolation, race/replay, tracking/partial fulfillment, cancellations and returns.

Do not activate a third-party consignor dispatch or automatic carrier purchasing on the basis of this read-only queue.
