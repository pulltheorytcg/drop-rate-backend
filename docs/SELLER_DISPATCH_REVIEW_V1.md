# Seller Hub → Sales → To ship: owner-scoped dispatch review, v1

**Status:** first safe, read-only phase. This is **not** a carrier label or Shopify fulfillment release.

## 11 October 2026 — Seller shipping payment transparency (read-only)

Founder clarified that the seller must see how much will be deducted before accepting a postage charge, and that customer-paid delivery needs to offset it. Customer checkout price is not the carrier cost. UK Standard Tracked 48 is **£3.95 below £50, free from £50**; UK Tracked 24 stays **£4.95 paid at every order value**. Europe **£14.99** and selected International **£23.99** currently charge shipping at every order value. Do not blindly apply a free-shipping threshold to other services or countries, and never infer checkout shipping from merchandise subtotal: discounts/refunds and live Shopify rate rules can change the captured amount.

**Implemented this phase:**
- `GET /api/v1/fulfilment/to-ship/{order_item_id}/shipping-cost` authenticates one active owner, verifies their exact physical order-item and Shopify link, reads only their order-item ledger `SHIPPING_REVENUE`, `SHIPPING_REFUND` and **reconciled** `SHIPPING_COST` and queries the current Shopify order shipping total, refunded shipping and delivery service titles in **shop currency GBP**.
- A pure deterministic `seller_shipping_charges.py` contract validates both sources, rejects refunded/cancelled orders, malformed money, truncated shipping services, foreign currencies and owner shipping credit exceeding Shopify's whole net delivery payment. It returns the buyer's paid delivery, one owner's allocated share and any **verified** label cost. For one checkout with two physical owners, the customer shipping charge is shown for context but the owner's share comes only from the existing ledger and is **never copied in full to each owner**.
- In the existing Fulfill wizard, seller sees customer-paid amount, their allocated customer payment, real postage cost if verified (otherwise **Pending verified carrier cost**) and additional net shipping adjustment if and only if the ledger has a verified source (otherwise **Pending — not approved**). No bogus £2.95 example or fixed threshold-based carrier guess. Sensitive buyer addresses, customer names and Shopify credentials never enter this response.
- The UI remains read-only for carrier fees. No `shippingLabelPurchase`, label print, `fulfillmentCreate`, customer notification or finance ledger mutation is triggered by viewing costs.

**Commercial policy still requires founder sign-off before applying new charges:** the existing deterministic finance engine currently credits the shipping revenue to owners and debits verified actual postage. If multiple owners ship separately and their pooled buyer-paid delivery revenue is insufficient, an owner may incur a **net postage shortfall even below £50** unless Drop Rate agrees to subsidise that shortfall. The founder suggested seller-funded postage only when the buyer receives free UK Standard shipping; this is **not yet an implemented override**. Do not silently switch net cost treatment or post seller deductions. Decide whether customer-paid shipments have a platform-funded shortfall and how free-delivery costs are capped/approved in the seller agreement.

**Unresolved API limit:** the official Shopify Shipping `shippingLabelPurchase` API purchases a label and returns tracking/documents asynchronously, but does **not** expose a guaranteed per-label merchant postage quote before purchase through its publicly supported Admin GraphQL. The preview therefore cannot promise an exact carrier charge before payment from Shopify alone. To permit a seller to approve a *known* charge, either get a permitted carrier quote source with genuinely matching payable tariff (verify agreement), or publish a deterministic seller contribution schedule/maximum and have Drop Rate fund discrepancies. A buyer's £3.95 shipping fee is not that quote.

**Test gates:** pure money/checkout tests for standard, free £50, Tracked 24 on >£50, paid EU/International, refunds, multi-owner shares, verified carrier cost, missing/unverified carrier cost, bad currencies and unexpected checkout allocation; authenticated SQL owner isolation and UI pending-cost display. No production mutations or paid labels.

---

## 11 October 2026 — Fulfill wizard and Shopify-order packing slip print

