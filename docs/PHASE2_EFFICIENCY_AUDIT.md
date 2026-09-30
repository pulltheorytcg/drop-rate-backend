# Drop Rate — Phase 2 Efficiency & Simplicity Audit

_Last measured: 30 September 2026_

## Executive result

The system is technically capable, but the full Phase 2 human-efficiency claim is **not yet verified**.

What can be measured from production today shows:
- ordinary founder/dashboard API reads are generally sub-second;
- recognition resolution is the clearest measured latency hotspot;
- some inventory-image responses are also materially slower than normal API reads;
- the catalogue/publication backend is no longer the dominant blocker;
- the real-phone start-to-live card test and real Brand Redesign purchase test still require a human/device and must not be replaced by a synthetic claim.

This audit deliberately separates **machine-side evidence** from the two manual tests required by the operating manual.

## 1. Production complexity baseline

At the start of this audit:
- Railway: 7 services;
- Supabase: 68 base tables in `tcg`;
- Shopify: 470 ACTIVE products;
- physical FOR_SALE inventory: 509;
- published physical Shopify links: 492;
- unlinked FOR_SALE: 17;
- Brand Redesign: unpublished;
- verified real external-customer sales: still not established.

Two of the seven Railway services are confirmed temporary diagnostics with no inbound dependencies. Their deletion is staged, reducing the intended steady-state Railway topology to five services.

## 2. Machine-side latency evidence

Production Railway HTTP logs were sampled from real application use across 27–30 September.

### Recognition

Observed `POST /api/v1/recognition/resolve` completions:
- **5.100 s**
- **12.413 s**
- **21.672 s**

Observed sample median: **12.413 s** (n=3).

This is the clearest measured performance hotspot. It is large enough to dominate perceived scan speed even when the surrounding UI/API is fast.

### Typical founder/dashboard reads

Recent observed medians:
- `/api/v1/inventory/brands`: ~119 ms
- `/api/v1/pricing/inventory`: ~119 ms
- `/api/v1/inventory/intelligence`: ~244 ms
- `/api/v1/shopify/readiness`: ~237 ms
- `/api/v1/inventory`: ~481 ms
- `/api/v1/inventory/state`: ~554 ms
- `/api/v1/inventory/market-values`: ~590 ms

These are not instant, but they are not currently the main reason a card scan feels slow.

### Inventory images

A number of inventory image responses were observed around **1.5–2.8 s**, while others were in the ~100–400 ms range.

This variance can make grids/scanner confirmation feel much slower than the underlying metadata API. It should be profiled later by image source/cache path rather than solved by adding infrastructure.

## 3. Card start-to-live test

Required manual path:

`physical card → mobile scan → exact-print match → confirm identity → set condition/price → Shopify live`

### What is verified now

Machine-side evidence confirms:
- recognition can resolve a request successfully;
- inventory/readiness APIs are functioning;
- controlled Shopify publication paths exist and the current catalogue has 0 linked drafts;
- publication retains deterministic owner/Inventory ID attribution;
- ambiguous identity/media cases correctly stop rather than guess.

### What is not yet verified

A true Phase 2 result still needs, on a real phone:
- elapsed wall-clock time;
- number of screens;
- number of taps;
- time spent waiting for recognition;
- time spent on identity/condition/price confirmation;
- time until Shopify is verified live.

No synthetic benchmark should be substituted for that test.

### Current optimization hypothesis

Based on production timing alone, recognition/provider resolution is the first place to investigate if the real-phone test exceeds the target. UI/API metadata reads are secondary.

## 4. Customer purchase test

Required manual path:

`homepage → find a specific card → PDP/grouped copy → cart → checkout → confirmation → Drop Rate owner attribution`

### What is verified now

- Shopify native cart/checkout architecture exists.
- Historical paid test order #1002 successfully created a Drop Rate order and exact physical inventory/owner attribution, then refund/cancellation handling was exercised.
- That historical test was on the old launch context and does **not** satisfy the Phase 2 Brand Redesign purchase gate.

### What is not yet verified

The final measurement needs Brand Redesign itself and a real customer-style journey:
- elapsed time;
- clicks/taps;
- search/browse friction;
- checkout completion;
- confirmation email;
- Founder HQ/Seller Hub visibility;
- exact owner allocation.

## 5. Concrete issues found by this audit

### Pooled public copy — fixed

The stale-PR review found two live Dragon Ball quantity-2 pooled products still used single-copy wording and exposed one member's internal Inventory ID.

Actions completed:
- both Shopify descriptions corrected without changing quantity, SKU or price;
- PR #311 preserved/merged for the Brand Redesign PDP stock/internal-ref fix;
- PR #337 ported the missing pooled-description hardening onto current main;
- CI passed and production deployment succeeded.

### Historical #1001 webhook gap — durable fix deployed

#1001 was an unpaid PENDING test order that was cancelled, had a successfully processed `orders/cancelled` webhook, left no reservation/local sale, and was followed by successful #1002.

PR #338 changes reconciliation so a cancelled unpaid remote-only order with processed cancellation evidence is terminally acknowledged. Paid-like remote-only orders remain CRITICAL; uncancelled pending orders with missing create proof remain HIGH.

### Temporary Railway diagnostics — staged for deletion

`psa-cert-lookup-temp` and `psa-fetch-batch` were useful investigation tools on 29 September but are not production dependencies. Railway independently confirmed no inbound dependency and staged both deletions. Dashboard 2FA is required to commit the destructive change.

### Action Required queue — three stale media exceptions identified

There are 11 OPEN `MEDIA_UNRESOLVED` items but only 8 genuinely unresolved Dragon Ball printings. Three older records correspond to cards that later resolved and are already published:
- BT18-067 Krillin;
- BT18-138 Reaper's Cunning;
- BT13-142 Dark King Mechikabura.

They should be reconciled through the Action Required lifecycle rather than deleted directly.

## 6. Simplicity conclusions

The product does not need another infrastructure layer before launch.

The useful simplifications are:
- remove temporary services;
- close/supersede stale PRs only after preserving unique behavior;
- keep one authoritative operations monitor;
- keep n8n dormant until one low-risk workflow proves the pattern;
- do not build a custom Google Shopping feed;
- optimize measured recognition/image bottlenecks instead of adding general-purpose services;
- retire the one-shot Shopify reconciliation worker later if launch stability proves it is no longer useful.

## 7. Launch stability definition

Brand Redesign is considered **stable enough to reopen deferred workstreams** only after all of the following are true:

1. Brand Redesign has remained MAIN for at least **72 consecutive hours** without a checkout-blocking rollback.
2. At least **5 genuine paid non-founder customer orders** have completed successfully.
3. Those orders contain **zero owner-attribution, physical Inventory ID allocation, oversell or settlement discrepancies**.
4. There have been **zero CRITICAL Action Required items for 72 consecutive hours**.
5. No post-launch Shopify order remains with an unresolved webhook/reconciliation gap.
6. At least one outside person who did not build the platform has completed the purchase path and their usability findings have been recorded.

Passing this bar does not reopen everything automatically. It permits an explicit review to reopen **one frozen workstream at a time**.

## 8. Remaining Phase 2 human checks

Before theme publication:
- full mobile Brand Redesign smoke on a real phone;
- full desktop Brand Redesign smoke;
- real Brand Redesign test purchase and confirmation/owner-attribution verification;
- measure the real card scan-to-live path and count taps/screens;
- measure the customer find-to-checkout path and count clicks.

Those are the only efficiency/publish-gate checks in this audit that cannot be honestly completed from backend/store data alone.
