# DR-100 — Automatic owner-visible photo exceptions for published graded stock

**7 November 2026, rollout gated by CI and production verification.**

## 1. What is being built
An independent, non-destructive **hourly audit** of the existing Shopify sync pipeline. Every already-APPROVED, FOR_SALE and non-test PUBLISHED graded physical inventory item is checked for a commercial-use, first-party, exact-inventory photo of the slab FRONT and BACK. A missing side creates/reopens an idempotent owner-specific `Action Required` item; it resolves only when that exact physical copy receives both approved sides. The audit does **not** list an unowned catalogue reference as saleable stock; it never automatically unpublishes stock or overrides a founder's existing photographic review.

## 2. Why this belongs
Live Supabase audit 7 Nov: all 506 approved for-sale physical items have published Shopify product/variant links, including eight graded items. There are **0 approved Shopify READY, rights-verified FIRST_PARTY_CAPTURE slab fronts/backs** in the DB; the graded source photos currently include PSA/ACE certification imagery recorded as `INTERNAL_REFERENCE_ONLY`. A product GID or external cert screenshot cannot be substituted for Drop Rate's own physical item. Two independent old `GRADED_SLAB_MEDIA_REQUIRED` actions remain OPEN; old founder review override decisions must be respected rather than overwritten.

## 3. Connections
`catalogue_maintenance.shopify_pass` (existing maintenance actor and hourly database advisory lock) → `shopify_graded_photo_audit.audit_published_graded_media` → `tcg.inventory_items + tcg.shopify_inventory_links + tcg.media_assets` (owner/inventory/rights exact-match) → `tcg.action_required_items` (existing owner/role-scoped and audited queue). Durable `SHOPIFY_SYNC` receipts include `graded_media_audit` with checked/ready/missing/open/resolved counts. No separate Shopify credentials required.

## 4. Failure points and tests
- A slab image is eligible only with **matching owner and inventory ID**, `scope='INVENTORY_ITEM'`, `capture_context='GRADED_SLAB'`, `rights_tier='FIRST_PARTY_CAPTURE'`, `approval_status='APPROVED'`, `rights_status='VERIFIED'`, `source_status='ACTIVE'`, not revoked, Shopify `READY` file ID. Raw card art, another founder's picture and PSA/ACE external certificate images cannot satisfy.
- Duplicate audit: existing OPEN dedupe is **not incremented**. A previously resolved issue is reopened only if the photo disappeared/rights revoked. Once both sides qualify, resolve only the DR100 dedupe—not an older founder exception.
- Stale/wrong Shopify product ID, unsupported actor, too many rows or DB issue → record an `INCOMPLETE` SHOPIFY_SYNC heartbeat and failure reason; continue the original publication reconciliation. Never block orders/refunds/settlements or change a Shopify product directly.
- Tests `tests/test_dr100_shopify_graded_photo_audit.py`, full backend, Postgres/CI, and Railway API predeploy all pass before production activation.

## 5. Rollout and remaining photo capture
Safe once deployed: founder/action queue will automatically show any missing exact-physical, shop-ready slab photos. The system can automate checking, not *taking photographs of physical slabs* or licensing third-party certification photography. Founders must capture first-party front/back images for every graded copy requiring publication; approval must be legitimate. Existing listed stock remains unchanged until independently reviewed. Owner-specific ID and original status are never edited by the audit.

This does **not** complete all future artwork, market pricing or Riftbound permission. See [DR-99 evidence and expiry incident](DR99_MARKET_EXPIRY_AND_SHOPIFY_MEDIA_AUDIT_20261107.md).
