# Storefront Launch Rollback Plan

_Last verified: 30 September 2026_

## Purpose

This is the Phase 2 rollback procedure for the Brand Redesign launch. It is intentionally simple: **theme rollback only**. Do not alter Supabase ownership, Shopify product inventory, prices, orders or settlement records merely because the storefront theme is rolled back.

## Verified pre-launch state

Shopify theme state was read directly from the Admin API:

- **Horizon** — role: `MAIN`
- **Drop Rate — Brand Redesign** — role: `UNPUBLISHED`
- Drop Rate — Storefront Dev — `UNPUBLISHED`
- Drop Rate – Grouped PDP Preview — `UNPUBLISHED`

Shopify's current Admin GraphQL schema exposes the supported `themePublish(id: ID!)` mutation. The operation contract was schema-validated during this review.

## Launch

When the final Phase 2 smoke gates have passed:

1. Open Shopify Admin → **Online Store → Themes**.
2. Publish **Drop Rate — Brand Redesign**.
3. Confirm Brand Redesign is now the live/current theme.
4. Immediately run the post-publish smoke:
   - homepage;
   - collection + filters/sort;
   - PDP / grouped copies;
   - cart;
   - native checkout entry;
   - search;
   - account/login;
   - exact-copy / pooled stock behaviour.
5. Complete the controlled real purchase required by Phase 2 and verify:
   - confirmation email;
   - Shopify order;
   - Drop Rate order;
   - exact physical Inventory ID allocation;
   - correct owner attribution;
   - no oversell or reconciliation alert.

## Emergency rollback

If Brand Redesign causes a checkout-blocking or material commerce defect during launch:

1. Open Shopify Admin → **Online Store → Themes**.
2. Locate **Horizon** in the theme library.
3. Use the theme action menu and choose **Publish**.
4. Confirm the publish action.
5. Re-read theme state and verify:
   - **Horizon = MAIN**
   - Brand Redesign is no longer MAIN.
6. Run a minimal Horizon recovery smoke:
   - homepage loads;
   - product page loads;
   - cart accepts an in-stock item;
   - checkout entry opens.
7. Record the rollback in BUILD_STATUS / incident notes before attempting another Brand Redesign publish.

## What rollback must NOT do

Do not:
- delete or archive Shopify products;
- rewrite inventory quantities;
- change physical ownership;
- fabricate/cancel Drop Rate orders;
- reset Shopify webhooks;
- alter prices or settlement state;
- delete Brand Redesign.

The failure domain is the **theme presentation layer** unless evidence proves otherwise.

## Tooling boundary

The connected Shopify integration can read theme state and validate the `themePublish` contract, but direct theme publishing is intentionally blocked by the tool safety boundary. The actual launch/rollback publish action must therefore be performed through Shopify Admin by an authorized founder/operator.

That limitation is useful for this gate: a production theme cannot be silently switched by an automated review task.
