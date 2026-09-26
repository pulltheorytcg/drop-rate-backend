# Stripe Connect payout architecture

## Scope

Stripe is the payout/KYC rail for Drop Rate sellers and consignors. It is **not** the
source of truth for inventory ownership, sale allocation, commissions, fees, refunds,
or settlement amounts.

Customer checkout remains on Shopify. Supabase/PostgreSQL remains the master source of
truth. FastAPI makes every deterministic settlement decision before Stripe is allowed
to move money.

## Phase 1 decision

Drop Rate uses Stripe Connect **Express** connected accounts and requests only the
`transfers` capability.

Why:

- sellers/consignors need Stripe-hosted identity and bank-account onboarding;
- Drop Rate needs connected-account readiness and payout control;
- connected accounts do not need to accept customer card payments because Shopify is
  the customer checkout;
- requesting only `transfers` minimises verification scope.

Stripe documents that a connected account needs the `transfers` capability to receive
funds transferred by a platform:
https://docs.stripe.com/connect/account-capabilities

Stripe-hosted onboarding is used with `eventually_due` collection so verification is
collected up front and payout interruptions are less likely:
https://docs.stripe.com/connect/hosted-onboarding

### Important Express implication

The connected-account Dashboard type is an architectural choice. Stripe documents that
the dashboard type chosen at account creation is immutable; changing it requires a new
connected account. No live connected account is created by this phase while the live
creation gate is disabled.

## Deterministic flow

```text
Shopify/eBay sale
  -> exact physical Inventory ID
  -> Owner
  -> financial ledger entries
  -> fee/postage/refund reconciliation
  -> available owner balance
  -> payout request
  -> founder approval
  -> PREPARED Stripe payout execution
  -> [Phase 2 only] platform funding verification
  -> Stripe transfer to connected balance
  -> Stripe payout to seller bank
  -> webhook confirmation
  -> paid settlement / ledger entry
```

A payout cannot be approved while:

- Stripe account is missing or restricted;
- `transfers` is not ACTIVE;
- payouts are disabled;
- Stripe verification is currently/past due;
- Shopify/eBay settlement costs remain unreconciled; or
- refunds/adjustments have reduced the owner's ledger below reserved payouts.

## Idempotency

- Stripe account creation uses one deterministic idempotency key per Drop Rate owner.
- Each payout request can have at most one Stripe execution record.
- Each execution has an immutable deterministic idempotency key.
- Stripe webhook event IDs are unique and raw payloads are not retained.
- Failed webhook processing can retry; completed duplicate events no-op.
- Replays of the same Stripe event ID with different bytes are rejected.

## Audit and sensitive data

Drop Rate stores Stripe account IDs, capability/readiness flags, requirement field
names, transfer/payout IDs, and audit state.

Drop Rate does **not** store seller bank-account numbers, identity documents, card
details, or Stripe secret keys in PostgreSQL.

Stripe secret keys and webhook signing secrets belong only in Railway secrets.

## Production kill switches

- `TCG_STRIPE_CONNECT_LIVE_ENABLED=false` prevents live connected-account creation.
- `TCG_STRIPE_PAYOUT_EXECUTION_ENABLED=false` prevents automatic money movement.

Phase 1 intentionally has no endpoint that creates a Stripe Transfer or Payout.

## Funding constraint before Phase 2

Because the original customer payment is collected by Shopify rather than the Drop Rate
Stripe platform, the sale proceeds do not automatically appear in the Stripe platform
balance.

Before enabling payout execution we must confirm a permitted, operational funding path
for the platform Stripe balance. Stripe states that Connect transfers move funds from
the platform balance to connected accounts and that transfers must be used with
permitted charges, top-ups, or fees:
https://docs.stripe.com/connect/account-capabilities

No implementation may assume Shopify funds are automatically available in Stripe.

## Phase 1 test matrix

- incomplete onboarding / KYC;
- payouts disabled;
- transfers pending/inactive;
- valid READY account;
- duplicate Stripe webhook;
- failed webhook retry;
- payload mismatch replay;
- payout approval retry/idempotency;
- multi-owner ledger isolation;
- refund reducing available balance after payout request;
- unreconciled Shopify/eBay fee or postage blocker;
- immutable owner/amount/connected-account execution mapping;
- production live-connect and payout-execution kill switches.

## Phase 2 entrance criteria

Do not enable real money movement until all are true:

1. Phase 1 has production health and regression coverage.
2. Stripe live credentials are stored in Railway, never GitHub/chat.
3. Connect webhook signature verification is live-tested.
4. At least one test-mode connected account reaches READY.
5. Funding source for the Stripe platform balance is confirmed and permitted.
6. Transfer + bank payout + failure + reversal flows are tested end to end.
7. Refund-after-payout policy and reserve/negative-balance handling are documented.
8. Founder approval/exception handling is production verified.
