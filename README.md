# Drop Rate Backend

Private FastAPI backend and founder dashboard for Drop Rate's inventory system.

## Inventory workflow

- Search and filter owner-scoped inventory.
- Edit acquisition, condition, grading, location, pricing and audit details.
- Allocate one binder or set purchase total across multiple cards atomically.
- Review missing information in the Action Required queue.
- Approve complete stock records through a dedicated validation endpoint.
- Record every inventory change through the database audit trigger.

Unknown acquisition costs remain `null`; the dashboard never converts them to zero. Bulk allocations use integer minor units and must reconcile exactly to the purchase total.

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/me`
- `GET /api/v1/inventory`
- `GET /api/v1/inventory/readiness`
- `PATCH /api/v1/inventory/{inventory_id}`
- `POST /api/v1/inventory/{inventory_id}/approve`
- `POST /api/v1/inventory/bulk-cost`
- `POST /api/v1/automation/inventory-review`

Protected routes require a valid Supabase bearer token. The verified user ID is applied to the transaction with `SET LOCAL`, and PostgreSQL row-level security determines which owner and inventory rows are visible.


## Market data

Market integrations are modular. Production pricing remains disabled until provider evidence has been validated.

Official eBay UK active-listing access uses the eBay Browse API with an Application access token (OAuth client-credentials grant). Configure these server-side variables:

- `TCG_EBAY_CLIENT_ID`
- `TCG_EBAY_CLIENT_SECRET`
- `TCG_EBAY_MARKETPLACE_ID=EBAY_GB`

When official eBay credentials are present, the backend prefers the official Browse adapter over the legacy Parse-backed eBay diagnostic adapter. Browse results are always normalized as `ACTIVE` evidence only; the system never converts active listings into sold observations.

Historical eBay sold data is a separate capability. Drop Rate will only treat eBay sales-history results as `SOLD` evidence when access is provided through an official/permitted historical-sales source such as eBay Marketplace Insights. Until then, Cardmarket remains the UK/EU valuation anchor and eBay Browse is used for current supply/asking-price context.


## Shopify foundation

Shopify is the storefront; Drop Rate remains authoritative for canonical card identity, physical inventory, ownership, cost, pricing and settlement.

The current Shopify integration is intentionally non-publishing. It provides:

- a read-only GraphQL Admin API connection probe;
- verified HTTPS webhook intake at `/api/v1/shopify/webhooks`;
- HMAC-SHA256 verification against the raw request body before JSON is trusted;
- delivery-level idempotency using `X-Shopify-Webhook-Id`;
- a metadata-only webhook delivery ledger (raw customer/payment payloads are not stored);
- founder-visible integration status in Settings;
- a publishing feature flag that defaults to disabled.

Configure these variables only in the server/Railway environment. Do not place them in browser code or commit them to Git:

- `TCG_SHOPIFY_SHOP_DOMAIN=<store>.myshopify.com`
- `TCG_SHOPIFY_CLIENT_ID=<app client ID>`
- `TCG_SHOPIFY_CLIENT_SECRET=<app client secret>`
- `TCG_SHOPIFY_API_VERSION=2026-07`
- `TCG_SHOPIFY_WEBHOOK_ENDPOINT=https://drop-rate-api-live-production.up.railway.app/api/v1/shopify/webhooks`
- `TCG_SHOPIFY_PUBLISH_ENABLED=false`

The shop domain must be the canonical `*.myshopify.com` domain, not a custom storefront domain or URL with a scheme/path. Drop Rate exchanges the Client ID + Client Secret for a short-lived Shopify Admin API token and refreshes it automatically before expiry; access tokens are not configured manually.

Initial webhook topics expected by Drop Rate are:

- `orders/paid`
- `orders/cancelled`
- `refunds/create`
- `app/uninstalled`

Webhook deliveries are acknowledged and deduplicated, but order/refund business processing is deliberately not enabled in this foundation phase. Publishing and order processing are separate guarded phases.


Webhook registration is founder-controlled and idempotent through `POST /api/v1/shopify/webhooks/register`. It first verifies the configured shop through the Admin API, refuses conflicting or duplicate topic registrations, creates only missing subscriptions, and re-reads Shopify to verify exactly one canonical subscription for each required topic. Provider-side partial creation is safe to retry because exact existing subscriptions are treated as already complete.


## Controlled Shopify single-item milestone test

Bulk Shopify publishing remains disabled by default. The first product/order milestone is exercised through a separate single-item test gate.

Additional server variables:

