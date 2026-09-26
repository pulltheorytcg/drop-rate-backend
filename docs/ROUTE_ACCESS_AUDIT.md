# Route access audit

## Purpose

Founder HQ is an internal control plane. OWNER accounts must never inherit access merely
because they own inventory. This audit classifies routes before external seller/consignor
accounts are enabled.

## PLATFORM_ADMIN-only routers

The following routers are currently restricted at FastAPI include-router level:

- pricing / imported benchmark / eBay sold pricing / pricing preview
- market ingestion, mappings, discovery, provider probes and smoke tests
- marketplace listing administration
- imports and import-review
- inventory intake, intelligence, market values and state administration
- identity review and condition review
- Shopify publishing pipeline and Shopify readiness
- purchase lots
- storage locations

These routes contain global business controls, publication actions, operational review
queues or cross-owner administration and are not part of the future owner portal.

## Mixed routers and endpoint-level policy

The mixed-router pass now enforces these boundaries:

- `api.py`: owner-scoped inventory reads remain authenticated; inventory mutations, approvals, cost allocation, purchase lots and inventory-review automation are PLATFORM_ADMIN-only.
- `finance.py`: owner-scoped summary/sales/settlements/payout history and payout request/cancel remain available to the linked owner; fee/postage reconciliation and manual sales are PLATFORM_ADMIN-only.
- `refunds.py`: owner-scoped refund visibility remains authenticated; refund creation is PLATFORM_ADMIN-only.
- `stripe_connect.py`: owner self-service onboarding/status/sync remains owner-scoped; payout queue approval/rejection uses the central PLATFORM_ADMIN guard; Stripe webhook remains externally signed.
- `shopify.py`: status/probe/webhook-registration are PLATFORM_ADMIN-only; the signed Shopify webhook remains external.
- `ebay_sales.py`: seller-status and listing publication are PLATFORM_ADMIN-only; eBay notification verification/delivery remain external.
- `ebay_oauth.py`: status/start/options/setup/configuration are PLATFORM_ADMIN-only; the state-verified provider callback remains external.
- `founder_onboarding.py`: founder invite creation is PLATFORM_ADMIN-only; invitation preview/redeem remain deliberately available to the invited flow.

## OWNER-safe target surface

The future restricted owner portal may expose only owner-scoped data/actions such as:

- access context/profile
- own inventory/submissions/listing status
- own sales, fees, commission and settlement history
- own payout history/request/cancel where allowed
- own payout preferences
- own Stripe Connect onboarding/status/sync

Every OWNER-safe API must still be enforced server-side by RLS + FastAPI authorization.
UI visibility is never treated as a security control.

## Remaining before OWNER onboarding

- build a separate owner portal shell instead of exposing Founder HQ navigation
- audit the exact fields returned by each owner-safe inventory/finance endpoint
- add cross-owner integration tests using two independent memberships
- add OWNER invitation/onboarding rather than reusing founder invitations
- require admin MFA before external seller launch

Provider callbacks and verified Shopify/eBay/Stripe webhooks remain intentionally outside user-session RBAC and retain their cryptographic/state verification boundaries.

No OWNER accounts should be created until the separate owner portal and cross-owner isolation tests are complete.
