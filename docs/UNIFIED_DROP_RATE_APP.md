# Unified Drop Rate app

Requested scope, 2 October 2026: one app for sellers and the three founders
(Sunny, Eamon and Riaz), with simpler navigation and the existing working tools.
This is an explicitly requested Phase 3 change. Whatnot remains planned.

## Implemented

- `/app` is the common login. The server's verified role selects Founder HQ or
  Seller Hub; both retain the same tab-scoped authentication session.
- Founder permission requires an explicit roster entry matching the active
  membership, active founder owner and one of three unique founder slots.
  Signup, user metadata and a PLATFORM_ADMIN role alone cannot grant access.
  Existing verified founders are bootstrapped; operator enrollment fills the
  third slot only after matching the verified account. No invitation is sent.
- Founders retain all original inventory, scanner, finance, payout, review,
  settings and operational tools. Accounts adds read-only cross-account inventory,
  channel, sales and payout oversight. Own-inventory mutations stay owner-bound.
- Five primary destinations per role. Less frequent tools remain under More;
  existing deep links and unsaved forms are preserved.
- Seller Channels includes unlisted inventory and per-item sync controls. The
  server binds every request to the signed-in seller and checks version, approval,
  sale intent, publishing gates and the existing deterministic listing readiness.
  Shopify/eBay credentials and publication plans are never returned to sellers.
- eBay can use an explicit shared store connection independently of stock owner.
  The new backend-only order function locks and records a mixed-owner basket
  atomically, preserves each seller's commission triggers, allocates shipping in
  pennies, and deduplicates replayed orders. Concurrent item publishing is locked.
- The Expo app is named Drop Rate and opens `/app`. Signing identifiers are retained.

## Deployment and acceptance

Apply both migrations before this backend is deployed. The founder roster is
operator-controlled with no browser or backend write grants. Enrollment and
roster changes are audited. Do not add emails or auth IDs to source control.

`TCG_EBAY_SHARED_STORE_OWNER_ID` explicitly identifies the company store connection;
it must never be a seller-supplied parameter. Missing or disconnected shared-store
authorization fails closed. Shared mode uses the bound connection's encrypted token and policies, ignoring
legacy global overrides so a different token cannot select the wrong store.

`TCG_SHOPIFY_SELLER_SYNC_ENABLED` and `TCG_EBAY_SELLER_SYNC_ENABLED` default to false.
They also require the corresponding existing publish gate. Keep disabled until
database allocation checks and approved-item channel acceptance pass. This change
does not automatically publish inventory. Whatnot shows Planned.

Acceptance must cover one approved unit per enabled channel, duplicate clicks,
stale versions, a rejected personal-collection item, sale on one channel removing
availability on the other, correct owner proceeds, refund and payout reconciliation.
Use approved test stock and provider test/sandbox flows where supported; never
fabricate a genuine paid order or payout in production.

Local verification: full backend suite, founder UI route/unsaved-form tests,
out-of-order account responses and logout cleanup, mobile typecheck/lint/unit tests,
and Android/iOS/web JavaScript exports. A bundle export is not a signed installer.

Native release still requires an Expo project, Apple/Android signing and physical
device checks for camera, uploads, downloads, background/reconnect and OAuth return.
No App Store, Play Store or TestFlight release is claimed by this change.

## Verified database rollout

Both migrations were applied on 2 October 2026. The three slots are Sunny, Riaz
and Eamon. Database authorization returned true for enrolled founders and false
for the seller account. Browser roles cannot read the roster or execute the order
recorder; the API role cannot enroll founders. Direct role-switch testing was not
available through the connector, so RLS policies were inspected and HTTP guards
were verified in the automated suite.

`tests/sql/shared_ebay_order_rollback.sql` passed against the deployed schema:
mixed owners, exact shipping, commission allocation, inventory changes, replay
idempotency and conflict rollback. Every fixture, ledger row, audit entry and
outbox event was rolled back. No genuine order or payout was created.

The security advisor reported the intended deny-all founder roster (RLS without
a public policy) and an existing disabled leaked-password protection setting.
See https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection
for that existing Auth setting; it was not changed by this rollout.
