# Shopify pooled offers

## Purpose

Drop Rate must preserve exact physical inventory ownership while presenting interchangeable
raw cards to customers as normal Shopify quantities.

The storefront model is therefore:

- raw cards that are the same canonical card, language and condition may share one Shopify
  product/variant and expose quantity > 1;
- graded cards and other copy-specific inventory remain exact physical offers with quantity 1;
- Supabase remains the source of truth for every physical Inventory ID, owner, cost, location
  and sale allocation;
- Shopify is the customer-facing quantity projection, not the ownership ledger.

This design does not require Shopify Plus.

## Pool identity

Pooling reuses `marketplace_listings.listing_shape` rather than defining a second
equivalence algorithm.

For raw cards, the pool fingerprint includes:

- canonical catalogue ID
- product type
- pooling mode
- language
- condition

Graded cards are always `UNIQUE` and include the physical Inventory ID in the fingerprint.

Missing raw language or condition fails closed.

## Shopify projection

Every physical item continues to have one `tcg.shopify_inventory_links` row.

For a pooled offer, member links intentionally share:

- `listing_key = offer:<fingerprint>`
- Shopify product GID
- Shopify variant GID
- Shopify inventory-item GID
- Shopify location GID
- pooled offer SKU
- synced storefront unit price

Each physical link retains:

- exact Inventory ID
- Owner ID
- allocation priority
- link state
- reservation/order references
- audit timestamps

`allocation_priority` is unique inside a `listing_key` and keeps sale allocation
deterministic.

## Order allocation

The existing Shopify webhook allocator already selects physical units behind one Shopify
variant in this order:

1. allocation priority
2. linked timestamp
3. Inventory ID

It locks candidate rows and fails closed when quantity exceeds eligible physical stock.
The selected physical Inventory IDs become the order items and drive owner attribution,
cost basis, settlement and refunds.

## Quantity lifecycle

Pooled quantity is the count projected to Shopify, but physical ownership never moves into
Shopify.

Pool-aware lifecycle rules:

- adding one eligible physical member: Shopify available quantity +1;
- removing one eligible member: Shopify available quantity -1;
- Shopify checkout/order creation: Shopify decrements quantity natively, while Drop Rate
  reserves exact physical members;
- paid order: selected physical members become SOLD and their links become SOLD;
- cancellation before payment: exact physical reservations return to APPROVED and Shopify
  handles the order cancellation inventory restoration;
- returned/refunded pooled unit: Shopify's restock is counteracted by -1 because the
  physical card moves to INSPECTION, not directly back to sellable stock;
- exact-copy legacy listings retain the existing quantity-zero + draft behavior.

Inventory deltas use Shopify's idempotent `inventoryAdjustQuantities` mutation so a
single pool member can change without overwriting concurrent checkout adjustments.

## Conversion safety

Current legacy links are not modified by the planning code.

`build_shopify_offer_plan` is read-only and:

- chooses an existing PUBLISHED Shopify product as the anchor when possible;
- otherwise chooses the deterministic earliest linked product;
- blocks raw copies with missing language/condition;
- blocks pooled groups with mixed or missing store prices;
- preserves unique graded inventory as one-copy offers;
- lists duplicate Shopify products that may be retired only after the shared offer is
  remotely verified.

The existing linked-draft reconciliation worker must remain APPLY=false while pooled-offer
conversion is being prepared. Publishing hundreds of legacy one-copy drafts before pooling
would create unnecessary storefront churn.

## Production baseline — 29 September 2026

Read-only production audit of currently linked launchable card inventory:

- 457 raw linked units
- 34 duplicate raw offer groups / 75 physical cards
- 22 groups immediately poolable under strict language/condition/price rules
- 49 physical cards in those ready pools
- 27 duplicate Shopify products removable after verified consolidation
- 12 duplicate groups blocked solely by missing language
- 7 graded linked units remain unique

No pool conversion has been applied yet.

## Required tests before APPLY

1. identical raw copies become one pool and quantity matches member count;
2. language and condition differences never pool;
3. graded copies never pool;
4. missing language fails closed;
5. mixed member prices require an explicit shared offer price;
6. PUBLISHED anchor is preferred over DRAFT duplicate products;
7. two owners can share one pool without losing owner IDs;
8. quantity-2 order allocates two different physical Inventory IDs;
9. duplicate webhook delivery does not allocate twice;
10. withdrawal decrements one pooled unit only;
11. refund/return removes only the returned physical unit from available pooled stock;
12. legacy exact-copy withdrawal/refund behavior remains unchanged;
13. Shopify quantity and backend eligible-unit reconciliation agree after each mutation.


## One-shot conversion worker

Legacy one-product-per-physical-card links are consolidated by the standalone runner:

`python scripts/run_shopify_pooled_offer_conversion.py`

Run it from the backend working directory. It does not import or start FastAPI and is
therefore not tied to the API container lifespan.

Environment controls:

- `TCG_SHOPIFY_POOLED_OFFER_CONVERSION_ENABLED=false` by default.
- `TCG_SHOPIFY_POOLED_OFFER_CONVERSION_APPLY=false` by default.
- `TCG_SHOPIFY_POOLED_OFFER_LANGUAGE_MAP_JSON` may contain only explicit verified
  `game|set -> language` mappings. Missing language otherwise remains blocked.
- `TCG_SHOPIFY_POOLED_OFFER_CONVERSION_LIMIT=100` caps pooled offers per run.

The worker always performs a read-only discovery pass first. APPLY preparation is run only
for the physical members of selected ready duplicate pools, so singleton inventory and
blocked pools are not silently approved or identity-confirmed.

### Per-pool APPLY sequence

1. Re-run core identity/language/price/physical-policy preparation for selected members.
2. Rebuild the fingerprint and fail if the group changed.
3. Force every legacy Shopify product in the pool to DRAFT.
4. Set each old Shopify inventory item to zero while those products are offline.
5. Convert the deterministic anchor variant to the pooled SKU/price with tracking enabled
   and inventoryPolicy=DENY. Do not write an acquisition cost to the shared variant.
6. In one Postgres transaction, lock every physical member and verify it remains APPROVED,
   FOR_SALE and unreserved, then repoint all link rows to the anchor product/variant while
   preserving Inventory ID and Owner ID.
7. Store the previous live intent as PUBLISHED or DRAFT on every pooled link. A remote
   failure after this point can therefore be recovered deterministically.
8. Set the anchor Shopify inventory quantity to the physical member count and verify it
   while the anchor is still DRAFT.
9. If the pool was previously live, activate and publish the anchor and verify publication.

Duplicate Shopify products are retained as DRAFT with zero stock during the initial
migration. They are not deleted, preserving a reversible recovery path and historical
evidence.

### Failure model

The sequence intentionally prefers underselling over overselling.

- Failure before database repoint: legacy links remain authoritative; products may be
  temporarily DRAFT/zero and the same run can retry.
- Failure after database repoint but before Shopify reactivation: pooled links preserve
  the intended PUBLISHED state while the remote product remains offline; retry detects the
  already-pooled links, reconciles quantity and restores publication.
- A database repoint is transactional and cannot partially move only some physical member
  links.
- A pooled refund/return counteracts Shopify restock by an idempotent -1 delta because the
  physical card enters INSPECTION rather than becoming immediately sellable.

The result is emitted as a single machine-readable
`POOLED_OFFER_CONVERSION_RESULT=<json>` line for Railway logs.
