# Shopify pooled raw publication

## Scope

This flow publishes Shopify products that have already been safely consolidated by
Phase A raw pooling.

It does not create pools, change ownership, infer language, merge graded cards, or publish
legacy single-item drafts.

## Publication contract

A pooled offer is publishable only when every linked physical member is still:

- APPROVED
- FOR_SALE
- identity-confirmed
- language-resolved
- raw/ungraded
- priced
- assigned to storage
- unreserved

All links in one pool must agree on:

- pooled listing key
- Shopify product/variant/inventory-item/location/publication IDs
- pooled SKU
- synced/store price

Allocation priorities must remain contiguous from 1..N.

## Remote Shopify verification

Before activation the pooled anchor must still be DRAFT and must have:

- at least one image
- all required browse collections
- exactly one variant
- the expected pooled variant/inventory IDs
- pooled SKU
- exact shared price
- inventory tracking enabled
- inventoryPolicy=DENY
- available quantity equal to the number of physical pool members

## Apply order

1. Reload and validate the pool from Postgres.
2. Verify the remote DRAFT product.
3. Set Shopify product ACTIVE.
4. Publish to the configured Online Store publication.
5. Re-fetch and verify ACTIVE/publication/variant state.
6. In one DB transaction, lock the pool again, verify membership/readiness and mark every
   physical member link PUBLISHED.
7. Audit each physical link mutation.

If any step after remote activation fails, the product is forced back to DRAFT. This
deliberately prefers temporary underselling over Shopify/ownership drift.

## Ownership

Publication changes only Shopify visibility and each link's sync state. Physical Inventory
ID, Owner ID, acquisition cost, storage location, condition and settlement attribution stay
in Supabase.

## Endpoints

Platform-admin only:

- GET /api/v1/shopify/pooling/pooled-publish-plan
- POST /api/v1/shopify/pooling/pooled-publish-apply

The apply payload accepts max_groups from 1 to 100.
