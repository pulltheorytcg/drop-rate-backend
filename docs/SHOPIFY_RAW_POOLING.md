# Shopify raw inventory pooling

_Status: Phase A implementation in progress. This document defines the safe migration contract._

## Goal

Drop Rate must present interchangeable raw cards as normal Shopify quantity while preserving exact physical inventory ownership in Supabase.

Example customer-facing offer:

- Igaram EB04-021
- Japanese
- Near Mint
- Quantity: 2

Backend truth remains two distinct physical items, each with its own Inventory ID, owner, acquisition cost, location and audit history.

## Core rule

Shopify quantity is a projection of eligible physical inventory. It is never the source of truth for ownership.

For a pooled raw offer, several tcg.shopify_inventory_links rows may point to the same Shopify product, variant and Shopify inventory item. Each row still maps one exact tcg.inventory_items.id to its owner.

The existing Shopify order processor already selects physical units deterministically from all published links behind a variant by allocation priority. This preserves:

Shopify line -> exact Inventory ID -> Owner -> Cost -> Settlement

## Pool identity

Phase A pools only raw cards that match exactly on canonical catalogue_id, language and condition.

The deterministic pool fingerprint does not include owner or acquisition cost. This allows future multi-owner pooling while preserving those values on the physical inventory rows.

Graded inventory is never automatically pooled by this flow.

## Phase A: DRAFT-only raw consolidation

Phase A deliberately touches only Shopify-linked products whose link state is DRAFT. This avoids an in-flight customer-order race while the physical links are repointed.

A group is eligible only when every physical member:

- is a CARD
- is raw/ungraded
- is APPROVED
- is FOR_SALE
- has confirmed identity
- has language and condition
- has acquisition cost
- has a registered storage location
- has store price
- has a non-test Shopify link in DRAFT
- has no active order reservation
- has no active marketplace-listing membership/reservation

All members must share the same store price, Shopify location and publication.

### Apply sequence

For each eligible group:

1. Acquire a per-pool PostgreSQL advisory lock.
2. Re-read and validate the pool.
3. Read every Shopify draft and verify it is still a single-variant DRAFT product.
4. Choose the oldest linked item as the deterministic pool anchor.
5. Give the anchor variant a stable pool SKU and inventoryPolicy=DENY.
6. Set anchor Shopify quantity to the number of physical members.
7. Set redundant draft quantities to zero and archive those draft products.
8. Re-read and lock the Supabase rows.
9. Fail if membership/readiness changed.
10. Repoint every physical shopify_inventory_links row to the anchor product/variant/inventory item.
11. Assign deterministic allocation priorities.
12. Record an audit event for every physical link mutation.

If Shopify changes succeed but the Supabase commit fails, the flow performs best-effort compensation to restore the previous anchor SKU/quantity and the secondary draft products.

The flow is resumable and reports an already-pooled group without duplicating work.

## Why no new table is required for Phase A

tcg.shopify_inventory_links already supports the required physical mapping:

- inventory_id is unique
- Shopify product/variant IDs are not unique
- listing_key plus allocation_priority is unique
- the order webhook already allocates multiple physical links behind one Shopify variant

This means Phase A can pool quantity without weakening the existing ownership or settlement chain.

tcg.sellable_listings, tcg.listing_inventory_members and tcg.inventory_reservations remain the broader marketplace-listing foundation. They are not silently populated by this migration.

## Ongoing pool-safe operations

Pooling changes the semantics of a Shopify inventory quantity from "this one physical item" to "remaining eligible physical members". Existing single-item maintenance paths therefore follow these rules:

- **Return/refund:** a returned physical item moves to INSPECTION and its exact link is archived, but Shopify quantity is reconciled to the count of remaining unreserved PUBLISHED links behind that variant. A unique one-copy variant naturally reconciles to zero.
- **Withdraw from sale / Personal Collection:** withdrawing one member reconciles quantity to the remaining eligible sibling links. A published pool stays ACTIVE while quantity remains above zero; the final member still produces quantity zero and DRAFT, preserving the old fail-closed behaviour.
- **Cancellation before payment:** the existing Shopify reservation path releases the exact reserved Inventory IDs and does not force the shared variant to zero. Shopify remains responsible for its native cancellation inventory restoration.
- **Price changes:** the legacy owner/item price-sync endpoint explicitly excludes shopify-pool links. Shared offer prices require a dedicated offer-level price sync so one physical owner/member cannot silently overwrite a pooled variant price.

## Published duplicates: Phase B

Already-published duplicate products are not migrated by Phase A.

Phase B requires a legacy-variant drain/alias strategy so a Shopify orders/create event that was generated immediately before migration can still resolve its old variant ID. Published products must not be repointed in a way that creates even a short attribution gap.

That work belongs in a separate PR and separate production test.

## Canonical Shopify product + offer variants

The target storefront model is one canonical Shopify product per exact card printing, with variants for sellable offers, for example:

- English · Near Mint — quantity N
- Japanese · Near Mint — quantity N
- PSA 9 · English — quantity 1
- PSA 10 · Japanese — quantity 1

Raw variants can be backed by several physical Inventory IDs. Unique/graded variants remain backed by one exact physical item.

This canonical multi-offer consolidation is a later step after Phase A raw pooling is proven. It must also handle variant-specific slab media correctly.

## Brand Redesign theme

Drop Rate — Brand Redesign is the storefront launch theme.

Its existing buy-button implementation already behaves correctly for this model:

- tracked quantity <= 1: quantity selector is hidden
- tracked quantity > 1: Shopify's native quantity selector is shown
- native Shopify cart and checkout remain unchanged

Do not port the old exact-copy quantity suppression from the experimental Grouped PDP Preview theme into Brand Redesign.

## Safety / failure testing

Required before Phase A production apply:

- planner returns the expected DRAFT-only cohort
- raw cards with different language do not pool
- raw cards with different condition do not pool
- graded cards do not auto-pool
- price mismatch blocks the pool
- missing identity/cost/location blocks the pool
- concurrent apply calls serialize on the pool advisory lock
- Shopify quantity becomes exact eligible-member count
- every physical link shares the pooled variant after commit
- allocation priorities are deterministic
- duplicate webhook/order processing remains idempotent
- quantity 2 order allocates two distinct Inventory IDs
- refund/restock returns the exact allocated physical item
- simulated Supabase commit failure compensates Shopify draft state

## Current production cohort (29 September 2026)

Read-only production audit before implementation:

- 27 DRAFT raw duplicate groups
- 61 physical items in those groups
- 15 fully ready groups
- 35 fully ready physical items
- 12 groups blocked on identity/language readiness
- 0 ready candidate groups with a price mismatch

No production pooling mutation has been run yet.


## Customer-facing pooled copy

A pooled Shopify offer must never present one physical member's Inventory ID as if it identifies the whole offer.

Before a consolidated raw pool can be activated, the pooled publication path now:
- requires the draft description to match the deterministic Drop Rate card-description contract
- removes the single-copy `Inventory ID` row
- replaces the single-item wording with pooled-copy wording
- writes that corrected description while the product is still DRAFT
- re-reads Shopify and fails closed if the corrected description did not persist

Exact physical Inventory IDs remain in Supabase and in the per-member Shopify link records for deterministic allocation, ownership, refunds and settlement. They are not customer-facing pooled-offer identity.
