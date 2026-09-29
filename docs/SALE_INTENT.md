# Inventory Sale Intent

_Last updated: 29 September 2026_

## Purpose

`sale_intent` answers one narrow question for each physical Inventory ID:

**Is this exact physical item currently intended to be sellable, or is the owner keeping it in a personal collection?**

It is separate from the inventory workflow `status`. Status describes operational state such as DRAFT, APPROVED, RESERVED or SOLD. Sale intent describes the owner's commercial intent.

The physical item, owner, acquisition cost, identity and audit history remain unchanged when sale intent changes.

## Allowed states

### `FOR_SALE`

This is the default and current production state for existing inventory.

It means the item may participate in listing/readiness/allocation flows if every other deterministic gate also passes. It does **not** mean the item is automatically published.

Returning an item to `FOR_SALE`:

- makes it eligible to be listed again;
- does not reactivate a Shopify, eBay or marketplace listing automatically;
- still requires normal readiness/publication checks;
- does not bypass condition, identity, media, pricing or channel rules.

### `PERSONAL_COLLECTION`

This means the owner is keeping the exact physical item rather than offering it for sale.

Moving an item to `PERSONAL_COLLECTION` is locally authoritative immediately. Drop Rate then attempts to withdraw the exact Inventory ID from external selling channels.

Effects:

- active marketplace membership rows are paused;
- Shopify inventory/product exposure is withdrawn through the existing guarded channel path;
- eBay exposure is withdrawn through the existing guarded channel path where applicable;
- allocation/sale paths must independently require `FOR_SALE`;
- the item remains in inventory and keeps its owner, cost, identity and history;
- a later return to `FOR_SALE` requires explicit re-listing.

A channel withdrawal failure does not silently revert the local sale intent. The API returns a structured 502 retry-required error with per-channel withdrawal details, so the physical item remains protected locally while the external discrepancy is repaired.

## State restrictions

A `SOLD` item cannot move to or from Personal Collection.

A `RESERVED` item cannot change sale intent until the reservation is released.

The database also prevents a `PERSONAL_COLLECTION` item from being in `RESERVED` or `SOLD` state. This is defence in depth in addition to application-level checks.

## Ownership and permissions

Sale intent never transfers ownership.

The change endpoint resolves the authenticated user's owner scope and updates only an inventory item belonging to that resolved owner. Existing row-level security and owner membership boundaries remain authoritative.

A founder cannot use sale intent to take or alter another owner's physical inventory.

## Concurrency and idempotency

Changes use the inventory row's optimistic `version`.

If the item changed since the client last read it, the request fails with a conflict instead of overwriting newer state.

Sending the already-current sale intent is idempotent.

## Audit

Every actual sale-intent change writes a `SALE_INTENT_CHANGED` audit event containing the previous/new sale intent, status and version.

Marketplace membership pauses also write their existing marketplace audit event.

Historical audit records are not rewritten when an item later returns to `FOR_SALE`.

## Current production state

As verified on 29 September 2026:

- 509 physical inventory items total;
- 509 are `FOR_SALE`;
- 0 are `PERSONAL_COLLECTION`.

This is a factual snapshot, not a rule. Future items may use either allowed state.

## Tests and failure paths

The contract must continue to cover:

- invalid sale-intent values rejected;
- SOLD items rejected;
- RESERVED items rejected;
- stale versions rejected;
- owner-scoped item lookup;
- idempotent no-op when already in the requested state;
- Personal Collection prevents sale allocation;
- external withdrawal failure is surfaced rather than hidden;
- returning to `FOR_SALE` does not silently republish a listing;
- sale-intent changes remain auditable.
