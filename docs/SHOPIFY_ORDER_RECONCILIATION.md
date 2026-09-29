# Shopify Order Reconciliation

_Last updated: 29 September 2026_

## Purpose

Shopify webhooks are the primary event path, but webhooks are not treated as the only
proof that an order exists. A periodic reconciliation worker compares Shopify's own
recent order list with `tcg.orders` and Shopify webhook history so a missed order event
cannot remain invisible indefinitely.

This is a detection and exception-control system. It is deliberately **not** an
automatic ledger-repair system.

## Architecture

Every 30 minutes the operations monitor runs two independent checks in sequence:

1. payout scheduler heartbeat;
2. Shopify order reconciliation.

The Shopify check:

1. retrieves all Shopify orders created in the previous 30 days using cursor pagination;
2. retrieves all `tcg.orders` rows with `source='SHOPIFY'` in the same time window;
3. compares numeric Shopify order references in both directions;
4. for Shopify-only orders, checks processed `orders/create` webhook coverage and
   Shopify's current financial status;
5. records genuine anomalies through the existing Founder HQ Action Required queue;
6. resolves an open reconciliation alert only when that reference is later demonstrated
   healthy by the same completed scan.

The default lookback is 30 days. Code allows an explicitly supplied lookback from one
hour up to 60 days, but the production worker uses the default.

If Shopify fails, pagination is incomplete or the response is malformed, the run fails
closed before reconciliation writes. Existing alerts are left untouched.

## Why Shopify-only does not always mean missing sale

An unpaid Shopify order is intentionally not yet a completed `tcg.orders` sale. If an
unpaid Shopify-only order has a successfully processed `orders/create` webhook, Drop
Rate has evidence that the pending order was seen by the reservation path. That state is
classified as **expected pending** rather than an anomaly.

The worker does not assume that every remote-only order should have a ledger entry.

## Mismatch classes

### Paid-like Shopify order missing from Drop Rate

`SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE` / CRITICAL

A Shopify-only order whose current financial state is `PAID`, `PARTIALLY_PAID`,
`PARTIALLY_REFUNDED` or `REFUNDED` is expected to have reached Drop Rate's paid-order
path. The operator must inspect Shopify payment/webhook history. Reconciliation does not
create the missing order or any ledger/settlement records automatically.

### Shopify webhook coverage gap

`SHOPIFY_ORDER_WEBHOOK_GAP` / HIGH

A Shopify-only order that is not paid-like and has no successfully processed
`orders/create` webhook is evidence that Drop Rate's webhook coverage was incomplete.
The operator should inspect webhook history and pending-order reservation state.

### Drop Rate order missing from Shopify scan

`DROP_RATE_ORDER_MISSING_IN_SHOPIFY` / HIGH

A recent `tcg.orders` Shopify row that is not returned by Shopify for the same completed
scan window needs investigation before any inventory or finance record is changed.

## Privacy

The reconciliation Shopify query intentionally requests only:

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
- A manually dismissed mismatch reopens if the anomaly is still present on the next
  completed scan.
- The scan has a hard pagination ceiling and fails rather than treating a partial remote
  result as authoritative.

## Known production proof case

Shopify order reference `8488414282075` / `#1001` exists in Shopify but is absent from
`tcg.orders`. It is a cancelled founder test order and its current financial state is
PENDING, so it is **not** evidence of a lost paid customer sale. Production webhook
history shows the cancellation event but no successfully processed `orders/create`
event for that order reference. Under the final classifier it is therefore expected to
surface as the HIGH-severity `SHOPIFY_ORDER_WEBHOOK_GAP` proof case.

The correct response is to investigate delivery coverage, not fabricate a replacement
sale.


## RLS-safe local order read

The production monitor connects as the restricted `tcg_api` role without a browser user
session. A direct SELECT from `tcg.orders` is therefore subject to the same owner-scoped
RLS policy used by interactive application traffic. In a cron context that policy can
legitimately expose zero rows even when Shopify orders exist.

Reconciliation must not weaken that RLS boundary. Instead it reads only the fields needed
for comparison through `tcg.shopify_orders_for_reconciliation(window_start)`, a
`SECURITY DEFINER`, `STABLE` function with execute permission granted only to
`tcg_api`. The function returns only:

- internal order ID
- Shopify source reference
- order number
- Drop Rate status
- placed timestamp

It does not return owner, customer, address, payment, ledger or settlement data.

This change fixes a production false positive where Shopify #1002 /
`8488435581275` was incorrectly classified as Shopify-only even though its
`tcg.orders` row exists.

## Production monitor deployment

Reconciliation is the second step of the internal Railway operations monitor on the
repurposed `drop-rate-api` service. The cron schedule is every 30 minutes. The service
has the Shopify Admin credentials required for the read-only remote scan and the database
connection required for deterministic persistence.

Production verification already proved the persistence/security boundary using real
Shopify order `8488414282075` / `#1001`: exactly two HIGH founder alerts were opened,
one for each active founder, and no consignor alert was created. No commerce or finance
records were reconstructed.

Production completion was verified on the **2026-09-29 02:30 UTC** scheduled
execution. The final combined monitor returned heartbeat healthy, then reconciliation
reported two Shopify orders, one local Drop Rate order, one correct match, one remote-only
anomaly and zero local-only anomalies. The run resolved the two false #1002 CRITICAL
alerts created before the RLS-safe read fix and retained the two expected #1001 HIGH
founder webhook-gap alerts. Both monitor steps exited 0.

This completes the reconciliation release gate. Recovery remains detection-first: the
worker does not fabricate missing orders or mutate inventory, ownership, ledger,
settlement or payout history.


### Migration history alignment

Production Supabase recorded the RLS-safe order-read migration as
`20260929021203_shopify_reconciliation_rls_read`. The repository filename is aligned to
that already-applied version. No database history row was deleted, rewritten or re-applied,
and the live `tcg.shopify_orders_for_reconciliation(timestamptz)` definition was verified
against the repository SQL before the rename.
