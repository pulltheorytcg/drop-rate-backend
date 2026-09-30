# Drop Rate — Phase 2 System Map

_Last production review: 30 September 2026_

This is the plain-English system map required by the Phase 2 Operating Manual. It is intentionally operational rather than aspirational: it describes what is actually deployed now, what each part is for, and what should not own business decisions.

## 1. Railway production services

Production currently exposes seven Railway services. Two are temporary diagnostics already dependency-audited and staged for deletion, so the intended steady-state topology is five services.

| Service | Purpose | Normal state | Keep? |
| --- | --- | --- | --- |
| `drop-rate-api-live` | Main FastAPI application and internal web surfaces. Enforces deterministic inventory, ownership, Shopify, finance, media, recognition and security rules. | Online, 1 replica in Amsterdam, `/health/ready` healthcheck. | Yes — core application. |
| `drop-rate-api` | Internal operations monitor. Every 30 minutes checks payout-scheduler heartbeat and Shopify-vs-Drop-Rate order reconciliation. Despite the legacy name, it is not the customer API. | Cron: `*/30 * * * *`, Amsterdam. | Yes — reliability control. Rename later only if useful; no need to create a replacement service. |
| `drop-rate-payout-scheduler` | Hourly deterministic payout-request scheduler. It creates eligible payout requests only; automatic money movement remains disabled. | Cron: `0 * * * *`. | Yes — finance control plane. |
| `drop-rate-n8n-e840` | n8n orchestration runtime with persistent volume. It must trigger/move data only; it must not own pricing, ownership, identity or finance decisions. | Online, 1GB persistent volume, currently kept production-dormant for advanced workflows. | Yes, but workflow activation remains gated. |
| `shopify-reconciliation-worker` | Controlled one-shot operational worker used for the linked-DRAFT/Dragon Ball publication backlog. It is not a permanent scheduler. | Deployed, no cron. Current linked-DRAFT backlog is zero. | Keep through launch as a recovery tool; review for retirement after launch stability. |
| `psa-cert-lookup-temp` | One-off PSA/ACE/CardTrader diagnostic function used during 29 Sep media/cert investigations. | Sleeping. No inbound dependencies. | Delete. Removal is staged; Railway requires dashboard 2FA to commit. |
| `psa-fetch-batch` | One-off PSA batch diagnostic function used during 29 Sep slab investigation. | Sleeping. No inbound dependencies. | Delete. Removal is staged; Railway requires dashboard 2FA to commit. |

### Railway rule going forward

No new service is allowed merely because a one-off operation is convenient. Prefer:
1. the existing FastAPI application;
2. the existing operations monitor or scheduler when the cadence genuinely belongs there;
3. a version-controlled script executed through an established deployment path;
4. n8n only for orchestration after its activation gate.

Any genuinely new Railway service must be documented in `BUILD_STATUS.md` in the same PR that introduces it.

## 2. Supabase / Postgres

Supabase is the master source of truth. Production currently has **68 base tables in the `tcg` schema**. The table count is not itself the problem; the important test is whether each area has one clear responsibility.

### Inventory, catalogue and ownership
Core tables include `owners`, `owner_memberships`, `inventory_items`, `catalogue_products`, `card_printings`, `sealed_product_details`, `storage_locations`, `purchase_lots`, `sellable_listings` and `listing_inventory_members`.

Purpose: know exactly what every physical item is, who owns it, where it is, its condition/grade/language, and whether it may be sold.

### Shopify, orders, refunds and finance
Core tables include `shopify_inventory_links`, `shopify_webhook_events`, `orders`, `order_items`, `shopify_order_item_links`, `order_item_reconciliations`, `refund_events`, `financial_ledger_entries`, `fulfilment_cost_components` and `shopify_shipping_profiles`.

Purpose: preserve the chain:

`Shopify order → order item → physical Inventory ID → owner → fees/commission → net proceeds → settlement`.

### Market data and pricing
Core tables include `market_observations`, `market_ingestion_runs`, `market_source_mappings`, `provider_catalogue_mappings`, `pricing_policies` and `pricing_snapshots`.

Purpose: preserve raw historical evidence and deterministic pricing outputs. Provider expansion remains frozen until the current storefront milestone is reopened.

