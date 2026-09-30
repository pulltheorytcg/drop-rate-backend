# Drop Rate — Phase 2 Efficiency & Launch Audit

_Status: 30 September 2026. This audit follows the storefront-first operating manual; it does not replace it._

## Executive position

The catalogue engineering milestone is substantially complete, but Brand Redesign is **not yet approved for launch** under the Phase 2 publish gate.

The immediate goal is not more scope. It is to:
1. finish launch proof;
2. measure real operational/customer efficiency;
3. reduce/document complexity;
4. launch safely;
5. only then reopen deferred work deliberately.

## 1. Publish gate status

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Full mobile smoke on a real phone | PENDING HUMAN TEST | Cannot be certified from backend/system tools. Must test homepage → collection → filters/sort → PDP/grouped copies → cart → checkout → search → account. |
| Full desktop smoke | PENDING HUMAN TEST | Same flow must be completed after final Brand Redesign state is ready. |
| Real Brand Redesign purchase | PENDING | Existing Shopify orders are historical Horizon/test orders. A new purchase must be completed while Brand Redesign itself is MAIN. |
| HIGH `SHOPIFY_ORDER_WEBHOOK_GAP` alerts | VERIFIED HISTORICAL GAP | Both alerts point to the same historical Shopify test order #1001. Shopify received/processed its cancellation webhook, but no successful orders/create event exists and no local order was created. No stuck reservation remains. Treat as an acknowledged historical test gap; do not fabricate a missing order. |
| No CRITICAL Action Required | PASS | Current queue has no CRITICAL items. |
| Rollback plan | READY TO VERIFY AT LAUNCH | Intended rollback is republishing Horizon as MAIN. Confirm theme publish control immediately before launch. |

**Launch decision:** do not publish Brand Redesign until the remaining gates above pass.

## 2. Efficiency audit — system-side baseline

### Backend response timings

Railway HTTP telemetry from the latest production deployment shows normal authenticated application reads are generally sub-second:

- `GET /api/v1/access/me`: ~187 ms average.
- `GET /api/v1/inventory/brands`: ~151 ms average.
- `GET /api/v1/shopify/readiness`: ~236 ms average.
- `GET /api/v1/inventory`: ~419 ms average.
- `GET /api/v1/inventory/state`: ~474 ms average.
- `GET /api/v1/inventory/market-values`: ~524 ms average.
- finance summary/analytics reads are commonly ~0.4–0.6 s.
- eBay seller-status is materially slower, averaging ~1.18 s with a ~2.1 s maximum in the sampled window.

### Main performance concern found

Individual inventory-image requests are frequently taking approximately **1.8–2.1 seconds each**, with multiple examples near or above two seconds.

That matters more than many normal API timings because a mobile inventory grid may request many images at once. It is a credible contributor to the sluggish mobile experience and should be treated as a concrete Phase 2 optimisation target.

### Interpretation

The backend is not uniformly slow. The efficiency issue is concentrated:
- media/image delivery;
- external-provider-dependent calls;
- cumulative UI work when many resources are requested together.

This is preferable to a vague “the app is slow” diagnosis and gives us a measurable optimisation target.

## 3. Human efficiency tests still required

### One card, start to finish

Required real-device measurement:

`physical card → mobile scan → exact-print match → confirm identity → condition → price → live Shopify listing`

Record:
- elapsed time;
- number of screens;
- taps;
- waits >1 second;
- any point where the founder has to understand internal implementation detail.

This cannot be honestly certified without a physical card and real phone/camera session.

### One purchase, start to finish

Required customer measurement:

`homepage → find a specified card → PDP → cart → checkout completion`

Record:
- elapsed time;
- clicks/taps;
- search/filter friction;
- cart/checkout surprises.

This should be performed once Brand Redesign can be made MAIN for the launch test.

## 4. Complexity audit

Production currently runs seven Railway services.

This is not automatically excessive, but every service now has an explicit purpose in `docs/PRODUCTION_SYSTEM_MAP.md`.

The two PSA services are **not being deleted**. Review showed they implement a valuable future capability: exact PSA certificate lookup and exact official slab-media retrieval. They should be formalised/consolidated later, not discarded.

The stronger simplification target is:
- remove undocumented/duplicate responsibilities;
- keep core business rules in one FastAPI/Postgres layer;
- reduce temporary migration workers after launch stability;
- avoid building custom infrastructure where Shopify/provider-native tooling already solves the problem.

