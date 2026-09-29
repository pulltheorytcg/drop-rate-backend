# Shopify linked-draft launch reconciliation

## Purpose

This is a controlled, one-off reconciliation path for physical inventory that already has
an existing Shopify product and a `tcg.shopify_inventory_links` row in `DRAFT` state.
It exists to close legacy catalogue bootstrap gaps without creating replacement products
or weakening Drop Rate's normal publication policy.

Normal ongoing publishing continues to use the standard inventory, media registry and
Shopify pipeline.

## Safety model

The reconciliation is disabled and dry-run only by default. It:

- targets one explicit import batch and excludes test-mode links;
- requires `FOR_SALE` inventory in a launchable state;
- excludes pooled, reserved and sold inventory;
- reuses exact Collectr import identity checks;
- preserves existing language and otherwise requires an explicit per-game/per-set language map;
- never applies one blanket language to the whole batch;
- can use a positive Collectr `Price Override` only when the backend store price is missing;
- reuses the existing physical-photo/condition policy, so low-risk raw Near Mint cards can
  proceed while graded/high-value cards still require their existing physical verification;
- requires the already-linked Shopify product and variant to exist, with the exact SKU,
  positive stock, at least one remote image and required browse collections;
- updates the existing Shopify product copy/SEO/tags/metafields from corrected backend data;
- never creates a Shopify product;
- activates/publishes Shopify before marking the link `PUBLISHED`;
- returns the Shopify product to `DRAFT` on a final database publication-state failure;
- records the link publication transition in `tcg.audit_events`.

Existing remote Shopify imagery is accepted only as a presence gate for this legacy,
already-linked reconciliation. The worker does not invent `media_assets`, alter rights
metadata or weaken the standard media resolver.

## Configuration

All switches are server-side environment variables:

- `TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_ENABLED` — default `false`
- `TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_APPLY` — default `false`
- `TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_BATCH_ID` — required when enabled
- `TCG_SHOPIFY_LINKED_DRAFT_LANGUAGE_MAP_JSON` — required per-set language evidence
- `TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_LIMIT` — default 500

Language-map keys are case-insensitive `Game|Set Name` values, for example:

```json
{
  "Pokemon|Phantasmal Flames": "English",
  "Pokemon|Ninja Spinner": "Japanese"
}
```

An existing inventory language always wins over the map. Any unmapped null-language row
is blocked as `LANGUAGE_UNRESOLVED`.

## Run sequence

1. Deploy the code with reconciliation disabled.
2. Configure the batch ID and verified language map.
3. Enable reconciliation with `APPLY=false`; inspect the logged READY/BLOCKED totals.
4. Resolve unexpected blockers.
5. Set `APPLY=true` and redeploy once.
6. Verify Shopify ACTIVE counts, publication membership, inventory/link state and order-path
   reconciliation.
7. Disable reconciliation again and redeploy.

The job is bounded and idempotent. It reports explicit result/blocker codes so a rerun can
continue from the remaining drafts rather than recreating products.