### Media, identity and imports
Core tables include `media_assets`, `identity_verification_events`, `condition_review_events`, `import_batches`, `import_candidates` and `import_enrichment_items`.

Purpose: separate canonical identity from evidence about each physical item and fail closed where exact media/language/printing cannot be proved.

### Recognition and learning data
Core tables include `recognition_runs`, `recognition_candidates`, `recognition_feedback`, `recognition_reference_fingerprints`, `recognition_learning_examples`, `recognition_hard_negatives` and `recognition_model_versions`.

Purpose: identify cards and learn only from governed/human-confirmed outcomes. Recognition may suggest; it must not silently overwrite canonical truth.

### Owners, access and payouts
Core tables include `owners`, `owner_memberships`, invites, `stripe_connected_accounts`, `payout_preferences`, `payout_requests`, `payout_scheduler_runs` and `stripe_payout_executions`.

Purpose: separate permission from ownership, keep owner data isolated, and make payout state auditable. Automatic live money movement remains gated.

### Automation, exceptions and audit
Core tables include `automation_events`, `automation_runs`, `action_required_items`, `audit_events`, `marketplace_audit_events` and `request_receipts`.

Purpose: durable event/idempotency/audit state. n8n consumes or triggers work around this state; n8n is not the state store.

### eBay and taxonomy
eBay connection/link/webhook tables preserve already-built cross-channel groundwork. Taxonomy tables hold structured classification. New eBay/cross-channel scope remains frozen.

## 3. Shopify

Shopify owns:
- the customer storefront;
- product presentation and Online Store publication;
- native cart and checkout;
- customer accounts and order history;
- Search & Discovery facets;
- order/webhook source events.

Shopify does **not** decide physical ownership, cost basis, settlement allocation, canonical card identity or final deterministic backend rules.

Current launch state:
- **470 ACTIVE / Online Store-published products**;
- **0 DRAFT products**;
- **492 physical published inventory links**, with interchangeable raw duplicates correctly represented as Shopify quantity;
- `Horizon` remains MAIN;
- `Drop Rate — Brand Redesign` remains UNPUBLISHED until the Phase 2 publish gate is complete.

## 4. GitHub

`pulltheorytcg/drop-rate-backend` is the version-controlled source for:
- FastAPI/backend code;
- database migrations;
- Shopify Brand Redesign theme source;
- tests;
- operating/runbook documentation;
- future n8n workflow JSON exports.

A production behavior that exists only in a dashboard/UI is operational drift and must be brought back into source control.

## 5. n8n

The n8n runtime exists, but advanced automation is intentionally gated.

Current important branches:
- PR #236 — DR-01 approved-inventory → Shopify orchestration, including a version-controlled workflow JSON. **Open/unmerged/unactivated.**
- PR #215 — governed CRO/SEO experiment foundation. **Open/unmerged.**
- PR #216 — content-machine foundation. **Open/unmerged.**

Phase 2 activation order:
1. one low-risk notification workflow;
2. n8n error workflow;
3. prove signed ingress, idempotent retries and correct delivery;
4. export JSON and commit it;
5. only then consider higher-value workflows such as Merchant Center diagnostics;
6. deterministic decisions remain in FastAPI/Postgres.

## 6. External providers

Current provider integrations/evidence include Shopify, Stripe, CardTrader, TCGGraph and existing eBay groundwork. Provider terms/rate limits remain explicit constraints.

No provider may silently determine:
- physical language;
- ownership;
- condition/grade;
- canonical exact-print identity when evidence is ambiguous;
- final price;
- settlement outcome.

## 7. Complexity decisions from the Phase 2 review

Keep:
- one main FastAPI service;
- one operations-monitor cron;
- one payout-scheduler cron;
- one n8n runtime;
- the existing reconciliation worker through launch as a recovery mechanism.

Remove:
- the two temporary PSA diagnostic services once Railway dashboard 2FA applies the already-staged deletion.

Do not add:
- a custom Google Shopping feed service;
- a second automation database;
- a second pricing/business-rule layer in n8n;
- temporary production services for one-off diagnostics.

Review after launch stability:
- whether `shopify-reconciliation-worker` can be retired once the storefront has proven stable and no backlog-recovery need remains.
