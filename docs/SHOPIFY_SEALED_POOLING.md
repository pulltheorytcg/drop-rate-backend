# Drop Rate — Shopify sealed-copy pooling (OP17 pilot)

## Objective
Two seller-held identical Japanese One Piece `OP-17` sealed **single booster packs**, both individually recorded and APPROVED at £10, must become **one sellable Shopify variant with available quantity 2**. Never merge or delete the physical `tcg.inventory_items` rows. Backend ownership, cost history and seller net proceeds remain per copy.

This is distinct from the already completed **Seller Hub display projection** (PR #580), which shows a single card with `×2` but does *not* alter Shopify publication.

## Grounded identities and safeguards

- Original Shopify anchor: product `10788230791515`, variant `54295232119131`, inventory item `56430021902683`. Keep the existing handle and approved single pack image.
- Duplicate: product `10788230857051`, variant `54295233134939`, inventory item `56430022918491`. Retire with available stock 0 and status `ARCHIVED`, never delete.
- Both share one verified canonical sealed single-pack identity, exact Japanese language, SEAL=SEALED, seller, £10 price, Shopify location/publication, verified gallery and approved seller-held consignment source records. Their acquisition costs are unknown and must remain NULL.
- The pooled listing's SKU is a stable deterministic `DRP-S-...` derived from canonical product, language, seal, packaging and variant; listing key begins `shopify-pool:sealed:`. Never present the original Inventory ID as an attribute of the entire public offer.
- Must not pool Booster BOX versus PACK, English versus Japanese, graded/unsealed product, cross-owner stock without explicit multi-owner validation, price differences, reservations, uncertain identity or external eBay listings.

## Critical checkout edge case

Shopify can send a delayed `orders/create` or `orders/paid` webhook for the **retired variant**, even after its product disappears from the storefront. Migration `20261010195000_shopify_variant_pool_aliases.sql` adds an immutable legacy-variant and **original-SKU** alias tied to the **original physical copy**, original product/SKU and new pooled variant. Both original variants need an alias: the retired sibling changes variant and SKU, while the surviving Shopify anchor retains its variant ID but receives a new pooled SKU. It is not a sellable stock record. The order resolver checks that alias only when the primary variant has no current links and verifies the pooled link identity. Any such event allocates the same original Inventory ID (or safely rejects if already sold); refunds continue following the recorded order-item link. The alias is owner-scoped, service-readable for pre-authenticated webhooks and insertable only by authorised platform operations.

## Publish sequence (approved, operator-controlled)

1. Verify current DB versions, owner and seller-held approval, two remote product images/collections/price/status/quantity, both `DENY` and tracked, no committed Shopify quantity, no local reservations, no processed or unprocessed variant order links, and no relevant recent Shopify orders. Record snapshot + rollback values.
2. **Install and test** the legacy alias migration and deploy the new webhook resolver **before the cutover**. Smoke-test production readiness and exact order-lookup behaviour.
3. Set **both remote Shopify products DRAFT first** (short, explicit maintenance window). Read back no sales/stock drift, then query recent Shopify orders again. If either copy was sold or reserved, abort and restore from the verified snapshot instead of guessing. Do not use `CONTINUE` inventory policy.
4. While DRAFT, replace the anchor's single-copy description with `pooled_sealed_description_html`; preserve the Drop Rate title, tags, approved exact Japanese pack image and category/collection rules. Update the anchor variant SKU to deterministic pool SKU, keep price £10, tracked/oversell DENY and preserved shipping weight. Remove obsolete anchor `drop_rate.inventory_id` metafield. Set `copy_group_size=2`, `copy_handles=[anchor handle]`, `copy_group_truncated=true`; add a stable pooled identity metafield. The archived product may keep historical metadata.
5. Set the duplicate's remote available stock to **0** using CAS `changeFromQuantity=1`, archive the duplicate. Set the anchor available stock to **2** from 1 using CAS while DRAFT. Read back that the anchor is still DRAFT with exact SKU/price/qty2/media/tags/weight, and the sibling is ARCHIVED with qty0.
6. In **one PostgreSQL transaction** guarded by exact IDs, link and inventory versions, ownership, identity, price and status, absence of reservations/orders, shared location/publication, and the same deterministic pool key: insert the two immutable **old-variant/original-SKU aliases**, update both original `shopify_inventory_links` records to the anchor product/variant/inventory-item with distinct priorities 1/2 and identical pooled SKU/listing key. Audit each link's old/new state and the alias creation. **Do not update either physical inventory row.**
7. After DB commit, re-read both physical links and the unreserved eligible copy count. Only then set the anchor ACTIVE/published and verify the Online Store publication, £10, Qty2, SKU, approved image, shipping/collections, archived sibling Qty0 and both linked owner records. Confirm no `PENDING` or `FAILED` webhook messages related to the retired variant.
8. Record final evidence (versioned links, audit row count, source-of-truth owner/valuation fingerprint and Shopify screenshots). Retain the legacy alias for historic reconciliation, never delete it. Close the OP17 issue only when *actual Shopify* is one active Qty2 offer. Do not turn on Whatnot import until this is finished.

## Failure and rollback

- Pre-cutover failure: keep DB unchanged; restore both original Shopify products ACTIVE, original SKUs/copy descriptions and available quantity one, with a remote read-back. If an order/reservation appears, **do not blindly restore quantities**: process/reconcile it first.
- Post-cutover but before anchor activation: keep both remote products unavailable and create Action Required if remote confirmation fails; DB retains truthful pool allocations. Correct remotely or perform a guarded reverse migration after checking no orders/aliases used. Never allow two active Qty2+Qty1 offers.
- Delayed legacy webhook: use immutable alias and existing idempotent Shopify order pipeline to select the corresponding physical copy; never recreate a sellable duplicate.
- Any drift in owner, canonical identity, packaging, media, price, variant, stock, committed counts, publication or link versions: fail closed and notify admin rather than auto-correct financial data.

## Testing

- Pure deterministic eligibility, branding and exact remote snapshot verification.
- Disposable PostgreSQL migration replay, uniqueness, immutable alias, SELECT-before-actor, INSERT admin-only and no inventory changes.
- Unit simulation for original legacy order SKU/product/variant routing with null acquisition cost under exact approved consignment.
- Existing real Shopify order, created/paid/cancel/refund/idempotency tests and seller inventory/tests must all remain passing.
- Production readback from Shopify/Supabase before marking complete.

**Scope:** existing permitted Shopify API, Supabase, FastAPI. No new market data provider, n8n workflow, app installation, payment transfer, storefront theme publication or recognition expansion.