## 5. GitHub stale-PR audit

The previously open stale/superseded set has been reviewed and closed:

- #309
- #311
- #312
- #313
- #314
- #317
- #325

They were not closed blindly.

The useful functionality is present in later merged/current production work:
- current `shopify_pooling.py` contains deterministic raw pooling, physical-owner preservation, publication safety and customer-safe pooled copy;
- current Brand Redesign PDP already has pooled `N in stock` behaviour;
- the broad audit-table permission proposed by #314 was superseded by the safer merged protected `SECURITY DEFINER` audit writers in #315;
- #312's standalone migration worker targeted the legacy linked-draft conversion state, while current production has zero linked drafts and has already completed the pooled migration via the later merged path;
- #325's counts were superseded by the current consolidated checkpoint.

## 6. Current 17-item unlinked inventory

The count is still real:

- 8 Dragon Ball exact-print exceptions;
- 7 One Piece raw cards;
- 2 One Piece sealed products.

### Dragon Ball

Remain fail-closed until exact-print evidence or first-party physical capture exists. Do not substitute visually similar base/promo art.

### Seven One Piece raw cards

A production evidence review found:
- physical language is NULL on all seven;
- original Collectr source rows contain identity/variant information but no physical language;
- no prior identity-verification events exist for these items;
- no verified provider catalogue mappings exist for them;
- one canonical provider image is English, but canonical image language is not sufficient proof of the physical copy's language.

**Decision:** leave them blocked until physical review/scan supplies real evidence.

### Two sealed products

Remain blocked on real physical/package inputs, including exact first-party package media, language/region, packed dimensions/weight, sealed shipping profile and applicable seal-status evidence.

**Decision:** do not guess.

## 7. Graded slab exceptions

Two `GRADED_SLAB_MEDIA_REQUIRED` items remain intentionally open:

- Nico Robin ACE 10 cert 590532: exact official ACE front is verified; official back is unavailable. Listing may remain live under the recorded founder override while the back evidence stays open.
- Charizard V PSA 9 cert 62398872: PSA confirms the certificate identity/grade but the exact slab scans are not currently available in the registry.

**Decision:** never substitute another slab.

## 8. Historical Horizon order question

Shopify currently has two historical test orders:

- #1002: reached Drop Rate correctly, mapped to a physical Inventory ID/owner and was later refunded/cancelled.
- #1001: Shopify-side cancelled test order. Its cancellation webhook was processed, but no successful `orders/create` webhook/local `tcg.orders` row exists. There is no stuck reservation.

The two current HIGH webhook-gap alerts are duplicate owner-scoped alerts for this same #1001 historical condition.

This does **not** count as the Brand Redesign launch purchase proof.

## 9. Google Shopping

Do not build a custom n8n feed.

After Brand Redesign is public:
- use Shopify's native Google & YouTube channel / Merchant Center integration;
- start with free organic listings;
- do not enable paid Shopping campaigns without explicit founder commercial approval;
- use n8n later for Merchant Center diagnostics → Drop Rate Action Required, not as the feed source.

## 10. n8n launch discipline

The n8n server exists, but advanced production automation remains intentionally dormant.

Before new production workflows:
1. first workflow must be low-risk and boring, e.g. Action Required → notification;
2. signed event in;
3. existing event idempotency key reused;
4. safe duplicate retry proven;
5. n8n error workflow configured;
6. workflow JSON exported to GitHub;
7. credentials remain in n8n credential store;
8. business decisions remain in FastAPI/Postgres.

There are currently no completed automation-run records demonstrating this Phase 2 production workflow pattern, so the proof still needs to be done.

## 11. Recommended immediate sequence

1. Keep Brand Redesign unpublished.
2. Close/document the historical #1001 webhook-gap alerts without fabricating data.
3. Optimise/diagnose the slow inventory-image path.
4. Complete real-phone one-card timing test when a founder is available.
5. Complete mobile + desktop Brand Redesign smoke.
6. Make Brand Redesign MAIN for the controlled launch test and complete one real purchase.
7. Verify correct order/owner attribution and rollback procedure.
8. Publish only after every gate passes.
9. Get one outside person to make a purchase before marketing.
10. Define a measurable stability threshold before reopening Seller Hub, recognition, pricing-provider, cross-channel or autonomous growth scope.
