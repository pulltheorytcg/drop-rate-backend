# Drop Rate — Automatic Net Postage Policy

## Approved commercial rule (11 October 2026)

**The seller sees only a single `Net shipping charge` in Seller Hub, not what the customer paid or the carrier cost.** Drop Rate must retain separate, auditable internal facts for the real customer checkout shipping payment (including promotions/refunds) and the verified carrier label expense.

The policy for NEW Shopify orders is deterministic:

| Delivery selected by customer | Recorded customer shipping revenue | Seller automatic NET shipping debit |
| --- | --- | --- |
| UK Royal Mail Tracked 48, paid below £50 | Platform retains true discounted checkout charge | **£0** |
| UK Royal Mail Tracked 48, free at £50 inclusive and above | Platform retains £0 | **Actual verified label cost** |
| UK Royal Mail Tracked 24, paid regardless of basket | Platform retains true discounted checkout charge | **£0** |
| Europe/International, paid | Platform retains true discounted checkout charge | **£0** |
| Promotional free shipping below £50 / overseas free / missing identity | Platform bears cost pending policy review | **£0**; do not guess eligibility |
| Partially refunded/cancelled/identity uncertain | Review required | **No new deduction** |

**No separate seller approval action.** Once a founder-authorised backend has verified the actual carrier receipt for the physical owner's parcel, FastAPI automatically posts the eligible free UK Tracked48 owner debit in the immutable ledger; customer-paid shipments post £0 seller postage and remain company-funded. Until an actual carrier cost is verified, free qualifying shipment preview says **Pending automatic charge**, not £0 or an estimated number.

The merchant currently allows Royal Mail label purchases inside Shopify Admin, but **the native Shopify Shipping API doesn't provide a guaranteed exact purchase quote**, and seller live label buying remains disabled until an idempotent purchase journal, verified custody, split-FO allocation and the first real paid-order pilot work. This accounting rule is independent of that label-purchasing milestone.

## Implementation

- **Paid order webhook:** `shopify_pipeline._process_paid_order` snapshots actual discounted `shipping_lines[].discounted_price_set.shop_money.amount` when present, merchandise after discounts, destination country and exact delivery title. It inserts one `tcg.shopify_delivery_accounts` row per Shopify order. It does **not** create `SHIPPING_REVENUE` entries in physical-owner ledger. Missing source/discount fields are `NEEDS_REVIEW` and may never trigger automatic owner postage charges.
- **Company refund tracking:** `tcg.shopify_delivery_refunds` stores an immutable, uniquely keyed refund event and ensures total refunded customer shipping never exceeds received shipping. Existing historical Shopify orders *without* a new platform account keep their old owner-shipping-revenue and refund ledger semantics. No retroactive ledger rewrites.
- **Carrier receipt reconciliation:** founder-only `/api/v1/finance/shopify/orders/{order_id}/postage` uses the carrier's verified **actual GBP postage**, exact order, responsible owner ID (including consignors via admin-supplied `owner_id`) and unique carrier label reference. Writes `tcg.shopify_postage_actual_costs` once and automatically determines `owner_net_charge_minor` from platform policy. For customer-paid orders, label cost is *platform cost*, owner debit **£0**. For eligible free UK Tracked48, owner debit equals verified actual carrier amount. Existing physical item `SHIPPING_COST` and `order_item_reconciliations` are populated only as appropriate. No owner approves a postage debit.
- **Seller visibility:** `tcg.owner_net_shopify_postage(order_item_id)` is a tightly scoped SECURITY DEFINER function that checks one active membership and exact physical order owner, exposing just mode/status and ONE net figure, never company revenues, buyer address, carrier receipt, or other sellers. `GET /api/v1/fulfilment/to-ship/{order_item_id}/shipping-cost` independently reads current Shopify payment/refund state but returns only that one net seller charge and status. Seller Hub Fulfill has one charge line, no separate customer or carrier labels.
- **RLS/audit:** the 3 new platform accounting tables are private to authenticated platform administrators and postgres; only INSERT/SELECT for tcg_api, immutable after INSERT, audit events on each new record and unique company refund/label references. No unnecessary buyer PII is stored.
- **Missing/unsupported:** Existing invoice reconciliation handles one aggregate verified carrier invoice per order+owner and **does not yet validate multiple parcels for one owner or a shared parcel between owners**; those require manual exception workflow before net charges can be posted. New shipping account rules and current marketplace rate settings are separate; do not assume £50 always makes Express or international free. A customer-facing shipping discount could be present below £50; the source line governs paid vs free.

## Failure tests and rollout sequence

1. Pure contract tests: UK £49.99 paid, UK £50 free, paid Express at £200, EU/International paid, promotional free under £50, missing country/missing discounted lines, incorrect currency, actual label missing/negative, duplicate owner invoice, refund/cancel.
2. Static/write-boundary checks for owner ledger suppression and separate platform account, exact RLS function output, no buyer/customer/carrier amounts in seller UI.
3. Full backend CI, Seller Hub browser UI, real PostgreSQL migration/privilege checks, n8n build. No external label purchase during tests.
4. Apply additive production migration BEFORE backend deployment; preserve historical records. Verify Railway production health and print regressions, then conduct a controlled paid Shopify test order when available. The previous 3 Shopify orders were cancelled/refunded. No retroactive payouts.
5. Later Shopify Shipping label purchase + printing and fulfilment, after actual shipping costs can be confirmed and idempotent payments/shipper custody are fully gated.

**This policy is intended for prospective NEW Shopify paid orders and founder-verified actual postage records only.** Historical Shopify shipping revenue postings and payout calculations are deliberately preserved for audit and reviewed as legacy. Manual sales and eBay shipping remain unchanged.
