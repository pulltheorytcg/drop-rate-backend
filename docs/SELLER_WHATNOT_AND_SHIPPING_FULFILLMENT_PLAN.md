# Drop Rate — owner-specific Whatnot and shipping fulfilment implementation gate

Date: 10 October 2026. This documents a newly requested capability. The Phase 2 Operating Manual prioritises storefront launch, measured operational simplicity and gated workstream reopening; **do not silently activate new customer/seller shipping automation before those gates and explicit commercial decisions**.

## 1. Seller's own Whatnot account

- A Seller Hub seller must link **their personal, approved Whatnot seller account** to **their own Drop Rate owner ID**, not install a Whatnot Shopify sales channel on the Drop Rate company's single Shopify store. The latter syncs the *store*, not a distinct unrelated seller, so the old "Set up" link was removed.
- Whatnot Seller API documentation supports OAuth for third parties, with per-app `read:inventory`, `write:inventory`, `read:orders` and optionally order/shipment scopes. **Developer preview is closed to new applicants** as of 10 October 2026. We have no approved Drop Rate Whatnot client/redirect credentials, and must not simulate a working connection.
- Current response `DEVELOPER_ACCESS_REQUIRED` is an **honest disabled status**. Never ask sellers to enter Whatnot passwords, paste private tokens, or connect Whatnot to the Drop Rate Shopify admin.
- Only after Whatnot authorises Drop Rate: implement `seller_channel_credentials` keyed by owner and provider; server-side encrypted tokens; OAuth authorization code+state/PKCE as applicable, tenant/account-bound callback and verified authorised scopes, rotation/revocation, scoped disconnect, activity log, rate limits, webhook verification and idempotent exact-item listing sync. Expose `Connected as @seller` only after a successful credential round trip and verified owner identity.
- Ownership and prices remain in Supabase/FastAPI. A single physical item must never be available for sale simultaneously on independent channels without inventory reservation/reconciliation. Whatnot funds/fees must not be attributed using Shopify order accounting.

Official:
- https://developers.whatnot.com/docs/getting-started/introduction
- https://developers.whatnot.com/docs/getting-started/authentication

## 2. Checkout shipping funding policy — confirmed 10 October 2026

The founder clarified the **shipping-financing model**, so no seller courier billing integration is required merely to decide who bears postage:

- **Shopify checkout** is the one source of truth for the delivery rate that the customer sees and pays. In the live General shipping profile, the current **United Kingdom** options are Standard **£4.99**, Express **£6.99**, and free Standard on a `TOTAL_PRICE >= £50` condition. The requested replacement threshold is **£10**, with orders below £10 paying delivery. **International rates remain £14.99 (EU) and £23.99 (other listed countries)**. Whether the £10 threshold applies only to the UK must be explicitly verified before a live rate write; international free postage must not be inferred.
- The attempted `deliveryProfileUpdate` to change the free-rate price condition from £50 to £10 was rejected by Shopify with `The condition with id {condition_id: 448537821531} could not be found`. **Checkout has NOT been altered.** Never report £10 as live until Shopify shipping-rate readback and test checkout confirm it.
- **Free shipping:** the customer contributes **0p** postage revenue; the **actual purchased label charge** (not the hypothetical £4.99 rate) reduces the physically responsible seller's eventual net proceeds as a deterministic `SHIPPING_COST` ledger entry.
- **Customer-paid shipping:** the exact Shopify-paid delivery amount is an auditable `SHIPPING_REVENUE` entry; each actual label invoice is `SHIPPING_COST`. The customer's payment offsets label charges. Never debit `£4.99` from a seller *on top of* the actual postage cost; never claim postage has been covered unless the recorded customer payment is sufficient.
- **Multiple sellers:** one Shopify shipping charge is allocated **once**, using the existing `allocate_minor` weighted distribution across owner items. Each independently purchased physical label is charged only once against its own eligible dispatched items; a jointly packed parcel's cost is divided by the item net values using deterministic rounding. If the collected shipping charge is less than the total of multiple actual labels, the platform-versus-seller **shortfall policy requires a separate sign-off** before settlement is marked verified.
- Financial rules must use GBP minor units and existing `financial_ledger_entries` /`order_item_reconciliations`; the seller's acquisition cost remains independent, and no ledger should be posted from a predicted rate or fake PDF. Existing tests in `tests/test_customer_shipping_seller_postage_policy.py` cover free, paid, multiple-seller and unknown-cost cases.

