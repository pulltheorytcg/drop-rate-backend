# Shopify Order Reconciliation

_Last updated: 29 September 2026_

## Purpose

Shopify webhooks are the primary event path, but they are not treated as the only proof
that an order exists. A periodic reconciliation worker compares Shopify's own recent
order list with `tcg.orders` and webhook history so missed order events cannot remain
invisible indefinitely.

This is a detection and exception-control system. It is deliberately **not** an automatic
ledger-repair system.

## Architecture

Every 30 minutes the operations monitor runs two checks in sequence:

1. payout scheduler heartbeat;
2. Shopify order reconciliation.

The Shopify check:

1. retrieves Shopify orders created in the previous 30 days using cursor pagination;
2. retrieves `tcg.orders` rows with `source='SHOPIFY'` in the same time window;
3. compares numeric Shopify order references in both directions;
4. for Shopify-only unpaid orders, checks whether `orders/create` was successfully processed;
5. records genuine anomalies through Founder HQ Action Required;
6. resolves an open alert only when later evidence shows that discrepancy is healthy.

If Shopify fails, pagination is incomplete or the response is malformed, the run fails
closed before reconciliation writes. Existing alerts are left untouched.

## Status-aware mismatch classes

### Paid Shopify order missing from Drop Rate

`SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE` / CRITICAL

Shopify reports a paid-like financial state but Drop Rate has no matching `tcg.orders`
row. This is high risk because ownership, ledger or settlement work could be absent.
The worker never reconstructs the order automatically.

### Shopify webhook coverage gap

`SHOPIFY_ORDER_WEBHOOK_GAP` / HIGH

An unpaid Shopify order has no matching `tcg.orders` row and no successfully processed
`orders/create` webhook. This catches the class of failure demonstrated by Shopify order
`8488414282075` / #1001.

Unpaid Shopify orders with a successfully processed `orders/create` webhook are expected
to remain outside `tcg.orders` while payment is pending; they are not treated as false
missing-order alerts.

### Drop Rate order missing from Shopify

`DROP_RATE_ORDER_MISSING_IN_SHOPIFY` / HIGH

A recent Drop Rate Shopify order was not returned by Shopify for the same completed scan
window. The operator should inspect Shopify API visibility and order state before changing
inventory or finance records.

## Privacy

The Shopify query intentionally requests only:

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
- The lookback is 30 days by default and cannot exceed 60 days.

## Known production proof case

Shopify order `8488414282075` / #1001 exists in Shopify, is cancelled with a PENDING
financial status, and is absent from `tcg.orders`. Production webhook history currently
shows the cancellation event but no successfully processed `orders/create` event. The
reconciler should therefore surface a HIGH webhook-coverage alert rather than fabricate
a sale.

Shopify #1002 is present in both systems and is the healthy comparison case.
