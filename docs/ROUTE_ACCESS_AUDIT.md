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

## Mixed routers requiring endpoint-level policy

These routers intentionally remain mixed and must not be blanket-guarded:

- `api.py`: authenticated identity + Founder HQ inventory administration
- `finance.py`: future owner-safe balance/history plus admin reconciliation/manual-sale actions
- `refunds.py`: owner-safe visibility may be allowed later; refund creation is admin-only
- `stripe_connect.py`: owner self-service onboarding/status plus admin payout approval/rejection and external webhooks
- `shopify.py`: admin configuration/probe/register plus external signed webhooks
- `ebay_sales.py`: admin seller/listing actions plus external order notifications
- `ebay_oauth.py`: admin OAuth start/configuration with provider callback handling
- `founder_onboarding.py`: admin invite creation plus invited-user preview/redeem flow

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

## Next hardening pass

Apply endpoint-level PLATFORM_ADMIN guards to the mixed routers while preserving:

- authenticated owner self-service
- provider callbacks
- verified Shopify/eBay/Stripe webhooks
- public founder-invite preview/redeem where required

No OWNER accounts should be created until this endpoint-level pass is complete.
