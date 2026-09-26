# Drop Rate access-control model

## Principle

Inventory ownership and application permission are separate concepts.

An owner record answers **who owns a physical item**.
An owner membership answers **what an authenticated user is allowed to access**.

No external seller or consignor receives Founder HQ access merely because they own inventory.

## Roles

### PLATFORM_ADMIN

Internal-only role for the platform founder and any explicitly trusted admin account.

Founder HQ access is allowed.

Intended capabilities include:
- cross-owner inventory and finance visibility
- owner assignment and ownership administration
- Shopify/eBay/Stripe integration settings
- commission and settlement controls
- payout approval/execution controls
- audit and exception views
- platform-wide analytics and pricing controls
- founder invitations

### OWNER

Restricted role for a seller, consignor or future non-admin founder account.

Founder HQ access is denied.

The future owner portal may expose only owner-scoped capabilities such as:
- own inventory/submissions
- own listing status
- own sales and settlement breakdown
- own payout history and payout preference
- narrowly permitted profile/listing requests

The OWNER role must never receive:
- other-owner inventory or financial data
- global integration configuration
- owner reassignment
- commission changes
- payout approval
- settlement adjustments
- platform audit administration
- global pricing/market-data controls

## Enforcement layers

1. Supabase Auth verifies identity.
2. FastAPI sets `tcg.user_id` for the request transaction.
3. `tcg.owner_memberships` resolves the authenticated user's owner and access role.
4. PostgreSQL RLS determines which owners are visible.
5. Existing owner-scoped policies inherit that visibility.
6. FastAPI must still apply explicit PLATFORM_ADMIN guards to privileged actions.
7. UI navigation is presentation only; hidden tabs are never treated as authorization.

## Current rollout

Phase 1 establishes:
- `PLATFORM_ADMIN`
- `OWNER`
- least-privilege default of `OWNER`
- existing founder membership migration to `PLATFORM_ADMIN`
- admin-only founder invitations
- role-aware owner visibility
- authenticated access-context API

No OWNER accounts should be invited until privileged Founder HQ routes have completed the
admin-guard audit and a separate restricted owner portal exists.

## Owner portal entry boundary

The restricted owner portal is served from `/owner` and is intentionally separate from
Founder HQ.

The first portal slice is access-only:

- it supports the same Supabase identity providers as the rest of Drop Rate
- it calls `GET /api/v1/access/me` before showing any owner workspace
- `PLATFORM_ADMIN` accounts are redirected to Founder HQ
- only `OWNER` + `OWNER_PORTAL` access context may enter the restricted portal
- unlinked authenticated users fail closed
- no inventory, finance, marketplace, pricing or admin APIs are exposed by the portal yet

Business-data modules are added only after their owner-safe API contracts and cross-owner
isolation tests are complete.

## Owner-safe read API contract

The first owner business-data contract is exposed separately under `/api/v1/owner`.

Current read-only endpoints:

- `GET /api/v1/owner/overview`
- `GET /api/v1/owner/inventory`

These endpoints require the explicit `OWNER` / `OWNER_PORTAL` guard. PLATFORM_ADMIN does not
silently pass the owner-portal guard; admin users remain in Founder HQ.

The owner inventory response uses an explicit field allowlist. It intentionally excludes:

- acquisition cost and acquisition date
- internal notes
- storage/bin locations
- purchase-lot data
- internal optimistic-lock versions
- Shopify/eBay provider IDs and error metadata
- identity-review internals
- audit/admin fields

Both SQL queries include the authenticated membership's owner ID even though RLS already applies,
providing defence in depth.

Multiple simultaneous active owner memberships fail closed with administrator review instead of
silently selecting one owner context.

## Restricted OWNER invitations

Seller/consignor onboarding uses a dedicated owner invitation flow and never reuses founder
permissions.

Rules:

- only PLATFORM_ADMIN may create or revoke an owner invite
- every owner invite is email-locked
- invite redemption uses the verified Supabase JWT email, never a client-supplied email
- redemption creates physical owner type `CONSIGNOR`
- redemption creates application access role `OWNER`
- commission is snapshotted onto the owner at onboarding; current default is 1000 bps (10%)
- an account with an existing active owner membership cannot redeem another owner invite
- invite tokens are stored only as SHA-256 hashes
- invite create/redeem/revoke actions are audit logged
- the public preview exposes name, commission rate and expiry only; it does not expose the invited email
- the onboarding destination is `/owner/join`, and successful redemption lands at `/owner`

Founder invitation redemption is also bound to the verified JWT email so a signed-in account
cannot impersonate the invited email by changing a browser payload.

## Owner finance portal contract

The restricted owner portal consumes dedicated read-only finance endpoints under
`/api/v1/owner/finance` rather than Founder HQ finance routes.

Visible owner finance concepts:

- own sales revenue and shipping revenue
- platform/payment/shipping/fulfilment deductions allocated to that owner
- Drop Rate commission and commission rate
- refunds and adjustments
- owner proceeds derived from the append-only ledger
- pending, available, reserved and paid-out balances
- order-level settlement breakdown
- reconciliation completeness
- payout history
- owner-controlled payout cadence

The portal intentionally excludes acquisition cost, cost basis, company-wide gross/net profit,
customer addresses, provider credentials, payout approval controls, reconciliation mutations and
other owners' records.

Unreconciled external fees/shipping are displayed as `Reconciling` rather than presented as
final numbers.

