# Shopify Order Reconciliation

_Last updated: 29 September 2026_

## Purpose

Shopify webhooks are the primary event path, but webhooks are not treated as the only
proof that an order exists. A periodic reconciliation worker compares Shopify's own
recent order list with `tcg.orders` so a missed `orders/create` or `orders/paid`
delivery cannot remain invisible indefinitely.

This is a detection and exception-control system. It is deliberately **not** an
automatic ledger-repair system.

## Architecture

Every 30 minutes the operations monitor runs two independent checks in sequence:

1. payout scheduler heartbeat;
2. Shopify order reconciliation.

The Shopify check:

1. retrieves all Shopify orders created in the previous seven days using cursor
   pagination;
2. retrieves all `tcg.orders` rows with `source='SHOPIFY'` in the same time window;
3. compares numeric Shopify order references in both directions;
4. records mismatches through the existing Founder HQ Action Required queue;
5. resolves an open reconciliation alert only when the same order reference is present
   on both sides in a later successful scan.

If Shopify fails, pagination is incomplete or the response is malformed, the run fails
closed before reconciliation writes. Existing alerts are left untouched.

## Mismatch classes

### Shopify only

`SHOPIFY_ORDER_MISSING_IN_DROP_RATE` / CRITICAL

This means Shopify returned an order but Drop Rate has no matching `tcg.orders` row.
The operator should inspect webhook history and payment/cancellation state. The job does
not create an order, inventory allocation, ledger entry or settlement.

### Drop Rate only

`DROP_RATE_ORDER_MISSING_IN_SHOPIFY` / HIGH

This means a recent Drop Rate Shopify order was not returned by Shopify for the same
completed scan window. The operator should inspect Shopify API visibility/order state
before changing any inventory or finance record.

## Privacy

The reconciliation query intentionally requests only:

- Shopify order GID
- order name/number
- created timestamp
- cancelled timestamp
- display financial status

It does not request or persist customer name, email, phone, billing address or shipping
address.

## Safety boundaries

- Postgres remains the source of truth for Drop Rate ownership and finance.
- Reconciliation never reconstructs a webhook payload.
- Reconciliation never changes ownership, inventory status, order items, ledger rows,
  settlement rows or payout rows.
- Alerts are created only for active FOUNDER owners through a `SECURITY DEFINER`
  function executable only by `tcg_api`.
- Repeated mismatches are idempotent by founder + dedupe key.
- A manually dismissed mismatch reopens if the mismatch is still present on the next
  completed scan.
- The scan has a hard pagination ceiling and fails rather than treating a partial remote
  result as authoritative.

## Known production proof case

Shopify order reference `8488414282075` exists in Shopify but is absent from
`tcg.orders`. It is a cancelled founder test order, so no customer sale was lost, but
it proves that webhook delivery alone is not sufficient monitoring. The reconciliation
worker must surface this existing mismatch; it must not fabricate a replacement sale.
