# Stripe Connect payout architecture

## Scope

Stripe is the payout/KYC rail for Drop Rate sellers and consignors. It is **not** the
source of truth for inventory ownership, sale allocation, commissions, fees, refunds,
or settlement amounts.

Customer checkout remains on Shopify. Supabase/PostgreSQL remains the master source of
truth. FastAPI makes every deterministic settlement decision before Stripe is allowed
to move money.

## Phase 1 decision

Drop Rate uses Stripe Connect **Accounts v2** for all new connected-account creation.
Each seller/consignor is created with:

- the `recipient` configuration;
- `configuration.recipient.capabilities.stripe_balance.stripe_transfers.requested=true`;
- Express Dashboard access;
- platform-owned fee and loss responsibilities required by Stripe for Express;
- GBP / GB defaults.

This is a payout-only relationship. Shopify remains the customer checkout and the
connected account is not the Merchant of Record, so Drop Rate deliberately does not
request `card_payments`.

Stripe now recommends Accounts v2 (`/v2/core/accounts`) for new Connect integrations.
The v2 `recipient` configuration is specifically intended for accounts that receive
platform transfers, and `stripe_balance.stripe_transfers` replaces the v1
`transfers` capability:
https://docs.stripe.com/connect/accounts-v2
https://docs.stripe.com/api/v2/core/accounts/create

Some downstream Connect surfaces still use v1 endpoints. Stripe documents that v2
Account IDs are interoperable with most v1 APIs, which lets Drop Rate use the v1 Account
view for readiness and the v1 Account Links API for Stripe-hosted onboarding:
https://docs.stripe.com/connect/accounts-v2
https://docs.stripe.com/connect/hosted-onboarding

Stripe-hosted onboarding uses `eventually_due` collection so verification is collected
up front and payout interruptions are less likely.

### Important Express implication

Express access is an architectural and liability choice. Stripe requires both
`fees_collector=application` and `losses_collector=application` when the v2 Account
uses the Express Dashboard. This means Drop Rate is responsible for those connected
account fee/loss obligations under Stripe's Connect model. Do not change this silently.

No live connected account is created while the live creation gate is disabled.

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
- the recipient transfer capability is not ACTIVE (surfaced through the compatible
  v1 Account view as `transfers`);
- payouts are disabled;
- Stripe verification is currently/past due;
- Shopify/eBay settlement costs remain unreconciled; or
- refunds/adjustments have reduced the owner's ledger below reserved payouts.

## Idempotency

- Accounts v2 recipient creation uses one deterministic idempotency key per Drop Rate owner.
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

## Phase 2 sandbox transfer verification

The first Phase 2 slice is intentionally test-mode only. It adds Stripe client primitives
for platform balance inspection, Connect transfers, transfer reversals and funding-charge
refunds, plus a separate sandbox harness.

The harness is gated by both:

- `TCG_STRIPE_SANDBOX_TRANSFER_SELFTEST=true`
- `TCG_STRIPE_SANDBOX_RECIPIENT_ACCOUNT_ID=acct_...`

It refuses to run unless the platform uses an `sk_test_` key, live Connect remains
disabled, production payout execution remains disabled, and the recipient reports both an
ACTIVE transfers capability and payouts enabled.

The verification path is:

`£100 sandbox platform funding → £90 Connect transfer → duplicate transfer replay →
£90 transfer reversal → duplicate reversal replay → funding refund`

The £100 funding transaction is only a Stripe sandbox mechanism for creating available
platform balance. It does **not** model Drop Rate customer checkout; Shopify remains the
customer payment rail. The business entitlement remains the deterministic PostgreSQL
ledger calculation already verified separately as `£100 sale - £10 commission = £90
owner proceeds`.

The transfer self-test is not part of the production payout API. It remains off until a
test recipient has completed Stripe-hosted onboarding. Cleanup always attempts to reverse
a successful transfer before refunding the sandbox platform funding so the test cannot
silently strand a negative platform balance.

Production payout execution remains locked until the full test transfer, connected-account
bank payout, webhook, failure and refund-after-payout policy are verified.

## Owner payout preferences

Owner payout cadence is controlled by Drop Rate, not by Stripe. This keeps payout
eligibility, ownership, available balance and audit decisions in PostgreSQL/FastAPI while
Stripe remains the execution rail.

Supported preferences:

- `MANUAL`
- `DAILY`
- `WEEKLY` with a chosen weekday
- `FORTNIGHTLY` with a chosen weekday and deterministic 14-day anchor
- `MONTHLY` with a chosen day of month; shorter months clamp to their final day

All schedules use `Europe/London` and currently preview the next 09:00 local payout cycle.
A schedule means "eligible to be queued" rather than a guaranteed bank-arrival time. Funds
must still be available, Stripe Connect must be READY, transfer capability must be ACTIVE,
and every existing payout guard remains in force.

The default is `MANUAL`. Saving a schedule does not enable automatic money movement.
Production execution remains controlled by the separate payout execution kill-switch.

