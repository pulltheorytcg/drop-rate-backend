# eBay parity and reconciliation

## Current boundary

Drop Rate already has a substantial eBay integration:

- production OAuth and encrypted seller refresh-token handling;
- business policy and merchant-location setup;
- official Inventory API item/offer publication;
- fixed-price GTC single-card listings;
- front/back physical-media requirement;
- eBay ORDER_CONFIRMATION notification subscription and signature verification;
- physical Inventory ID → owner attribution;
- Shopify/eBay cross-channel withdrawal for reservation/sale;
- return-to-inspection protections.

The live seller connection is READY, but no live eBay inventory link/order has yet been proven in production.

## Read-only reconciliation

`GET /api/v1/ebay/reconciliation?limit=50`

is PLATFORM_ADMIN-only and diagnostic. It reads owner-scoped local links and compares them with eBay's current Inventory API offer + inventory item state.

It does **not**:

- publish or withdraw offers;
- change eBay quantity/price;
- change local inventory/link state;
- create orders;
- move money;
- mark discrepancies resolved.

Each item returns explicit discrepancy codes, including:

- missing/mismatched remote offer/listing;
- marketplace/SKU/price mismatch;
- live local link not remotely PUBLISHED;
- live local link with remote quantity other than one;
- withdrawn/sold local link still PUBLISHED;
- physical SOLD/RESERVED while remote offer remains PUBLISHED;
- local LIVE link whose physical inventory is no longer APPROVED/FOR_SALE;
- provider read errors.

Provider errors are item-level evidence, never silently counted as healthy.

## Why this comes before automation

Inventory API listings created via the Inventory API must continue to be managed through the API. A cross-channel business therefore needs read-back reconciliation rather than assuming a prior write succeeded.

The endpoint is the foundation for a later scheduled reconciliation workflow and Action Required alerts, but no schedule or automatic mutation is activated by this PR.

## Remaining eBay parity work

After the Phase 3 launch-stability gate permits activation:

1. controlled real listing + purchase proof;
2. shipping-fulfilment creation/tracking;
3. eBay-originated cancellation/return/refund handling;
4. eBay fees/finance ingestion into auditable owner settlement;
5. scheduled reconciliation + Action Required;
6. governed price/listing updates;
7. sealed-product channel support;
8. broader multi-channel adapters built on the same stock-protection contract.
