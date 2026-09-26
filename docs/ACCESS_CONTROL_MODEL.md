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