**Founder instruction:** Every eligible Seller Hub order must have a **Fulfill** action that leads to a print-confirm-dispatch flow, using native Shopify Shipping labels and a Shopify-sourced packing slip.

**Built in this release:** the existing Sales → To Ship physical-item cards now show **Fulfill**. Opening it triggers an exact authenticated Shopify `FulfillmentOrder` preflight and presents the four steps (verify/pack, print packing slip, Shopify Shipping label, confirm dispatched). The packing slip step calls `GET /api/v1/fulfilment/to-ship/{order_item_id}/packing-slip`, which re-fetches Shopify Order.lineItems, checks source order ID, payment, exact stored physical copies and open remaining Shopify fulfillment quantities. It then returns only this owner's Shopify product titles/SKUs, exact inventory IDs and order number. Browser print uses DOM `textContent`, not arbitrary order HTML. It contains no buyer email, postal address, private note, platform commission, acquisition cost, or another owner's items.

**Shopify's native Admin packing-slip template limitation:** Shopify does not expose an officially supported downloadable **native Admin packing-slip PDF** to third-party Seller Hub apps. Its published print extension guidance uses order GraphQL data and developer-generated print content. Therefore the slip is a **Drop Rate-branded, Shopify-order-derived packing slip**, not a claim that the Shopify Admin PDF itself has been downloaded. Official Shopify Shipping still supplies the separately purchased physical carrier label.

**Not deceptively available:** carrier label purchase, document download, and `fulfillmentCreate` dispatch remain disabled behind explicit steps in the wizard until a verified physical custodian/ship-from address, Shopify carrier quote and purchased-label journal, protection against ambiguous purchases and double settlement postings, correct mixed-owner FulfillmentOrder splitting, and protected customer address access are proven. A seller pressing **Fulfill** does **not** mark anything shipped, charge money, or post ledger costs. Printable packing slip != purchased postage.

**Failure tests:** negative cases for cancelled/refunded/unpaid/fully fulfilled Shopify orders, closed/insufficient FO quantity, duplicate physical IDs, wrong/missing owner Shopify links, 1-of-2 pooled same-variant allocations, multi-owner order with unrelated Shopify lines, browser XSS/stale print state, and rendered content with no customer PII. Local native packing slip test exercises both the Shopify data model and the authenticated owner-scoped read endpoint.

**Remaining acceptance gates:** running code branch must pass full pytest, browser, database and image checks; then the stable production backend must deploy and be read back. A paid, physically dispatchable Shopify test order is still necessary before any live label/dispatch flow can be called ready. The previous 3 order records were two cancelled and one refunded, and no customer order or funds were mutated.

---

## 11 October 2026 — Direct Shopify Shipping API connection (read-only verification live, purchase gated)

Founder confirmed Royal Mail labels can be purchased inside Drop Rate's Shopify Admin and explicitly requested the **native Shopify Shipping** integration, not another carrier subscription.

**API version discovery:** the connected ChatGPT Shopify wrapper exposes an older `2026-01` mutation schema and cannot call `shippingLabelPurchase`. Drop Rate's **own FastAPI `ShopifyAdminClient`** already uses merchant app client credentials and Admin API **2026-07**; Shopify added official `shippingLabelPurchase` in that version. The API is accessed directly by the existing backend using its existing store credentials; we do not add a service, carrier account, third-party token, or webhook.