**Shopify Shipping labels are now technically possible:** Shopify released GraphQL `shippingLabelPurchase` in stable API **2026-07**, which purchases carrier-issued labels asynchronously for eligible fulfilment orders; see https://shopify.dev/docs/apps/build/orders-fulfillment/order-management-apps/purchase-shipping-labels. However, the GraphQL schema currently exposed by Drop Rate's connected Shopify integration **does not expose that mutation**. Version upgrade and feature/terms/permissions, protected customer-data and shipping-rate preview checks are required before purchasing labels; no live purchases have been attempted. The purchase API by itself does not guarantee an exact previewable carrier invoice before buying, so a proper quoted-cost/approval strategy must be validated.

## 2. Shipping in Seller Hub — operator choice required

Goal: seller opens a **paid, allocated order**, obtains a real carrier-accepted label with a visible cost, prints **4x6 thermal or A4 PDF**, packs/dispatches their own items, and Drop Rate updates only their Shopify fulfilment-order line quantities with validated tracking.

**Critical distinction:** `owner_id` identifies who owns the physical card, but not necessarily **who holds it or pays shipping**. Seller-held goods should be dispatched by the seller. Physically consigned Drop Rate-held goods must remain in Drop Rate fulfilment and must not leak the buyer's shipping address to the consignor. Add a reviewed per-copy `fulfilment_party`/custody policy and verified shipping return address first.

### User-level flow

1. Sales tab → **To ship** (a compact queue, not an extra primary navigation screen). Show only the current owner's authorised paid Shopify allocations and only when they are responsible for physical dispatch.
2. Seller opens a shipment. FastAPI resolves the exact `order_items` + `shopify_order_item_links` allocation for the owner, checks `orders.status=PAID`, inventory `SOLD`, full/partial refund/cancellation state, assigned custody, carrier account readiness, Shopify FulfillmentOrder `remainingQuantity`, and address eligibility.
3. Backend obtains a carrier rate and explicit charge from a **connected carrier account**. User sees service, estimated delivery, insurance, dimensions/weight, ship-from address and final GBP cost. No money moves until the seller explicitly confirms this rate.
4. After confirmation, FastAPI locks a unique shipment purchase key, performs carrier label purchase once, persists the provider transaction/reference and a private label file reference (not public unrestricted URLs), tracking number/carrier/status, and returns an authenticated expiring PDF/4x6 print route.
5. **Buy label is not ship**: seller must press a separate **Confirm dispatched** action after printing/handing over, or a verified carrier acceptance event may be used under explicitly approved policy. The fulfilment transition uses Shopify GraphQL `fulfillmentCreate` and `lineItemsByFulfillmentOrder` mapping with **only the seller's allocated quantities**, not the entire mixed-owner Shopify order; use `notifyCustomer` according to policy.
6. On verified Shopify success, store `fulfillment_gid`, timestamp, tracking and audit. On ambiguous network timeout, query Shopify by order/fulfilment/tracking before retry to avoid double fulfilments. Surface discrepancies in Action Required rather than silently increasing quantities.

### Required seller isolation and safety

