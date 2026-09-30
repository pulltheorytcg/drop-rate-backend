# Drop Rate — Production System Map

_Status: 30 September 2026. Plain-English Phase 2 map of the current production estate._

## Core rule

PostgreSQL/Supabase is the master source of truth for physical inventory, ownership, finance, catalogue identity and audit history. FastAPI owns deterministic business rules. Shopify owns storefront/cart/checkout/customer commerce. Railway runs backend/worker infrastructure. n8n orchestrates low-risk workflows but must not decide ownership, price, identity or finance.

## Railway services

| Service | Purpose | Current disposition |
| --- | --- | --- |
| `drop-rate-api-live` | Main FastAPI application: Founder HQ, owner-safe APIs, inventory, pricing controls, recognition, Shopify integration, orders/refunds, settlements, Stripe controls and Action Required. | KEEP — primary application service. |
| `drop-rate-api` | 30-minute operations monitor. Runs payout-scheduler heartbeat checks and Shopify↔Drop Rate order reconciliation. | KEEP — reliability service. |
| `drop-rate-payout-scheduler` | Hourly deterministic scheduler that creates payout requests only. It does not move money. | KEEP — finance control-plane service. |
| `drop-rate-n8n-e840` | n8n runtime with persistent volume. Automation foundation is intentionally dormant/limited until Phase 2 workflow discipline is satisfied. | KEEP — orchestration layer. No unversioned production workflow should be activated. |
| `shopify-reconciliation-worker` | One-shot / manually controlled reconciliation runner used to drain and verify Shopify publication backlogs. Current production has zero linked Shopify drafts. | RETAIN TEMPORARILY — document as operational migration/recovery tooling; review after launch stability. |
| `psa-cert-lookup-temp` | PSA/graded-card certificate diagnostic and lookup utility. It has also been used for exact grading-provider evidence checks. | KEEP CAPABILITY — formalise/rename later. Do not delete while graded-card cert→identity→slab-media automation is part of the roadmap. |
| `psa-fetch-batch` | Batch PSA certificate lookup utility for multiple graded cards. | KEEP CAPABILITY — formalise/consolidate later with the PSA adapter rather than treating it as disposable. |

### PSA target architecture

The useful capability is:

`PSA certificate number → exact PSA identity/grade → exact inventory match → official PSA slab image(s) → media registry → human/graded verification → Shopify`

Rules:
- certificate identity must match the physical inventory record;
- official PSA images may be used only when tied to the exact certificate;
- if PSA provides no slab scan, keep `GRADED_SLAB_MEDIA_REQUIRED` open;
- never substitute another card/slab image;
- this should ultimately be source-controlled application/provider-adapter code rather than two permanently named diagnostic services.

## Supabase/PostgreSQL — major areas

### Catalogue and physical inventory
- `catalogue_products`, `catalogue_product_profiles`, card gameplay/printing tables: canonical card/product identity.
- `inventory_items`: every physical item, owner, cost, condition/grade, language, location, price, sale intent and status.
- `storage_locations`, purchase-lot/import tables: intake and physical operations.

### Ownership and access
- `owners`, `owner_memberships`, founder/owner invitations: application permission is separate from physical ownership.
- Founder HQ is privileged; restricted owner/seller surfaces remain isolated.

### Media and recognition
- `media_assets`: physical/canonical media, provider provenance, rights, approval and Shopify file metadata.
- recognition tables: candidates, hard negatives and recognition evidence. New recognition scope remains frozen until explicitly reopened after launch.

### Shopify commerce
- `shopify_inventory_links`: physical Inventory ID → Shopify product/variant/inventory mapping, including pooled raw quantity while preserving exact ownership.
- `shopify_webhook_events`, `orders`, `order_items`, `shopify_order_item_links`: Shopify event ingestion and deterministic sale attribution.
- `shopify_shipping_profiles`: deterministic shipping data.
- Raw duplicate pooling is live; Shopify quantity is a projection, never ownership truth.

### Finance
- financial ledger, settlements, payout preferences/requests/executions and Stripe connected-account tables.
- Deterministic calculations stay in FastAPI/Postgres.
- Automatic live-money movement remains deliberately gated.

### Market data and pricing
- provider mappings, market observations/ingestion, pricing policies/snapshots.
- Historical observations are append-only.
- Provider expansion remains frozen under the storefront-first/Phase 2 launch discipline.

### Operations and audit
- `action_required_items`: human exception queue.
- `audit_events`: ownership/price/admin/settlement/refund/sync audit trail.
- `automation_events` / `automation_runs`: governed automation event/run layer.
- n8n should consume signed/idempotent events and call backend APIs, not duplicate rules.

## Shopify

- One unified UK/GBP storefront.
- Current catalogue checkpoint: 470 ACTIVE, Online Store-published products and zero product drafts.
- `Horizon` remains MAIN.
- `Drop Rate — Brand Redesign` is the launch candidate and remains unpublished until every Phase 2 launch gate passes.
- Raw identical copies can share Shopify quantity while Supabase continues tracking each exact physical owner/cost/Inventory ID.

## n8n

n8n is the nervous system, not the brain.

Allowed responsibilities:
- receive signed events;
- call FastAPI;
- deliver notifications;
- orchestrate provider/API calls;
- schedule low-risk work;
- report failures.

Not allowed:
- decide final card identity;
- alter ownership rules;
- calculate settlement truth independently;
- arbitrarily set prices;
- silently publish uncertain/high-value inventory.

Every production workflow must have exported JSON in GitHub, idempotency, an error workflow and credentials stored outside JSON.