**Connected code:**
- `backend/app/shopify_shipping_labels.py`: official `order.fulfillmentOrders` read (no customer address requested), exact owner-vs-fulfilment-line quantity comparator, merchant-authorized Shopify Shipping purchase input validator, official asynchronous `shippingLabelPurchase` mutation and `ShippingLabelPurchaseResult` polling parser. It supports Shopify's verified `originAddress` override for seller-held inventory, measured package weight/dimensions (ENVELOPE/BOX etc), confirmed carrier/service codes and ship date, but cannot be invoked for a paid purchase from the Seller Hub yet.
- `GET /api/v1/fulfilment/shopify-status`: owner-authenticated read-only verification of **the backend's own Shopify app** with `probe_shop`, scoped app access, 2026-07 API version. It always reports `carrier_label_purchase=false` until the separate purchase release.
- `GET /api/v1/fulfilment/to-ship/{order_item_id}/shopify`: exact physical owner + Shopify line scoped by authenticated membership; queries the **live** Shopify payment, cancellation, `FulfillmentOrder` status/location/destination country and line items. Compares every remaining FO item quantity to only this owner's linked copies; mixed-owner same-variant quantities, other owners' order lines, partial refunds, truncated pages, held/closed/fulfilled FOs, mismatched order references, missing location and any unconfirmed physical custody are fail-closed. Never return buyer email, full address, seller secrets or internal cross-owner allocation.
- Existing Sales → To ship panel now has useful **Verify Shopify** and **Check Shopify** actions, *not* inert Buy/Dispatch buttons. Readback is session-aware, text-safe and mobile responsive.

**Evidence:** Shopify connected Admin GraphQL read-only query against a genuine (historical) Drop Rate order returned payment `REFUNDED`, cancellation present, FO `CLOSED`, remaining quantity `0`. This proves the store's core FulfillmentOrder read permissions and status contract (using the connected Shopify app); it is **not** a real paid-order label test. Current database has 2 cancelled and 1 refunded Shopify orders, no paid dispatch candidate. Backend merchant token permission is probed per signed-in seller session and not claimed live until a proper in-app readback. Do not display a carrier price based on guessed 50 g packing.

**Why label purchase stays disabled:** the official `ShippingLabel` GraphQL object has documents and tracking but **does not expose its verified carrier purchase cost**. The ShopifyQL `shipping_labels` analytics schema can aggregate `shipping_label_costs` by order, but that is not an auditable per-label amount for a potentially **multi-owner, multi-parcel** checkout. Never infer postage from customer-facing £3.95/£4.95/£14.99/£23.99 or from example Royal Mail rates. A label purchase charges the Shopify store and returns an async job; retrying after a timeout could purchase twice. Activation needs a unique, persistent owner/FO purchase journal with UNKNOWN timeout reconciliation, confirmed packed weight/insurance/origin, a real cost quote/merchant acceptance, authorised protected buyer address access, a tested Shopify FulfillmentOrder split when owners share one FO, exact tracking sync and eventual invoiced-cost ledger reconciliation. Shopify also requires matching `write_orders` + fulfillment scopes, shipping terms, and (when user-authenticated) `buy_shipping_labels` staff permission. Both native UI and the merchant app must be tested; being able to buy manually in Admin does not by itself prove the backend app can buy.

**Testing:** `tests/test_shopify_shipping_labels.py` validates official payload/polling, PII redaction, carrier quote/custody/duplicate-purchase gates and more than a dozen malformed/shipping variants; `tests/test_shopify_native_connection.py` tests exact SQL owner authorization, remote Shopify status, partial refunds, wrong owner and no buyer data; browser/UI cases check the actual verification button and no fabricated label purchase. No production purchase, label, customer notification, invoice or payout entry is created by this release.

**Rollout:** no new SQL tables, secrets, approvals, routes that charge money, workflows or Shopify theme publication. All standard CI and Railway predeploy tests must pass, followed by `shopify-status` readback from a signed-in account and a true paid-order pilot before paid labels/fulfillment are enabled. Ship-from verification must distinguish owner and actual custodian; Shopify's custom `originAddress` is valuable but cannot substitute for physical custody policy.

Official: https://shopify.dev/docs/apps/build/orders-fulfillment/order-management-apps/purchase-shipping-labels ; https://shopify.dev/docs/api/admin-graphql/2026-10/input-objects/ShippingLabelPurchaseInput ; https://shopify.dev/docs/api/admin-graphql/2026-10/objects/ShippingLabel

---

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
