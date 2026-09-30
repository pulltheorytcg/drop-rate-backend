# Published Shopify raw-card pooling — Phase B

## Purpose

Phase A consolidated duplicate raw-card products while they were still Shopify DRAFT.
After the remaining catalogue was published, some interchangeable physical copies were
left split across multiple ACTIVE Shopify products.

Phase B reconciles those already-published duplicates without changing physical
ownership, acquisition cost, condition, language, location, sale history or settlement
history.

## Eligibility

A published group can be consolidated only when every physical member is:

- a raw CARD (never graded);
- APPROVED and FOR_SALE;
- identity-confirmed;
- populated with language, condition, acquisition cost, storage location and store price;
- non-test Shopify inventory;
- PUBLISHED and unreserved;
- not part of an active marketplace listing/reservation;
- on the same Shopify location and publication;
- on the same canonical card + language + condition;
- at one identical Store Price that matches the last Shopify-synced price.

Anything ambiguous fails closed.

## Anchor selection

The reconciler prefers an existing pooled Shopify product when one already exists.
Otherwise it selects a deterministic existing published product. Historical products are
never deleted.

The anchor keeps its Shopify product identity, becomes the single public offer and receives:

- deterministic `shopify-pool:<fingerprint>` listing key;
- deterministic `DRP-...` SKU;
- quantity equal to eligible physical members;
- pooled-safe customer copy with no single Inventory ID;
- copy-group metadata that no longer points at archived sibling products.

Redundant current products are set to quantity zero and ARCHIVED. This preserves historical
Shopify order references while removing duplicate sellable storefront entries.

## Backend truth

Every physical Inventory ID keeps its own `tcg.shopify_inventory_links` row. Eligible
members are repointed to the anchor variant with deterministic allocation priority.
`sync_state` remains PUBLISHED.

Shopify remains the customer-facing quantity projection. Postgres remains the ownership
and financial source of truth.

## Order/refund behaviour

No new allocation path is introduced. Existing Shopify webhook logic already:

1. locks eligible physical links behind the purchased variant;
2. selects by allocation priority;
3. records the exact Inventory ID and owner;
4. moves only the selected item to SOLD;
5. records deterministic financial ledger entries.

Refunded/restocked physical cards move to INSPECTION and their links ARCHIVED rather than
silently becoming sellable again.

## Failure controls

- PLATFORM_ADMIN-only plan/apply routes;
- per-pool advisory lock;
- live Shopify read-back before mutation;
- product/variant/inventory-item identity verification;
- tracked inventory + DENY oversell verification;
- Shopify quantity parity check against eligible physical stock;
- product publication verification;
- remote compensation if database commit fails;
- version-checked database updates;
- audit event for every physical link migration;
- no mutation of SOLD/ARCHIVED historical links.

## Production launch finding — 30 September 2026

Brand Redesign checkout testing exposed that Uta OP13-023 still had sellable copies split
between an existing pooled product and separate individual Shopify products.

The strict production audit found 19 eligible published duplicate groups. These must be
reconciled before Brand Redesign becomes MAIN, followed by Shopify/Postgres parity and
customer-path read-back.
