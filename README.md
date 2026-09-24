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
- `TCG_SHOPIFY_ACCESS_TOKEN=<Admin API token>`
- `TCG_SHOPIFY_CLIENT_SECRET=<app client secret>`
- `TCG_SHOPIFY_API_VERSION=2026-07`
- `TCG_SHOPIFY_PUBLISH_ENABLED=false`

The shop domain must be the canonical `*.myshopify.com` domain, not a custom storefront domain or URL with a scheme/path.

Initial webhook topics expected by Drop Rate are:

- `orders/paid`
- `orders/cancelled`
- `refunds/create`
- `app/uninstalled`

Webhook deliveries are acknowledged and deduplicated, but order/refund business processing is deliberately not enabled in this foundation phase. Publishing and order processing are separate guarded phases.