- A seller's credentials/session grant access only to their owner allocations and their own purchased labels; do not expose addresses or other owners' items to unrelated sellers.
- A Shopify order may contain two owners or two units of the **same Shopify variant** owned by different people. Fulfilment orders are Shopify/location scoped, not owner scoped; map exact `shopify_line_item_id`, owner-allocated `order_item_id` and quantities. Handle same-line split, cancelled/refunded units, duplicate and out-of-order webhooks.
- A label is not a plain PDF we invent: it is carrier-issued postage purchased through an authenticated service. Never call something "Ready to print" until the carrier confirms the label can be downloaded. Store buyer shipping details only when necessary, encrypted/access restricted, and do not expose PDFs through unrestricted bucket URLs.
- A label with no dispatch confirmation is `LABEL_PURCHASED`, **not** `FULFILLED`. The Shopify order is marked partially fulfilled if another seller still has items to dispatch.
- Shipping charge payer is a **commercial decision**: platform account/deduct costs in settlements versus individual seller-paid carrier account. Never assume, and never automatically debit the seller's net proceeds without an approved fee policy. Shipping costs in existing financial ledger must be reconciled deterministically.

### Carrier selection

- **Royal Mail Click & Drop API**: creating orders and retrieving labels requires a compatible Royal Mail **Online Business Account (OBA)**. Its API does not retrieve labels from Online Postage (OLP) accounts. Need a connected account and return/shipping origin info.
- **Shippo API**: obtains carrier rates and purchases PDF/PDF_4x6 label transactions, with carrier-account options; requires Shippo credentials/account and explicit quoted cost confirmation. Can be adapted as a replaceable carrier if chosen.
- More carriers later using independent FastAPI adapters, only as needed. Avoid one-off integrations in n8n; it orchestrates notices, not payout/carrier/business logic.

Official:
- https://help.parcel.royalmail.com/hc/en-gb/articles/360011462338-Integrating-with-the-Click-Drop-API
- https://docs.goshippo.com/shippoapi/public-api/transactions/createtransaction
- https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/fulfillmentCreate

### Proposed minimal database boundaries (not yet migrated)

- `owner_fulfillment_policies`: verified shipper/custody+return address and carrier billing model, manually approved.
- `owner_shipments`: owner_id, internal_order_id, carrier/account, status `DRAFT → QUOTED → LABEL_PURCHASED → DISPATCH_CONFIRMED → SHOPIFY_FULFILLED`, carrier references, tracking, Shopify fulfilment IDs, request idempotency, audit timestamps and exception state.
- `owner_shipment_items`: shipment ID + unique `order_item_id`, exact owner, quantity=1, mapped Shopify order/line/fulfilment-order line IDs, immutable historic references.
- `shipping_label_documents`: protected label blob/key, private access expiry, page format, status. Do not put shipping addresses or payment tokens in frontend/local storage/n8n logs.
- `channel_owner_credentials`: separate per seller and provider, encrypted tokens/secrets (no plaintext Supabase tables or unredacted audit changes).

### Test gates before any live label/fulfilment

1. Owner A cannot list/read/mutate owner B's jobs, addresses, files or carrier account; founder admin cannot silently reassign custody.
2. One Shopify order, two different sellers, separate partial fulfilments and unique tracking; same Shopify line quantity 2 assigned to different owners; aggregated financial balances unchanged.
3. Only paid/unrefunded/uncancelled items dispatch; refunded after label paid invokes exception/refund flow, not a second label.
4. Repeated label-purchase request, HTTP timeout after purchase, race with order refund, duplicated Shopify order webhook, two browsers clicking "Dispatch" all remain idempotent.
5. Label PDF downloaded/printed at 4x6 and A4, expired URL denied, unauthorized download denied, tracking and Shopify fulfilment confirmed via live readback.
6. Carrier sandbox first; one approved low-risk test order on the target Shopify storefront; confirm customer email, status and rollback. No real postage purchase or stock mutation without explicit cost approval.

## Release gates

Do not claim either feature operational today: Whatnot API access and a carrier account/billing decision are missing. Storefront launch/efficiency requirements from Phase 2 must be checked before broad release. No new Railway service or unversioned n8n workflow. Full tests/documentation/audit and explicit merchant approval required.