- `TCG_SHOPIFY_LOCATION_GID=gid://shopify/Location/...`
- `TCG_SHOPIFY_PUBLICATION_GID=gid://shopify/Publication/...`
- `TCG_SHOPIFY_TEST_PUBLISH_ENABLED=true`
- keep `TCG_SHOPIFY_PUBLISH_ENABLED=false`

An inventory item is eligible for the test only after it is physically identity-confirmed, has a known acquisition cost, an active registered storage location, a store price, and status `APPROVED`.

Test sync is one physical Inventory ID at a time. The Shopify product uses a deterministic handle and a `drop_rate.inventory_id` metafield so retries can recover an externally-created product without matching by title. The variant SKU is the Drop Rate Inventory Code, inventory tracking is enabled, overselling is denied, and quantity begins at exactly one.

Shopify paid-order processing resolves the Shopify variant back to `tcg.shopify_inventory_links`, row-locks eligible links, validates product/SKU/price/state, creates the Drop Rate `SHOPIFY` order and physical order item, snapshots acquisition cost, marks the exact Inventory ID `SOLD`, and records the external line-item allocation. Duplicate deliveries and duplicate semantic orders are idempotent.

Sale and shipping revenue from Shopify begin as `PENDING`. Platform/payment fees are not guessed from the order webhook and must be added from a verified settlement source before net proceeds are considered final.

Refunds are linked back to the exact physical order item. A Shopify restock is accepted only when the physical item sale value is fully refunded; returned inventory moves to `INSPECTION`, never directly back to `APPROVED`.


## Marketplace sellable listings and reservations

Drop Rate separates the canonical card, the customer-facing sellable listing, and each exact physical Inventory ID.

A `sellable_listing` is the storefront concept. Multiple physical copies can join one listing only when they are genuinely equivalent. In the first pooling version, automatic pooling is restricted to raw cards with the same canonical catalogue identity, confirmed language, and condition. Graded cards and non-card stock default to `UNIQUE`. A raw card can also be forced unique for high-value or copy-specific stock.

Each physical copy joins through `listing_inventory_members`, which preserves its owner, owner context, minimum acceptable sale price, allocation priority, and eligibility start time. The customer-facing listing price is independent from owner cost basis. A copy is excluded from available quantity whenever the listing price is below that copy's minimum sale price.

Allocation is deterministic: allocation priority, then oldest eligible membership, then Inventory ID. Reservation code uses row locking with `FOR UPDATE SKIP LOCKED` so concurrent orders cannot reserve the same physical item. The exact Inventory ID moves `APPROVED → RESERVED`; release or expiry returns it to `APPROVED`, while consumption moves it to `SOLD`. Reserved inventory is protected by a database trigger from generic edits, cost changes, location moves, identity changes, or manual approval.

Reservations snapshot the physical owner, acquisition cost, listing price, owner minimum price, allocation priority, and inventory version. Reservation requests are idempotent by source/reference/line/allocation index, and one physical Inventory ID can have at most one active reservation.

The old single-item Shopify test path and the pooled listing path are mutually exclusive for the same Inventory ID. This prevents one physical card from being simultaneously exposed through two independent inventory-control paths.

The current implementation keeps Shopify bulk publishing disabled. The listing/reservation engine is the future allocation foundation; Shopify migration to listing-level quantities should happen only after the reservation engine has been verified with controlled test inventory.


Marketplace mutations use a dedicated immutable `tcg.marketplace_audit_events` ledger rather than weakening the existing privileged global audit trigger. The application role can insert/read its authorized audit events but cannot update or delete them.

Language is now part of inventory approval readiness. Physical stock cannot become APPROVED, and therefore cannot join a pooled sellable listing, until its language is explicitly recorded. This is required to prevent visually similar but non-equivalent language variants from sharing storefront quantity.


## Card language policy

Language is a first-class identity/pricing attribute. For physical cards, language must be explicit before approval or sellable listing.

Imports accept structured language fields such as `English`/`EN` and `Japanese`/`JP`. They also deterministically parse explicit language suffixes in card titles, including `(EN)`, `English`, `[JP]`, and `(Japanese)`. The parsed language tag is removed from the canonical card name so the canonical name remains clean.

If a structured language field conflicts with an explicit title language, the row enters REVIEW rather than choosing one silently. If a card has no explicit language, it enters REVIEW rather than being guessed as English.

Customer-facing Shopify titles always include a visible language code such as `EN` or `JP`, while the structured `language` field remains the source of truth for pricing, identity matching and allocation.

The existing imported portfolio had 96 physical units with explicit JP/Japanese title markers. Those can be promoted safely to structured Japanese language; the remaining untagged cards are deliberately not auto-labelled English.
